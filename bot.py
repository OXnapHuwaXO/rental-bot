import asyncio
import logging
import os
from dotenv import load_dotenv
load_dotenv()
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, InputMediaPhoto, BotCommand, BotCommandScopeDefault, BotCommandScopeAllPrivateChats, BotCommandScopeChat
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from parsers.kufar import parse_kufar
from parsers.realt import parse_realt
from parsers.onliner import parse_onliner
from parsers.domovita import parse_domovita
from parsers.neagent import parse_neagent
from storage import Storage, UserManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DEFAULT_MAX_PRICE_USD = int(os.getenv("MAX_PRICE_USD", "350"))
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "10"))
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

USER_COMMANDS = [
    BotCommand(command="start", description="Показать приветствие"),
    BotCommand(command="check", description="Проверить объявления сейчас"),
    BotCommand(command="status", description="Статус бота"),
    BotCommand(command="myid", description="Узнать свой Chat ID"),
    BotCommand(command="login", description="Войти в админ-панель"),
]

ADMIN_COMMANDS = [
    BotCommand(command="add", description="Добавить получателя"),
    BotCommand(command="remove", description="Удалить получателя"),
    BotCommand(command="users", description="Список получателей"),
    BotCommand(command="admin", description="Помощь по админке"),
    BotCommand(command="setprice", description="Сменить фильтр по цене"),
    BotCommand(command="getprice", description="Текущий фильтр по цене"),
    BotCommand(command="storage", description="Статистика просмотренных"),
    BotCommand(command="logout", description="Выйти из админки"),
]


async def set_user_commands():
    await bot.set_my_commands(
        USER_COMMANDS,
        scope=BotCommandScopeAllPrivateChats(),
    )


async def set_admin_commands(chat_id: int):
    full = USER_COMMANDS + ADMIN_COMMANDS
    await bot.set_my_commands(
        full,
        scope=BotCommandScopeChat(chat_id=chat_id),
    )


async def clear_admin_commands(chat_id: int):
    await bot.set_my_commands(
        USER_COMMANDS,
        scope=BotCommandScopeChat(chat_id=chat_id),
    )

bot = Bot(token=TOKEN)
dp = Dispatcher()
storage = Storage("seen_ads.json")
users = UserManager("users.json", default_max_price=DEFAULT_MAX_PRICE_USD)
scheduler = AsyncIOScheduler()


async def check_new_ads():
    logger.info("Checking for new ads...")
    new_ads = []

    parsers = [
        ("Kufar", parse_kufar),
        ("Realt", parse_realt),
        ("Onliner", parse_onliner),
        ("Domovita", parse_domovita),
        ("Neagent", parse_neagent),
    ]

    for name, parser in parsers:
        try:
            ads = await parser(max_price_usd=users.get_max_price())
            logger.info(f"{name}: found {len(ads)} ads under ${users.get_max_price()}")
            for ad in ads:
                ad_id = ad["id"]
                price = ad.get("price")
                price_byn = ad.get("price_byn")

                if not storage.is_seen(ad_id):
                    new_ads.append(ad)
                    storage.mark_seen(ad_id, price_usd=price, price_byn=price_byn)
                else:
                    old = storage.get_ad_data(ad_id)
                    if old and price is not None:
                        old_price = old.get("price_usd")
                        old_byn = old.get("price_byn")
                        if (old_price is not None and price < old_price
                                and old_byn is not None and price_byn is not None and price_byn < old_byn):
                            ad["price_drop"] = True
                            ad["old_price_usd"] = old_price
                            ad["old_price_byn"] = old_byn
                            new_ads.append(ad)
                    storage.update_ad_price(ad_id, price, price_byn)
        except Exception as e:
            logger.error(f"{name} parsing error: {e}")

    if new_ads:
        chat_ids = users.list_users()
        logger.info(f"Sending {len(new_ads)} new ads to {len(chat_ids)} recipients")
        for ad in new_ads:
            await send_ad(ad, chat_ids)
    else:
        logger.info("No new ads found")

    storage.save()


