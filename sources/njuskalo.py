"""Njuškalo - najveći HR oglasnik (HTML pretraga, sortirano od najnovijeg)."""
from selectolax.lexbor import LexborHTMLParser

from core.http import eur, session, text
from core.matcher import looks_new
from core.models import Offer
from core.shipping import marketplace_shipping

from .base import Source

NAME, LABEL = "njuskalo", "Njuškalo"
BASE = "https://www.njuskalo.hr"


def _text(node, selector: str) -> str:
    el = node.css_first(selector)
    return el.text(strip=True) if el else ""


def _attr(node, selector: str, attr: str) -> str:
    el = node.css_first(selector)
    return (el.attributes.get(attr) or "") if el else ""


def parse(html: str) -> list[Offer]:
    ship, note, exact = marketplace_shipping(NAME)
    offers = []
    for li in LexborHTMLParser(html).css("li.listing"):
        link = li.css_first("h3.title a")
        price = eur(_text(li, ".price"))
        if not link or not price:
            continue
        title = link.text(strip=True)
        offers.append(Offer(
            source=NAME, source_name=LABEL, id=link.attributes.get("name") or link.attributes.get("href", ""),
            title=title, url=BASE + link.attributes.get("href", ""), price=price,
            condition="new" if looks_new(title) else "used",
            image=_attr(li, "img", "src"),
            shipping=ship, shipping_note=note, shipping_exact=exact,
            location=_text(li, ".locationText"), posted=_attr(li, "time", "datetime"),
            extra={"trgovac": li.css_first(".feature.residentialSeller") is None},
        ))
    return offers


async def search(query: str) -> list[Offer]:
    async with session() as s:
        r = await s.get(BASE + "/search/", params={"keywords": query, "sort": "new"})
        r.raise_for_status()
        return parse(text(r))


SOURCES = [Source(NAME, LABEL, "market", search)]
