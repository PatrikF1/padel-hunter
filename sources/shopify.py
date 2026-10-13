"""Shopify trgovine.

Pretraga: /search/suggest.json. Za pronađene rekete dohvaća se STVARNA cijena dostave u HR:
reket se doda u anonimnu košaricu i pita se /cart/shipping_rates.json za Zagreb 10000.
Ništa se ne naručuje, košarica nestaje sa sesijom.

Nova Shopify trgovina = jedan red u SHOPS.
"""
import asyncio
import json
import re
import time
from dataclasses import dataclass

from core.http import session, text
from core.models import Offer
from core.shipping import to_eur

from .base import MAX_PAGES, Source

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
QUOTE_PARALLEL = 5  # istovremenih provjera košarice po trgovini (da nas ne blokiraju)
QUOTE_MAX = 40      # najviše proizvoda po pretrazi kojima provjeravamo stvarnu dostavu


@dataclass
class _Quote:
    at: float
    price: float            # cijena u košarici (EUR)
    shipping: float | None  # najjeftinija dostava u HR (EUR), None = ne šalje
    method: str
    sold_out: bool = False
    image: str = ""


_quotes: dict[str, _Quote] = {}  # url proizvoda -> zadnja ponuda


class ShopifyShop:
    def __init__(self, name: str, label: str, base: str):
        self.name, self.label, self.base = name, label, base
        self.limit = asyncio.Semaphore(QUOTE_PARALLEL)

    async def search(self, query: str) -> list[Offer]:
        """Spaja dva izvora: brzi prijedlog (do 10, sa slikama i zalihom) i SVE stranice pretrage
        (proizvodi iz ShopifyAnalytics podataka na stranici). Rasprodano otkrije košarica u enrich()."""
        async with session() as client:
            suggest, pages = await asyncio.gather(self._suggest(client, query), self._search_pages(client, query))
        by_handle = {o.id: o for o in pages}
        by_handle.update({o.id: o for o in suggest})  # prijedlog ima bolje podatke (slika, zaliha)
        return list(by_handle.values())

    async def _suggest(self, client, query: str) -> list[Offer]:
        response = await client.get(self.base + "/search/suggest.json",
                        params={"q": query, "resources[type]": "product", "resources[limit]": "10"})
        response.raise_for_status()
        products = response.json()["resources"]["results"].get("products", [])
        return [self._suggest_offer(product) for product in products if product.get("available", True)]

    def _suggest_offer(self, product: dict) -> Offer:
        path = product["url"].split("?")[0]
        img = product.get("image") or (product.get("featured_image") or {}).get("url") or ""
        return Offer(
            source=self.name, source_name=self.label, id=path.rsplit("/", 1)[-1], title=product["title"],
            url=self.base + path, price=float(product.get("price") or product.get("price_min") or 0), condition="new",
            image="https:" + img if img.startswith("//") else img,
            category=product.get("type") or "",
        )

    async def _search_pages(self, client, query: str) -> list[Offer]:
        async def page(n: int) -> str:
            response = await client.get(self.base + "/search", params={"q": query, "type": "product", "page": n})
            response.raise_for_status()
            return text(response)

        try:
            first = await page(1)
            last = min(max((int(n) for n in re.findall(r"[?&;]page=(\d+)", first)), default=1), MAX_PAGES)
            rest = await asyncio.gather(*(page(n) for n in range(2, last + 1)), return_exceptions=True)
        except Exception:
            return []  # tema bez stranice pretrage - ostaje prijedlog
        offers = []
        for html in [first, *(r for r in rest if isinstance(r, str))]:
            offers += await self._page_offers(html)
        return offers

    async def _page_offers(self, html: str) -> list[Offer]:
        meta = re.search(r"var meta = (\{.*?\});\s*for \(var attr in meta\)", html, re.S)
        currency = re.search(r'Shopify\.currency\s*=\s*\{"active":"(\w+)"', html)
        if not meta:
            return []
        offers = []
        for product in json.loads(meta.group(1)).get("products", []):
            variant = (product.get("variants") or [{}])[0]
            title = variant.get("name", "")
            if variant.get("public_title") and title.endswith(" - " + variant["public_title"]):
                title = title[: -len(variant["public_title"]) - 3]
            if not product.get("handle") or not variant.get("price") or not title:
                continue
            price = await to_eur(variant["price"] / 100, currency.group(1) if currency else "EUR")
            offers.append(Offer(
                source=self.name, source_name=self.label, id=product["handle"], title=title,
                url=f"{self.base}/products/{product['handle']}", price=price, condition="new",
                category=product.get("type") or "",
            ))
        return offers

    async def _quote(self, url: str) -> _Quote:
        cached = _quotes.get(url)
        if cached and time.time() - cached.at < SHIPPING_TTL:
            return cached
        async with session() as client:  # nova sesija = prazna košarica
            product = (await client.get(url + ".js")).json()
            variant = next((v for v in product["variants"] if v.get("available")), product["variants"][0])
            image = product.get("featured_image") or ""
            image = "https:" + image if image.startswith("//") else image
            added = await client.post(self.base + "/cart/add.js", json={"items": [{"id": variant["id"], "quantity": 1}]})
            if added.status_code != 200:  # npr. 422 "rasprodano" iako ga tražilica još prikazuje
                quote = _Quote(time.time(), 0.0, None, "", sold_out=True)
                _quotes[url] = quote
                return quote
            cart = (await client.get(self.base + "/cart.js")).json()
            currency = cart.get("currency", "EUR")
            price = await to_eur(cart["items"][0]["final_line_price"] / 100, currency)
            rates = (await client.get(self.base + "/cart/shipping_rates.json", params=HR_ADDRESS)).json()
        rates = rates.get("shipping_rates", [])
        if rates:
            best = min(rates, key=lambda r: float(r["price"]))
            shipping = await to_eur(float(best["price"]), best.get("currency") or currency)
            quote = _Quote(time.time(), price, shipping, best.get("name", ""), image=image)
        else:
            quote = _Quote(time.time(), price, None, "", image=image)
        _quotes[url] = quote
        return quote

    async def _limited_quote(self, url: str) -> _Quote:
        async with self.limit:
            return await self._quote(url)

    async def enrich(self, offers: list[Offer]) -> None:
        offers = sorted(offers, key=lambda o: o.price)[:QUOTE_MAX]
        results = await asyncio.gather(*(self._limited_quote(o.url) for o in offers), return_exceptions=True)
        for o, q in zip(offers, results):
            if isinstance(q, Exception):
                o.shipping_note = "dostava nije dohvaćena"
            elif q.sold_out:
                o.excluded = "rasprodano"
            elif q.shipping is None:
                o.excluded = o.shipping_note = "ne šalje u HR"
            else:
                o.price, o.shipping, o.shipping_exact = q.price, q.shipping, True
                o.image = o.image or q.image
                o.shipping_note = f"stvarna cijena iz košarice: {q.method}"


def _source(name: str) -> Source:
    shop = ShopifyShop(name, *SHOPS[name])
    return Source(name, shop.label, "shop", shop.search, shop.enrich)


SOURCES = [_source(name) for name in SHOPS]
