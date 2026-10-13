"""Trgovine bez upotrebljive tražilice (uglavnom hrvatske): čita se CIJELA kategorija padel reketa
(sve stranice), a matcher sam izdvoji traženi model. Kategorija se pamti 30 min.

Nova trgovina = jedan unos u SHOPS (CSS selektori kartice proizvoda) + pravilo dostave u core/shipping.py.
"""
import asyncio
import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from core.http import eur, session, text
from core.models import Offer
from core.shipping import shop_shipping

from .base import Source

CACHE_TTL = 30 * 60
MAX_PAGES = 15


@dataclass(frozen=True)
class Shop:
    label: str
    url: str            # prva stranica kategorije
    page_param: str     # parametar za stranice ("page", "p"), "" = sve je na jednoj stranici
    card: str           # CSS selektor kartice proizvoda
    title: str          # selektor naslova ("img@alt" = atribut alt prve slike)
    price: str          # selektor trenutne cijene (prvi koji postoji, odvojeno zarezom)


SHOPS = {
    "vidmarsport": Shop("Vidmar Sport", "https://www.vidmarsport.com/katalog/padel/padel-reket/", "page",
                        ".artikl-wrapper", "img@alt", ".discount-price, .price"),
    "teniswil": Shop("Teniswil", "https://teniswil.hr/katalog/padel/reketi-za-padel/", "",
                     ".prod-item", "img@alt", ".price-now"),
    "marines": Shop("Marines Sport", "https://www.marines-sport.hr/reketi", "page",
                    ".single-product", ".product-name", ".price-new, .price"),
    "tenniszone": Shop("Tennis Zone", "https://tennis-zone.hr/padel/reketi/", "p",
                       ".product-box", ".product-name@title", ".product-price"),
}


def _select(node, selector: str) -> str:
    """'.klasa' -> tekst, '.klasa@atribut' -> atribut, 'a, b' -> prvi koji postoji."""
    for sel in (s.strip() for s in selector.split(",")):
        css, _, attr = sel.partition("@")
        el = node.css_first(css)
        if el:
            value = (el.attributes.get(attr) or "") if attr else el.text(strip=True)
            if value:
                return value
    return ""


def parse(name: str, shop: Shop, html: str) -> list[Offer]:
    offers = []
    for card in LexborHTMLParser(html).css(shop.card):
        title, price = _select(card, shop.title), eur(_select(card, shop.price))
        link = card.css_first("a[href]")
        if not title or not price or not link:
            continue
        url = urljoin(shop.url, link.attributes.get("href", ""))
        img = card.css_first("img")
        image = (img.attributes.get("data-src") or img.attributes.get("src") or "") if img else ""
        ship, note, exact = shop_shipping(name, price)
        offers.append(Offer(
            source=name, source_name=shop.label, id=url.rstrip("/").rsplit("/", 1)[-1], title=title, url=url,
            price=price, condition="new", image=urljoin(shop.url, image) if image else "",
            shipping=ship, shipping_note=note, shipping_exact=exact,
        ))
    return offers


def _last_page(html: str, param: str) -> int:
    pages = [int(n) for n in re.findall(rf"[?&]{param}=(\d+)", html)]
    return min(max(pages, default=1), MAX_PAGES)


def _source(name: str) -> Source:
    shop = SHOPS[name]
    cache: dict = {"at": 0.0, "offers": []}
    lock = asyncio.Lock()

    async def fetch_all() -> list[Offer]:
        async with session() as s:
            first = text(await s.get(shop.url))
            pages = [first]
            if shop.page_param:
                sep = "&" if "?" in shop.url else "?"
                rest = await asyncio.gather(*(s.get(f"{shop.url}{sep}{shop.page_param}={n}")
                                              for n in range(2, _last_page(first, shop.page_param) + 1)))
                pages += [text(r) for r in rest]
        offers = list({o.url: o for html in pages for o in parse(name, shop, html)}.values())
        if not offers:
            raise RuntimeError("kategorija je prazna - stranica je možda promijenila izgled")
        return offers

    async def search(query: str) -> list[Offer]:
        async with lock:  # više istovremenih upita = jedno skidanje kategorije
            if time.time() - cache["at"] > CACHE_TTL:
                cache.update(at=time.time(), offers=await fetch_all())
        return cache["offers"]

    return Source(name, shop.label, "shop", search)


SOURCES = [_source(name) for name in SHOPS]
