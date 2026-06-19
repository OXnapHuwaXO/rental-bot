import asyncio
import logging
import os
from dotenv import load_dotenv
load_dotenv()
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from parsers.kufar import parse_kufar
from parsers.realt import parse_realt
from storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
# Поддержка нескольких получателей: CHAT_IDS=111,222 или старый CHAT_ID=111
_raw_ids = os.getenv("CHAT_IDS") or os.getenv("CHAT_ID", "")
CHAT_IDS = [cid.strip() for cid in _raw_ids.split(",") if cid.strip()]
MAX_PRICE_USD = int(os.getenv("MAX_PRICE_USD", "350"))
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "10"))

bot = Bot(token=TOKEN)
dp = Dispatcher()
storage = Storage("seen_ads.json")
scheduler = AsyncIOScheduler()


async def check_new_ads():
    logger.info("Checking for new ads...")
    new_ads = []

    try:
        kufar_ads = await parse_kufar(max_price_usd=MAX_PRICE_USD)
        logger.info(f"Kufar: found {len(kufar_ads)} ads under ${MAX_PRICE_USD}")
        for ad in kufar_ads:
            if not storage.is_seen(ad["id"]):
                new_ads.append(ad)
                storage.mark_seen(ad["id"])
    except Exception as e:
        logger.error(f"Kufar parsing error: {e}")

    try:
        realt_ads = await parse_realt(max_price_usd=MAX_PRICE_USD)
        logger.info(f"Realt: found {len(realt_ads)} ads under ${MAX_PRICE_USD}")
        for ad in realt_ads:
            if not storage.is_seen(ad["id"]):
                new_ads.append(ad)
                storage.mark_seen(ad["id"])
    except Exception as e:
        logger.error(f"Realt parsing error: {e}")

    if new_ads:
        logger.info(f"Sending {len(new_ads)} new ads to {len(CHAT_IDS)} recipients")
        for ad in new_ads:
            await send_ad(ad)
    else:
        logger.info("No new ads found")

    storage.save()


async def send_ad(ad: dict):
    source_emoji = "🟠" if ad["source"] == "kufar" else "🔵"
    price_str = f"${ad['price']}" if ad.get("price") else "цена не указана"
    byn_str = f" ({ad['price_byn']} BYN)" if ad.get("price_byn") else ""
    address_str = ad.get("address") or "адрес не указан"

    text = (
        f"{source_emoji} <b>{ad['source'].upper()}</b>\n"
        f"💰 <b>{price_str}{byn_str}</b>\n"
        + (f"🕐 {ad['posted_at']}\n" if ad.get("posted_at") else "")
        + f"📍 {address_str}\n"
        + f"🔗 <a href='{ad['url']}'>Открыть объявление</a>"
    )
    if ad.get("title"):
        text = f"🏠 {ad['title']}\n" + text

    image = ad.get("image")

    for chat_id in CHAT_IDS:
        try:
            if image:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=image,
                    caption=text,
                    parse_mode="HTML",
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text=text + "\n\n📷 фото нет",
                    parse_mode="HTML",
                    disable_web_page_preview=False,
                )
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {e}")


@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "🏠 <b>Бот мониторинга аренды</b>\n\n"
        f"Слежу за новыми объявлениями на <b>Kufar</b> и <b>Realt</b> "
        f"до <b>${MAX_PRICE_USD}</b>.\n"
        f"Проверка каждые <b>{CHECK_INTERVAL_MINUTES} минут</b>.\n\n"
        "Команды:\n"
        "/start — показать это сообщение\n"
        "/check — проверить прямо сейчас\n"
        "/status — статус бота\n"
        "/myid — узнать свой Chat ID",
        parse_mode="HTML",
    )


@dp.message(Command("check"))
async def cmd_check(message: Message):
    await message.answer("🔍 Проверяю объявления...")
    await check_new_ads()
    await message.answer("✅ Проверка завершена!")


@dp.message(Command("status"))
async def cmd_status(message: Message):
    seen_count = storage.count()
    recipients = len(CHAT_IDS)
    await message.answer(
        f"✅ <b>Бот работает</b>\n\n"
        f"📊 Просмотрено объявлений: <b>{seen_count}</b>\n"
        f"💰 Максимальная цена: <b>${MAX_PRICE_USD}</b>\n"
        f"⏱ Интервал проверки: <b>{CHECK_INTERVAL_MINUTES} мин</b>\n"
        f"👥 Получателей: <b>{recipients}</b>",
        parse_mode="HTML",
    )


@dp.message(Command("myid"))
async def cmd_myid(message: Message):
    await message.answer(f"Ваш Chat ID: <code>{message.chat.id}</code>", parse_mode="HTML")


async def main():
    logger.info(f"Starting bot with {len(CHAT_IDS)} recipient(s)...")

    scheduler.add_job(
        check_new_ads,
        "interval",
        minutes=CHECK_INTERVAL_MINUTES,
        id="check_ads",
    )
    scheduler.start()

    asyncio.create_task(check_new_ads())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
