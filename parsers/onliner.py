import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
import logging
import aiohttp

logger = logging.getLogger(__name__)

API_URL = "https://r.onliner.by/sdapi/ak.api/search/apartments"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://r.onliner.by/",
}

# Minsk bounding box
BOUNDS = {
    "bounds[lb][lat]": 53.85,
    "bounds[lb][long]": 27.35,
    "bounds[rt][lat]": 53.97,
    "bounds[rt][long]": 27.75,
}


async def parse_onliner(max_price_usd: int = 350) -> list[dict]:
    params = {
        **BOUNDS,
        "price[min]": 1,
        "price[max]": max_price_usd,
        "currency": "usd",
        "order": "created_at:desc",
        "page": 1,
    }

    ads = []
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(
                API_URL, params=params, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Onliner API returned {resp.status}")
                    return []
                data = await resp.json()

        items = data.get("apartments", [])
        logger.info(f"Onliner raw items: {len(items)}")

        for item in items:
            ad_id = item.get("id")
            if not ad_id:
                continue

            price_data = item.get("price", {}).get("converted", {})
            price_usd = price_data.get("USD", {}).get("amount")
            if price_usd is None:
                continue
            try:
                price = float(price_usd)
            except (ValueError, TypeError):
                continue
            if price > max_price_usd:
                continue

            price_byn = price_data.get("BYN", {}).get("amount")
            if price_byn is not None:
                try:
                    price_byn = round(float(price_byn), 2)
                except (ValueError, TypeError):
                    price_byn = None

            posted_at = None
            raw_time = item.get("created_at")
            if raw_time:
                try:
                    dt = datetime.fromisoformat(raw_time)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=ZoneInfo("Europe/Minsk"))
                    else:
                        dt = dt.astimezone(ZoneInfo("Europe/Minsk"))
                    posted_at = dt.strftime("%d.%m.%Y %H:%M")
                except Exception:
                    pass

            address = (item.get("location") or {}).get("address") or "Минск"

            rent_type = item.get("rent_type", "")
            title_map = {
                "room": "Комната",
                "1_room": "1-комнатная",
                "2_rooms": "2-комнатная",
                "3_rooms": "3-комнатная",
                "4_rooms": "4-комнатная+",
            }
            title = title_map.get(rent_type, "")

            raw_photo = item.get("photo")
            images = []
            if raw_photo:
                images.append(raw_photo)

            url = f"https://r.onliner.by/ak/apartments/{ad_id}"

            ads.append({
                "id": f"onliner_{ad_id}",
                "title": title,
                "price": round(price, 2),
                "price_byn": price_byn,
                "posted_at": posted_at,
                "address": address,
                "url": url,
                "source": "onliner",
                "images": images,
            })

    except asyncio.TimeoutError:
        logger.error("Onliner request timed out")
    except Exception as e:
        logger.error(f"Onliner error: {e}", exc_info=True)

    return ads
