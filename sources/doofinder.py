"""Trgovine koje koriste Doofinder tražilicu (javni search API koji koristi i njihova stranica).

Nova Doofinder trgovina = jedan red u SHOPS (hashid se nalazi u eu1-config.doofinder.com/2.x/<id>.js
na njihovoj stranici) + pravilo dostave u core/shipping.py.
"""
from core.http import session
from core.models import Offer
from core.shipping import shop_shipping

from .base import Source

SEARCH_URL = "https://eu1-search.doofinder.com/5/search"
SHOPS = {  # name: (label, hashid, origin)
    "padelnuestro": ("Padel Nuestro", "3680782b48e397920a52a2287bc777a2", "https://www.padelnuestro.com"),
    "padelreference": ("Padel Reference", "9fb34dfbeeb4c84220e4aebc3739fcc3", "https://www.padelreference.com"),
}
IN_STOCK = {"in stock", "instock", "available"}


def _source(name: str) -> Source:
    label, hashid, origin = SHOPS[name]

    def to_offer(p: dict) -> Offer | None:
        if str(p.get("availability", "in stock")).lower() not in IN_STOCK:
            return None
        price = float(p.get("sale_price") or p.get("best_price") or p.get("price") or 0)
        if not price:
            return None
        ship, note, exact = shop_shipping(name, price)
        categories = p.get("categories") or []
        return Offer(
            source=name, source_name=label, id=str(p.get("id") or p.get("link")), title=p.get("title", ""),
            url=p.get("link", ""), price=price, condition="new", image=p.get("image_link", ""),
            shipping=ship, shipping_note=note, shipping_exact=exact,
            extra={"category": " ".join(categories) if isinstance(categories, list) else str(categories)},
        )

    async def search(query: str) -> list[Offer]:
        async with session() as s:
            r = await s.get(SEARCH_URL, params={"hashid": hashid, "query": query, "rpp": 30},
                            headers={"origin": origin, "referer": origin + "/"})
            r.raise_for_status()
            return [o for o in map(to_offer, r.json().get("results", [])) if o]

    return Source(name, label, "shop", search)


SOURCES = [_source(name) for name in SHOPS]
