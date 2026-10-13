"""WooCommerce trgovine - javni Store API (/wp-json/wc/store/v1/products), isti koji koristi njihova stranica.

Nova WooCommerce trgovina = jedan red u SHOPS + pravilo dostave u core/shipping.py.
Kako prepoznati: https://trgovina/wp-json/wc/store/v1/products?search=x vraća JSON listu.
"""
import html

from core.http import session
from core.models import Offer
from core.shipping import shop_shipping, to_eur

from .base import Source, fetch_pages

PAGE_SIZE = 100  # najviše što Store API dopušta

SHOPS = {  # name: (label, base_url)
    "padeltienda": ("Padel.tienda", "https://padel.tienda"),
    "todopadel": ("TodoPadel", "https://todopadel.shop"),
    "sportivo": ("Sportivo", "https://sportivo.hr"),
}


def _source(name: str) -> Source:
    label, base = SHOPS[name]

    async def to_offer(product: dict) -> Offer | None:
        prices = product.get("prices") or {}
        if not product.get("is_in_stock", True) or not prices.get("price"):
            return None
        price = await to_eur(int(prices["price"]) / 10 ** int(prices.get("currency_minor_unit", 2)),
                             prices.get("currency_code", "EUR"))
        ship, note, exact = shop_shipping(name, price)
        images = product.get("images") or [{}]
        return Offer(
            source=name, source_name=label, id=str(product.get("id")), title=html.unescape(product.get("name", "")),
            url=product.get("permalink", ""), price=price, condition="new", image=images[0].get("src", ""),
            shipping=ship, shipping_note=note, shipping_exact=exact,
            category=" ".join(c.get("name", "") for c in product.get("categories") or []),
        )

    async def search(query: str) -> list[Offer]:
        async with session() as client:
            async def page(n: int) -> list[dict]:
                response = await client.get(base + "/wp-json/wc/store/v1/products",
                                params={"search": query, "per_page": PAGE_SIZE, "page": n})
                response.raise_for_status()
                return response.json()

            products = await fetch_pages(page, full_page=PAGE_SIZE)
        return [o for o in [await to_offer(product) for product in products] if o]

    return Source(name, label, "shop", search)


SOURCES = [_source(name) for name in SHOPS]
