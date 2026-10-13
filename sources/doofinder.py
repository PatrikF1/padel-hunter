"""Trgovine koje koriste Doofinder tražilicu (javni search API koji koristi i njihova stranica).

Nova Doofinder trgovina = jedan red u SHOPS (hashid se nalazi u eu1-config.doofinder.com/2.x/<id>.js
na njihovoj stranici) + pravilo dostave u core/shipping.py.
"""
from core.http import session
from core.models import Offer
from core.shipping import shop_shipping

from .base import Source, fetch_pages

PAGE_SIZE = 100

SEARCH_URL = "https://eu1-search.doofinder.com/5/search"
SHOPS = {  # name: (label, hashid, origin)
    "padelnuestro": ("Padel Nuestro", "7e6b0c88e88ddd9134bc543a8a37572e", "https://www.padelnuestro.com"),  # /int/ trgovina
    "padelreference": ("Padel Reference", "9fb34dfbeeb4c84220e4aebc3739fcc3", "https://www.padelreference.com"),
}
IN_STOCK = {"in stock", "instock", "available"}


def _source(name: str) -> Source:
    label, hashid, origin = SHOPS[name]

    def to_offer(product: dict) -> Offer | None:
        if str(product.get("availability", "in stock")).lower() not in IN_STOCK:
            return None
        price = float(product.get("sale_price") or product.get("best_price") or product.get("price") or 0)
        if not price:
            return None
        ship, note, exact = shop_shipping(name, price)
        categories = product.get("categories") or []
        return Offer(
            source=name, source_name=label, id=str(product.get("id") or product.get("link")), title=product.get("title", ""),
            url=product.get("link", ""), price=price, condition="new", image=product.get("image_link", ""),
            shipping=ship, shipping_note=note, shipping_exact=exact,
            category=" ".join(categories) if isinstance(categories, list) else str(categories),
        )

    async def search(query: str) -> list[Offer]:
        async with session() as client:
            async def page(n: int) -> list[dict]:
                response = await client.get(SEARCH_URL, params={"hashid": hashid, "query": query, "rpp": PAGE_SIZE, "page": n},
                                headers={"origin": origin, "referer": origin + "/"})
                response.raise_for_status()
                return response.json().get("results", [])

            return [o for o in map(to_offer, await fetch_pages(page, full_page=PAGE_SIZE)) if o]

    return Source(name, label, "shop", search)


SOURCES = [_source(name) for name in SHOPS]
