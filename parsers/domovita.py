import asyncio
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo
import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://domovita.by/minsk/flats/rent"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://domovita.by/",
}


def _parse_price_usd(text: str) -> float | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d.,]", "", text).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_price_byn(text: str) -> float | None:
    if not text:
        return None
    # Text format: "1 020 р./мес.366 $/мес.319 €/мес.26 894 ₽/мес."
    m = re.search(r"([\d\s]+)\s*р\.", text)
    if m:
        cleaned = m.group(1).replace(" ", "")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


async def parse_domovita(max_price_usd: int = 350) -> list[dict]:
    ads = []
    page = 1
    limit = 15

    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            while page <= limit:
                url = BASE_URL if page == 1 else f"{BASE_URL}?page={page}"
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status != 200:
                        logger.error(f"Domovita HTTP {resp.status} on page {page}")
                        break
                    html = await resp.text()

                soup = BeautifulSoup(html, "html.parser")
                cards = soup.select(".found_item.OFlatsRent")
                if not cards:
                    break

                for card in cards:
                    try:
                        ad_id = card.get("data-key")
                        if not ad_id:
                            continue

                        title_el = card.select_one(".title.title--listing")
                        title = title_el.get_text(strip=True) if title_el else ""

                        price_usd_el = card.select_one(".price-usd")
                        price_usd_text = price_usd_el.get_text(strip=True) if price_usd_el else ""
                        price = _parse_price_usd(price_usd_text)
                        if price is None or price > max_price_usd:
                            continue

                        price_byn_el = card.select_one(".price")
                        price_byn_text = price_byn_el.get_text(strip=True) if price_byn_el else ""
                        price_byn = _parse_price_byn(price_byn_text)

                        date_el = card.select_one(".date")
                        date_text = date_el.get_text(strip=True) if date_el else ""
                        posted_at = None
                        if date_text:
                            try:
                                dt = datetime.strptime(date_text, "%d.%m.%Y")
                                dt = dt.replace(tzinfo=ZoneInfo("Europe/Minsk"))
                                posted_at = dt.strftime("%d.%m.%Y %H:%M")
                            except Exception:
                                pass

                        # Address from JSON-LD
                        jsonld = card.find("script", type="application/ld+json")
                        address = "Минск"
                        if jsonld:
                            try:
                                import json
                                ld = json.loads(jsonld.string)
                                addr = ld.get("address", {})
                                if isinstance(addr, dict):
                                    parts = [v for v in [addr.get("addressLocality"), addr.get("streetAddress")] if v]
                                    if parts:
                                        address = ", ".join(parts)
                            except Exception:
                                pass

                        images = []
                        for img in card.select(".slider-img-in-listing__item img"):
                            src = img.get("src") or img.get("data-url-img") or ""
                            if not src or "noimage" in src or src.startswith("data:"):
                                continue
                            images.append(src)
                            if len(images) >= 3:
                                break

                        link_el = card.select_one("a[href*='/minsk/flats/rent/']")
                        if not link_el:
                            link_el = card.select_one("a.title")
                        if not link_el and card.name == "a" and card.get("href"):
                            link_el = card
                        listing_url = link_el.get("href", "") if link_el else ""

                        ads.append({
                            "id": f"domovita_{ad_id}",
                            "title": title,
                            "price": round(price, 2) if price else None,
                            "price_byn": round(price_byn, 2) if price_byn else None,
                            "posted_at": posted_at,
                            "address": address,
                            "url": listing_url,
                            "source": "domovita",
                            "images": images,
                        })

                    except Exception as e:
                        logger.debug(f"Domovita card error: {e}")
                        continue

                logger.info(f"Domovita page {page}: {len(cards)} cards")
                page += 1

    except asyncio.TimeoutError:
        logger.error("Domovita request timed out")
    except Exception as e:
        logger.error(f"Domovita error: {e}", exc_info=True)

    return ads
