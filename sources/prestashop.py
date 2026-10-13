"""PrestaShop trgovine - njihova pretraga vraća JSON kad se pozove kao AJAX.

Nova PrestaShop trgovina = jedan red u SHOPS + pravilo dostave u core/shipping.py.
"""
from urllib.parse import quote_plus

from core.http import session
from core.models import Offer
from core.shipping import shop_shipping

from .base import Source

SHOPS = {  # name: (label, search_url_template)
    "zonadepadel": ("Zona de Padel", "https://www.zonadepadel.com/search?controller=search&s={q}"),
    "time2padel": ("Time2Padel", "https://www.time2padel.com/en/look-for?s={q}"),
}
AJAX_HEADERS = {"accept": "application/json", "x-requested-with": "XMLHttpRequest"}


def _source(name: str) -> Source:
    label, url_template = SHOPS[name]

    def to_offer(p: dict) -> Offer | None:
        price = float(p.get("price_amount") or 0)
        if not price:
            return None
        ship, note, exact = shop_shipping(name, price)
        cover = (p.get("cover") or {}).get("large") or {}
        return Offer(
            source=name, source_name=label, id=str(p.get("id_product")), title=p.get("name", ""),
            url=p.get("url") or p.get("canonical_url") or "", price=price, condition="new",
            image=cover.get("url", ""), shipping=ship, shipping_note=note, shipping_exact=exact,
            extra={"category": p.get("category_name") or ""},
        )

    async def search(query: str) -> list[Offer]:
        async with session() as s:
            r = await s.get(url_template.format(q=quote_plus(query)), headers=AJAX_HEADERS)
            r.raise_for_status()
            return [o for o in map(to_offer, r.json().get("products", [])) if o]

    return Source(name, label, "shop", search)


SOURCES = [_source(name) for name in SHOPS]