async def quiet_init():
    """Первый запуск: собрать ID объявлений без отправки."""
    logger.info("Storage empty — quiet init: collecting ad IDs without sending")
    parsers = [
        ("Kufar", parse_kufar),
        ("Realt", parse_realt),
        ("Onliner", parse_onliner),
        ("Domovita", parse_domovita),
        ("Neagent", parse_neagent),
    ]
    total = 0
    for name, parser in parsers:
        try:
            ads = await parser(max_price_usd=users.get_max_price())
            count = 0
            for ad in ads:
                if not storage.is_seen(ad["id"]):
                    storage.mark_seen(ad["id"], price_usd=ad.get("price"), price_byn=ad.get("price_byn"))
                    count += 1
            total += count
            logger.info(f"Quiet init [{name}]: marked {count} ads as seen")
        except Exception as e:
            logger.error(f"Quiet init [{name}] error: {e}")
    storage.save()
    logger.info(f"Quiet init complete: {total} ads cached")


async def send_ad(ad: dict, chat_ids: list[int]):
    emoji_map = {"kufar": "🟠", "realt": "🔵", "onliner": "🟢", "domovita": "🟣", "neagent": "🔴"}
    source_emoji = emoji_map.get(ad["source"], "⚪")
    price_str = f"${ad['price']}" if ad.get("price") else "цена не указана"
    if ad.get("price_drop") and ad.get("old_price_usd") is not None:
        price_str += f" <s>(${ad['old_price_usd']})</s>"
    byn_str = f" ({ad['price_byn']} BYN" if ad.get("price_byn") else ""
    if ad.get("price_drop") and ad.get("old_price_byn") is not None:
        byn_str += f", было {ad['old_price_byn']} BYN"
    if byn_str:
        byn_str += ")"
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

    images = ad.get("images", [])

    for chat_id in chat_ids:
        sent = False
        if images:
            try:
                media = [
                    InputMediaPhoto(media=url, caption=text if i == 0 else None, parse_mode="HTML")
                    for i, url in enumerate(images)
                ]
                await bot.send_media_group(chat_id=chat_id, media=media)
                sent = True
            except Exception:
                pass

        if not sent:
            no_photo_text = text + "\n\n📷 фото нет"
            if len(no_photo_text) > 1024:
                no_photo_text = no_photo_text[:1021] + "..."
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=no_photo_text,
                    parse_mode="HTML",
                    disable_web_page_preview=False,
                )
            except Exception as e:
                logger.error(f"Failed to send message to {chat_id}: {e}")
                continue

        try:
            chat = await bot.get_chat(chat_id)
            username = chat.username
            if username:
                users.set_username(chat_id, username)
        except Exception:
            pass


@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "🏠 <b>Бот мониторинга аренды</b>\n\n"
        f"Слежу за новыми объявлениями на <b>Kufar</b> и <b>Realt</b> "
        f"до <b>${users.get_max_price()}</b>.\n"
        f"Проверка каждые <b>{CHECK_INTERVAL_MINUTES} минут</b>.\n\n"
        "Команды:\n"
        "/start — показать это сообщение\n"
        "/check — проверить прямо сейчас\n"
        "/status — статус бота\n"
        "/myid — узнать свой Chat ID\n"
        "/login &lt;пароль&gt; — войти в админку\n\n"
        "Админ-команды:\n"
        "/add &lt;id&gt; — добавить получателя\n"
        "/remove &lt;id&gt; — удалить получателя\n"
        "/users — список получателей\n"
        "/setprice &lt;сумма&gt; — сменить фильтр по цене\n"
        "/getprice — текущий фильтр по цене\n"
        "/storage — статистика просмотренных\n"
        "/logout — выйти из админки",
        parse_mode="HTML",
    )


@dp.message(Command("check"))
async def cmd_check(message: Message):
    if not users.list_users():
        await message.answer("⚠️ Нет получателей. Добавьте через /add команду (требуется админ).")
        return
    await message.answer("🔍 Проверяю объявления...")
    await check_new_ads()
    await message.answer("✅ Проверка завершена!")


