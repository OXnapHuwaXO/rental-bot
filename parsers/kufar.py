import asyncio
import logging
import aiohttp

logger = logging.getLogger(__name__)

KUFAR_API_URL = "https://api.kufar.by/search-api/v2/search/rendered-paginated"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://www.kufar.by/",
}


async def parse_kufar(max_price_usd: int = 350) -> list[dict]:
    params = {
        "cat": "1010",           # Квартиры, долгосрочная аренда
        "cur": "USD",
        "prc": f"r:0,{max_price_usd}",
        "sort": "lst.d",         # Новые сначала
        "size": 30,
        "lang": "ru",
        "rgn": "7",              # Только Минск (ID региона)
    }

    ads = []
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(
                KUFAR_API_URL, params=params, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Kufar API returned {resp.status}")
                    return []
                data = await resp.json()

        items = data.get("ads", [])
        logger.info(f"Kufar raw items: {len(items)}")

        for item in items:
            ad_id = str(item.get("ad_id") or item.get("id", ""))
            if not ad_id:
                continue

            title = item.get("subject", "")
            url = f"https://www.kufar.by/item/{ad_id}"

            # Цена в USD (API возвращает в центах, делим на 100)
            price = None
            raw_price = item.get("price_usd")
            if raw_price:
                try:
                    price = float(raw_price) / 100
                except Exception:
                    pass

            if price is not None and price > max_price_usd:
                continue

            # Адрес: сначала из account_parameters, потом из ad_parameters
            address_parts = []
            for param in item.get("account_parameters", []):
                if param.get("p") == "address":
                    val = param.get("v", "")
                    if val:
                        address_parts.append(val)

            if not address_parts:
                for param in item.get("ad_parameters", []):
                    if param.get("p") == "area":
                        val = param.get("vl", "")
                        if val:
                            address_parts.append(val)

            if not address_parts:
                for param in item.get("ad_parameters", []):
                    if param.get("p") == "region":
                        val = param.get("vl", "")
                        if val:
                            address_parts.append(val)

            address = ", ".join(address_parts) if address_parts else "Минск"

            ads.append({
                "id": f"kufar_{ad_id}",
                "title": title,
                "price": round(price, 2) if price else None,
                "address": address,
                "url": url,
                "source": "kufar",
            })

    except asyncio.TimeoutError:
        logger.error("Kufar request timed out")
    except Exception as e:
        logger.error(f"Kufar parsing error: {e}", exc_info=True)

    return ads
