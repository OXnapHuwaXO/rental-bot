import asyncio
from datetime import datetime
import json
import logging
import re
import aiohttp

logger = logging.getLogger(__name__)

REALT_URL = "https://realt.by/rent/flat-for-long/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://realt.by/",
}


async def parse_realt(max_price_usd: int = 350) -> list[dict]:
    ads = []
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(
                REALT_URL, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                logger.info(f"Realt URL: {resp.url}, status: {resp.status}")
                if resp.status != 200:
                    logger.error(f"Realt.by returned HTTP {resp.status}")
                    return []
                html = await resp.text()

        # Данные в Next.js SSR-дампе
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            html, re.DOTALL,
        )
        if not match:
            logger.error("Realt.by: __NEXT_DATA__ not found")
            return []

        data = json.loads(match.group(1))
        page_props = data.get("props", {}).get("pageProps", {})
        objects = page_props.get("objects", [])

        total_count = page_props.get("totalCount", 0)
        logger.info(f"Realt.by objects: {len(objects)} (total: {total_count})")

        for obj in objects:
            try:
                code = obj.get("code")
                if not code:
                    continue

                # Цены из priceRates
                price_rates = obj.get("priceRates") or {}
                price = price_rates.get("840")
                if price is None:
                    continue

                price = float(price)
                if price > max_price_usd:
                    continue

                price_byn = price_rates.get("933")
                if price_byn is not None:
                    price_byn = float(price_byn)

                # Дата публикации
                posted_at = None
                raw_time = obj.get("createdAt")
                if raw_time:
                    try:
                        dt = datetime.fromisoformat(raw_time)
                        posted_at = dt.strftime("%d.%m.%Y %H:%M")
                    except Exception:
                        pass

                title = obj.get("title") or "Квартира в аренду"
                address = obj.get("address") or "Минск"
                url = f"https://realt.by/rent-flat-for-long/object/{code}/"

                # Первое фото
                images = obj.get("images", [])
                image = images[0] if images else None

                ads.append({
                    "id": f"realt_{code}",
                    "title": title,
                    "price": round(price, 2),
                    "price_byn": round(price_byn, 2) if price_byn else None,
                    "posted_at": posted_at,
                    "address": address,
                    "url": url,
                    "source": "realt",
                    "image": image,
                })

            except Exception as e:
                logger.debug(f"Realt object error: {e}")
                continue

    except asyncio.TimeoutError:
        logger.error("Realt.by timed out")
    except Exception as e:
        logger.error(f"Realt.by error: {e}", exc_info=True)

    return ads