@dp.message(Command("status"))
async def cmd_status(message: Message):
    seen_count = storage.count()
    recipients = users.count()
    admin_status = "✅" if users.is_admin(message.chat.id) else "❌"
    await message.answer(
        f"✅ <b>Бот работает</b>\n\n"
        f"📊 Просмотрено объявлений: <b>{seen_count}</b>\n"
        f"💰 Максимальная цена: <b>${users.get_max_price()}</b>\n"
        f"⏱ Интервал проверки: <b>{CHECK_INTERVAL_MINUTES} мин</b>\n"
        f"👥 Получателей: <b>{recipients}</b>\n"
        f"🔑 Админ: {admin_status}",
        parse_mode="HTML",
    )


@dp.message(Command("myid"))
async def cmd_myid(message: Message):
    await message.answer(f"Ваш Chat ID: <code>{message.chat.id}</code>", parse_mode="HTML")


@dp.message(Command("login"))
async def cmd_login(message: Message):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /login &lt;пароль&gt;")
        return
    password = parts[1]
    if password != ADMIN_PASSWORD:
        await message.answer("❌ Неверный пароль")
        return
    users.add_admin(message.chat.id)
    await set_admin_commands(message.chat.id)
    await message.answer(admin_help_text(), parse_mode="HTML")


ADMIN_HELP = (
    "🔑 <b>Админ-панель</b>\n\n"
    "Команды:\n"
    "/add &lt;chat_id&gt; — добавить получателя\n"
    "/remove &lt;chat_id&gt; — удалить получателя\n"
    "/users — список получателей\n"
    "/admin — показать эту справку\n"
    "/setprice &lt;сумма&gt; — сменить фильтр по цене ($)\n"
    "/getprice — текущий фильтр по цене\n"
    "/storage — статистика просмотренных объявлений\n"
    "/logout — выйти из админки"
)


def admin_help_text() -> str:
    return "✅ <b>Вы авторизованы как администратор</b>\n\n" + ADMIN_HELP


@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not users.is_admin(message.chat.id):
        await message.answer("❌ Только администратор. Используйте /login")
        return
    await message.answer(ADMIN_HELP, parse_mode="HTML")


@dp.message(Command("logout"))
async def cmd_logout(message: Message):
    if not users.is_admin(message.chat.id):
        await message.answer("❌ Вы не авторизованы")
        return
    users.remove_admin(message.chat.id)
    await clear_admin_commands(message.chat.id)
    await message.answer("✅ Вы вышли из админки")


@dp.message(Command("add"))
async def cmd_add(message: Message):
    if not users.is_admin(message.chat.id):
        await message.answer("❌ Только администратор. Используйте /login")
        return
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /add &lt;chat_id&gt;")
        return
    try:
        chat_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Chat ID должен быть числом. Узнать: /myid")
        return
    if users.add_user(chat_id):
        try:
            chat = await bot.get_chat(chat_id)
            username = chat.username
            if username:
                users.set_username(chat_id, username)
                await message.answer(f"✅ @{username} (<code>{chat_id}</code>) добавлен", parse_mode="HTML")
            else:
                await message.answer(f"✅ Пользователь <code>{chat_id}</code> добавлен", parse_mode="HTML")
        except Exception:
            await message.answer(f"✅ Пользователь <code>{chat_id}</code> добавлен", parse_mode="HTML")
    else:
        await message.answer(f"ℹ️ Пользователь <code>{chat_id}</code> уже в списке", parse_mode="HTML")


@dp.message(Command("remove"))
async def cmd_remove(message: Message):
    if not users.is_admin(message.chat.id):
        await message.answer("❌ Только администратор. Используйте /login")
        return
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /remove &lt;chat_id&gt;")
        return
    try:
        chat_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Chat ID должен быть числом")
        return
    if users.remove_user(chat_id):
        await message.answer(f"✅ Пользователь <code>{chat_id}</code> удалён", parse_mode="HTML")
    else:
        await message.answer(f"❌ Пользователь <code>{chat_id}</code> не найден", parse_mode="HTML")


