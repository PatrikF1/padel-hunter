"""PrestaShop trgovine - njihova pretraga vraća JSON kad se pozove kao AJAX.

Nova PrestaShop trgovina = jedan red u SHOPS + pravilo dostave u core/shipping.py.
"""
import asyncio
from urllib.parse import quote_plus

from core.http import session
from core.models import Offer
from core.shipping import shop_shipping

from .base import MAX_PAGES, Source

PAGE_SIZE = 100  # trgovina može vratiti i manje po stranici

SHOPS = {  # name: (label, search_url_template)
    "zonadepadel": ("Zona de Padel", "https://www.zonadepadel.com/search?controller=search&s={q}"),
    "time2padel": ("Time2Padel", "https://www.time2padel.com/en/look-for?s={q}"),
    "stockpadel": ("StockPadel", "https://www.stockpadel.com/search?controller=search&s={q}"),
    "areapadel": ("Area Padel", "https://areapadel.com/search?controller=search&s={q}"),
    "ipontennis": ("Ipon Tennis", "https://www.ipontennis.com/search?controller=search&s={q}"),
}
AJAX_HEADERS = {"accept": "application/json", "x-requested-with": "XMLHttpRequest"}


def _source(name: str) -> Source:
    label, url_template = SHOPS[name]

    def to_offer(product: dict) -> Offer | None:
        price = float(product.get("price_amount") or 0)
        if not price:
            return None
        ship, note, exact = shop_shipping(name, price)
        cover = (product.get("cover") or {}).get("large") or {}
        return Offer(
            source=name, source_name=label, id=str(product.get("id_product")), title=product.get("name", ""),
            url=product.get("url") or product.get("canonical_url") or "", price=price, condition="new",
            image=cover.get("url", ""), shipping=ship, shipping_note=note, shipping_exact=exact,
            category=product.get("category_name") or "",
        )

    async def search(query: str) -> list[Offer]:
        async with session() as client:
            async def page(n: int) -> dict:
                url = url_template.format(q=quote_plus(query)) + f"&resultsPerPage={PAGE_SIZE}&page={n}"
                response = await client.get(url, headers=AJAX_HEADERS)
                response.raise_for_status()
                return response.json()

            first = await page(1)  # trgovina sama kaže koliko ima stranica
            pages_count = min(int((first.get("pagination") or {}).get("pages_count") or 1), MAX_PAGES)
            rest = await asyncio.gather(*(page(n) for n in range(2, pages_count + 1)), return_exceptions=True)
            products = [p for j in [first, *rest] if isinstance(j, dict) for p in j.get("products", [])]
        return [o for o in map(to_offer, products) if o]

    return Source(name, label, "shop", search)


SOURCES = [_source(name) for name in SHOPS]
