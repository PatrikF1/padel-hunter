"""Shopify trgovine.

Pretraga: /search/suggest.json. Za pronađene rekete dohvaća se STVARNA cijena dostave u HR:
reket se doda u anonimnu košaricu i pita se /cart/shipping_rates.json za Zagreb 10000.
Ništa se ne naručuje, košarica nestaje sa sesijom.

Nova Shopify trgovina = jedan red u SHOPS.
"""
import asyncio
import time
from dataclasses import dataclass

from core.http import session
from core.models import Offer
from core.shipping import to_eur

from .base import Source

SHOPS = {  # name: (label, base_url)
    "padelmarket": ("Padel Market", "https://padelmarket.com"),
    "padelproshop": ("Padel Pro Shop", "https://padelproshop.com"),
    "padelshop": ("Padelshop", "https://padelshop.com"),
    "padelpoint": ("Padel-Point", "https://www.padel-point.de"),
    "tennispoint": ("Tennis-Point", "https://www.tennis-point.com"),
    "padelwebshop": ("Padelwebshop", "https://padelwebshop.com"),
    "hollandpadel": ("Holland Padel", "https://hollandpadel.com"),
    "padelstore24": ("Padelstore24", "https://padelstore24.de"),
    "padelfreunde": ("Padelfreunde", "https://padelfreunde.de"),
    "justpadel": ("JustPadel", "https://justpadel.com"),
}
HR_ADDRESS = {"shipping_address[zip]": "10000", "shipping_address[country]": "Croatia",
              "shipping_address[province]": ""}
SHIPPING_TTL = 6 * 3600


@dataclass
class _Quote:
    at: float
    price: float            # cijena u košarici (EUR)
    shipping: float | None  # najjeftinija dostava u HR (EUR), None = ne šalje
    method: str
    sold_out: bool = False


_quotes: dict[str, _Quote] = {}  # url proizvoda -> zadnja ponuda


class ShopifyShop:
    def __init__(self, name: str, label: str, base: str):
        self.name, self.label, self.base = name, label, base

    async def search(self, query: str) -> list[Offer]:
        async with session() as s:
            r = await s.get(self.base + "/search/suggest.json",
                            params={"q": query, "resources[type]": "product", "resources[limit]": "10"})
            r.raise_for_status()
            products = r.json()["resources"]["results"].get("products", [])
        return [self._offer(p) for p in products if p.get("available", True)]

    def _offer(self, p: dict) -> Offer:
        path = p["url"].split("?")[0]
        img = p.get("image") or (p.get("featured_image") or {}).get("url") or ""
        return Offer(
            source=self.name, source_name=self.label, id=path.rsplit("/", 1)[-1], title=p["title"],
            url=self.base + path, price=float(p.get("price") or p.get("price_min") or 0), condition="new",
            image="https:" + img if img.startswith("//") else img,
            extra={"category": p.get("type") or ""},
        )

    async def _quote(self, url: str) -> _Quote:
        cached = _quotes.get(url)
        if cached and time.time() - cached.at < SHIPPING_TTL:
            return cached
        async with session() as s:  # nova sesija = prazna košarica
            product = (await s.get(url + ".js")).json()
            variant = next((v for v in product["variants"] if v.get("available")), product["variants"][0])
            added = await s.post(self.base + "/cart/add.js", json={"items": [{"id": variant["id"], "quantity": 1}]})
            if added.status_code != 200:  # npr. 422 "rasprodano" iako ga tražilica još prikazuje
                quote = _Quote(time.time(), 0.0, None, "", sold_out=True)
                _quotes[url] = quote
                return quote
            cart = (await s.get(self.base + "/cart.js")).json()
            currency = cart.get("currency", "EUR")
            price = await to_eur(cart["items"][0]["final_line_price"] / 100, currency)
            rates = (await s.get(self.base + "/cart/shipping_rates.json", params=HR_ADDRESS)).json()
        rates = rates.get("shipping_rates", [])
        if rates:
            best = min(rates, key=lambda r: float(r["price"]))
            shipping = await to_eur(float(best["price"]), best.get("currency") or currency)
            quote = _Quote(time.time(), price, shipping, best.get("name", ""))
        else:
            quote = _Quote(time.time(), price, None, "")
        _quotes[url] = quote
        return quote

    async def enrich(self, offers: list[Offer]) -> None:
        results = await asyncio.gather(*(self._quote(o.url) for o in offers), return_exceptions=True)
        for o, q in zip(offers, results):
            if isinstance(q, Exception):
                o.shipping_note = "dostava nije dohvaćena"
            elif q.sold_out:
                o.excluded = "rasprodano"
            elif q.shipping is None:
                o.excluded = o.shipping_note = "ne šalje u HR"
            else:
                o.price, o.shipping, o.shipping_exact = q.price, q.shipping, True
                o.shipping_note = f"stvarna cijena iz košarice: {q.method}"


def _source(name: str) -> Source:
    shop = ShopifyShop(name, *SHOPS[name])
    return Source(name, shop.label, "shop", shop.search, shop.enrich)


SOURCES = [_source(name) for name in SHOPS]
