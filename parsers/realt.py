import asyncio
import logging
import re
import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Правильный URL долгосрочной аренды в Минске
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


def extract_price_usd(text: str) -> float | None:
    text = text.replace("\u00a0", " ").replace("\xa0", " ").strip()
    patterns = [
        r"(\d[\d\s]*)\s*usd",
        r"\$\s*(\d[\d\s]*)",
        r"(\d[\d\s]*)\s*\$",
        r"(\d[\d\s]*)\s*у\.е",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(" ", ""))
            except ValueError:
                pass
    return None


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

        soup = BeautifulSoup(html, "html.parser")

        # Ищем карточки объявлений
        cards = (
            soup.select("article.object-item")
            or soup.select("div.object-item")
            or soup.select("[class*='object-item']")
            or soup.select("li[class*='item']")
            or soup.select("div[class*='catalog']")
        )

        logger.info(f"Realt.by cards: {len(cards)}")

        # Если карточки не нашли — ищем ссылки на объявления напрямую
        if not cards:
            all_links = soup.select("a[href]")
            cards = [
                a for a in all_links
                if re.search(r"/rent/flat[^/]*/[^/]+/\d+", a.get("href", ""))
            ]
            logger.info(f"Realt.by fallback links: {len(cards)}")

        seen_urls = set()

        for card in cards:
            try:
                link_tag = card if card.name == "a" else card.find("a", href=True)
                if not link_tag:
                    continue

                href = link_tag.get("href", "")
                if not href or href in seen_urls:
                    continue
                if not href.startswith("http"):
                    href = "https://realt.by" + href

                # Только страницы конкретных объявлений
                if not re.search(r"/rent/flat[^/]*/[^/]+/\d+", href):
                    continue

                seen_urls.add(href)
                ad_id = "realt_" + re.sub(r"\D", "", href)[-12:]

                # Заголовок
                title_tag = (
                    card.find(class_=re.compile(r"title|name|heading", re.I))
                    or card.find("h2") or card.find("h3") or card.find("h1")
                )
                title = title_tag.get_text(strip=True) if title_tag else "Квартира в аренду"

                # Цена
                price_tag = card.find(class_=re.compile(r"price|cost", re.I))
                price = None
                if price_tag:
                    price = extract_price_usd(price_tag.get_text(strip=True))
                    if price is None:
                        # Ищем число + USD в любом тексте карточки
                        full_text = card.get_text(" ", strip=True)
                        price = extract_price_usd(full_text)

                if price is not None and price > max_price_usd:
                    continue

                # Адрес
                addr_tag = card.find(class_=re.compile(r"addr|location|street|district|place|geo", re.I))
                address = addr_tag.get_text(strip=True) if addr_tag else None

                if not address:
                    for tag in card.find_all(["span", "div", "p"]):
                        txt = tag.get_text(strip=True)
                        if len(txt) > 5 and any(kw in txt for kw in ("ул.", "пр.", "пер.", "г.", "Минск")):
                            address = txt
                            break

                if not address:
                    address = "Минск"
                elif "минск" not in address.lower():
                    address = "Минск, " + address

                ads.append({
                    "id": ad_id,
                    "title": title,
                    "price": round(price, 2) if price else None,
                    "address": address,
                    "url": href,
                    "source": "realt",
                })

            except Exception as e:
                logger.debug(f"Realt card error: {e}")
                continue

    except asyncio.TimeoutError:
        logger.error("Realt.by timed out")
    except Exception as e:
        logger.error(f"Realt.by error: {e}", exc_info=True)

    return ads
