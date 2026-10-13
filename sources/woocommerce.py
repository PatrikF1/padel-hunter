"""WooCommerce trgovine - javni Store API (/wp-json/wc/store/v1/products), isti koji koristi njihova stranica.

Za pronađene rekete dohvaća se STVARNA dostava u HR: reket se doda u anonimnu košaricu, postavi se adresa
Zagreb 10000 i pročitaju ponuđene dostave. Ništa se ne naručuje, košarica nestaje sa sesijom.
Ako košarica ne odgovori, ostaje cijena iz cjenika (core/shipping.py), označena kao procjena ili cjenik.

Nova WooCommerce trgovina = jedan red u SHOPS (+ pravilo dostave u core/shipping.py kao rezerva).
Kako prepoznati: https://trgovina/wp-json/wc/store/v1/products?search=x vraća JSON listu.
"""
import asyncio
import html
import time

from core.http import session
from core.models import Offer
from core.shipping import shop_shipping, to_eur

from .base import Source, fetch_pages

API = "/wp-json/wc/store/v1"
PAGE_SIZE = 100       # najviše što Store API dopušta
QUOTE_PARALLEL = 3    # istovremenih provjera košarice po trgovini
QUOTE_MAX = 12        # najviše proizvoda po pretrazi kojima provjeravamo stvarnu dostavu (najjeftiniji prvi)
SHIPPING_TTL = 6 * 3600
HR_ADDRESS = {"country": "HR", "postcode": "10000", "city": "Zagreb", "state": "",
              "first_name": "", "last_name": "", "address_1": ""}

SHOPS = {  # name: (label, base_url)
    "padeltienda": ("Padel.tienda", "https://padel.tienda"),              # ES
    "todopadel": ("TodoPadel", "https://todopadel.shop"),                 # ES
    "padelprofi": ("Padel Profi", "https://padelprofideutschland.de"),    # DE, dodano 2026-10-13
}
NO_SHIPPING = "ne šalje u HR"
_quotes: dict[str, tuple[float, float | None, str]] = {}  # url proizvoda -> (vrijeme, dostava u EUR ili None, način)


async def _quote(base: str, offer: Offer) -> tuple[float | None, str]:
    """Najjeftinija dostava u HR za jedan proizvod: (cijena s porezom, naziv dostave) ili (None, ...) ako ne šalje."""
    cached = _quotes.get(offer.url)
    if cached and time.time() - cached[0] < SHIPPING_TTL:
        return cached[1], cached[2]
    async with session() as client:  # nova sesija = prazna košarica
        cart = await client.get(base + API + "/cart")
        headers = {"Nonce": cart.headers.get("nonce", ""), "Cart-Token": cart.headers.get("cart-token", "")}
        added = await client.post(base + API + "/cart/add-item", json={"id": int(offer.id), "quantity": 1}, headers=headers)
        if added.status_code != 201:
            raise RuntimeError(f"košarica: HTTP {added.status_code}")
        updated = await client.post(base + API + "/cart/update-customer", headers=headers,
                                    json={"shipping_address": HR_ADDRESS, "billing_address": HR_ADDRESS})
        updated.raise_for_status()
    rates = [rate for package in updated.json().get("shipping_rates", []) for rate in package.get("shipping_rates", [])]
    if not rates:
        quote = (None, NO_SHIPPING)
    else:
        def cost(rate: dict) -> float:  # cijena i porez su odvojeni, u najmanjim jedinicama valute (centi)
            return (int(rate["price"]) + int(rate.get("taxes") or 0)) / 10 ** int(rate.get("currency_minor_unit", 2))
        best = min(rates, key=cost)
        quote = (await to_eur(cost(best), best.get("currency_code", "EUR")), best.get("name", ""))
    _quotes[offer.url] = (time.time(), *quote)
    return quote


def _source(name: str) -> Source:
    label, base = SHOPS[name]
    limit = asyncio.Semaphore(QUOTE_PARALLEL)

    async def limited_quote(offer: Offer) -> tuple[float | None, str]:
        async with limit:
            return await _quote(base, offer)

    async def enrich(offers: list[Offer]) -> None:
        offers = sorted(offers, key=lambda o: o.price)[:QUOTE_MAX]
        quotes = await asyncio.gather(*(limited_quote(o) for o in offers), return_exceptions=True)
        for offer, quote in zip(offers, quotes):
            if isinstance(quote, Exception):
                continue  # ostaje cijena iz cjenika
            shipping, method = quote
            if shipping is None:
                offer.excluded = offer.shipping_note = NO_SHIPPING
            else:
                offer.shipping, offer.shipping_exact = shipping, True
                offer.shipping_note = f"stvarna cijena iz košarice: {method}"

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

    return Source(name, label, "shop", search, enrich)


SOURCES = [_source(name) for name in SHOPS]
