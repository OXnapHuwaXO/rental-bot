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
    max_price_cents = max_price_usd * 100

    params = {
        "cat": "1010",           # Квартиры, долгосрочная аренда
        "cur": "USD",
        "prc": f"r:0,{max_price_cents}",
        "sort": "lst.d",         # Новые сначала
        "size": 30,
        "lang": "ru",
        "rgn": "minsk",          # Только Минск
        "ar": "v.minsk",         # Дополнительный фильтр города
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

            # Цена в USD
            price = None
            for param in item.get("ad_parameters", []):
                if param.get("p") == "price_usd":
                    try:
                        price = float(param["v"]) / 100
                    except Exception:
                        pass

            if price is None:
                for field in ("price_usd", "usd_price"):
                    raw = item.get(field)
                    if raw:
                        try:
                            price = float(raw) / 100 if float(raw) > 10000 else float(raw)
                        except Exception:
                            pass

            if price is not None and price > max_price_usd:
                continue

            # Адрес
            address_parts = []
            for param in item.get("ad_parameters", []):
                label = param.get("pl", "").lower()
                value = param.get("vl", "")
                if any(kw in label for kw in ("город", "район", "улица", "адрес", "metro", "метро")):
                    if value:
                        address_parts.append(value)

            if not address_parts:
                city = item.get("city_name") or "Минск"
                region = item.get("region_name")
                parts = [p for p in [city, region] if p]
                address_parts = parts

            address = ", ".join(address_parts) if address_parts else "Минск"

            # Проверка что объявление из Минска
            full_text = (title + address + str(item.get("city_name", ""))).lower()
            if address and any(kw in full_text for kw in ("минск", "minsk")):
                pass  # ок
            elif not address:
                continue  # пропускаем без адреса

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
