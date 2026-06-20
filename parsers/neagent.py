import asyncio
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo
import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://neagent.by/kvartira/snyat"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://neagent.by/",
}


def _parse_price_usd(text: str) -> float | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d.]", "", text)
    try:
        return float(cleaned)
    except ValueError:
        return None


async def parse_neagent(max_price_usd: int = 350) -> list[dict]:
    ads = []

    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(
                BASE_URL, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                logger.info(f"Neagent status: {resp.status}")
                if resp.status != 200:
                    logger.error(f"Neagent HTTP {resp.status}")
                    return []
                html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("div.c-card")
        logger.info(f"Neagent raw cards: {len(cards)}")

        for card in cards:
            try:
                card_id = card.get("id", "")
                if not card_id.startswith("n"):
                    continue
                ad_id = card_id[1:]
                if not ad_id:
                    continue

                price_usd_str = card.get("data-price-secondary", "")
                price = _parse_price_usd(price_usd_str)
                if price is None or price > max_price_usd:
                    continue

                title_el = card.select_one("a.c-card__title")
                if not title_el:
                    continue
                title = title_el.get("title") or title_el.get_text(strip=True) or ""
                href = title_el.get("href", "")
                listing_url = href if href.startswith("http") else f"https://neagent.by{href}" if href else ""

                addr_el = card.select_one("div.c-card__addr")
                address = addr_el.get_text(strip=True) if addr_el else "Минск"

                # Try to get date from detail page (skip if too expensive)
                posted_at = None

                images = []
                for img in card.select("img"):
                    src = img.get("data-src") or img.get("src") or ""
                    if not src or "/f_uploads/" not in src:
                        continue
                    if src.startswith("//"):
                        src = "https:" + src
                    images.append(src)
                    if len(images) >= 3:
                        break

                ads.append({
                    "id": f"neagent_{ad_id}",
                    "title": title,
                    "price": round(price, 2) if price else None,
                    "price_byn": None,
                    "posted_at": posted_at,
                    "address": address,
                    "url": listing_url,
                    "source": "neagent",
                    "images": images,
                })

            except Exception as e:
                logger.debug(f"Neagent card error: {e}")
                continue

    except asyncio.TimeoutError:
        logger.error("Neagent request timed out")
    except Exception as e:
        logger.error(f"Neagent error: {e}", exc_info=True)

    return ads