@dp.message(Command("users"))
async def cmd_users(message: Message):
    if not users.is_admin(message.chat.id):
        await message.answer("❌ Только администратор. Используйте /login")
        return

    # Дозаполняем username, если пустые
    for u in users.users_without_username():
        try:
            chat = await bot.get_chat(u)
            if chat.username:
                users.set_username(u, chat.username)
        except Exception:
            pass

    admin_ids = users.get_admin_ids()
    admin_lines = []
    for aid in admin_ids:
        try:
            chat = await bot.get_chat(aid)
            uname = chat.username
            if uname:
                admin_lines.append(f"@{uname} <code>{aid}</code>")
            else:
                admin_lines.append(f"<code>{aid}</code>")
        except Exception:
            admin_lines.append(f"<code>{aid}</code>")
    admin_info = "\n".join(admin_lines) if admin_lines else "❓"

    display = users.list_users_display()
    if not display:
        text = f"🔑 <b>Админы:</b>\n{admin_info}\n\n📋 Получателей нет"
    else:
        text = (
            f"🔑 <b>Админы:</b>\n{admin_info}\n\n"
            f"📋 <b>Получатели:</b>\n" + "\n".join(f"• {line}" for line in display)
        )
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("setprice"))
async def cmd_setprice(message: Message):
    if not users.is_admin(message.chat.id):
        await message.answer("❌ Только администратор. Используйте /login")
        return
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /setprice &lt;сумма в USD&gt;")
        return
    try:
        price = int(parts[1])
    except ValueError:
        await message.answer("❌ Сумма должна быть числом")
        return
    if price <= 0:
        await message.answer("❌ Сумма должна быть положительной")
        return
    users.set_max_price(price)
    await message.answer(
        f"✅ Фильтр по цене изменён на <b>${price}</b>\n"
        f"💰 Текущая максимальная цена: <b>${users.get_max_price()}</b>",
        parse_mode="HTML",
    )


@dp.message(Command("getprice"))
async def cmd_getprice(message: Message):
    if not users.is_admin(message.chat.id):
        await message.answer("❌ Только администратор. Используйте /login")
        return
    await message.answer(
        f"💰 Текущий фильтр по цене: <b>${users.get_max_price()}</b>",
        parse_mode="HTML",
    )


@dp.message(Command("storage"))
async def cmd_storage(message: Message):
    if not users.is_admin(message.chat.id):
        await message.answer("❌ Только администратор. Используйте /login")
        return
    total = storage.count()
    breakdown = storage.breakdown_by_source()
    lines = [f"📊 <b>Всего просмотрено:</b> {total}"]
    if breakdown:
        emoji_map = {"kufar": "🟠", "realt": "🔵", "onliner": "🟢", "domovita": "🟣", "neagent": "🔴"}
        for src in sorted(breakdown):
            emoji = emoji_map.get(src, "❓")
            lines.append(f"{emoji} {src.capitalize()}: <b>{breakdown[src]}</b>")
    await message.answer("\n".join(lines), parse_mode="HTML")


async def main():
    # Миграция: если users пуст, пробуем забрать из CHAT_IDS или CHAT_ID
    if users.count() == 0:
        old_ids = os.getenv("CHAT_IDS") or os.getenv("CHAT_ID", "")
        for cid in old_ids.split(","):
            cid = cid.strip()
            if cid:
                try:
                    users.add_user(int(cid))
                except ValueError:
                    pass
    logger.info(f"Starting bot with {users.count()} recipient(s)...")
    await set_user_commands()
    for aid in users.get_admin_ids():
        await set_admin_commands(aid)

    scheduler.add_job(
        check_new_ads,
        "interval",
        minutes=CHECK_INTERVAL_MINUTES,
        id="check_ads",
    )
    scheduler.start()

    if storage.count() == 0:
        await quiet_init()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
