"""Njuškalo - najveći HR oglasnik (HTML pretraga, sortirano od najnovijeg)."""
from selectolax.lexbor import LexborHTMLParser

from core.http import eur, session, text
from core.matcher import looks_new
from core.models import Offer
from core.shipping import marketplace_shipping

from .base import Source, fetch_pages

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
        ))
    return offers


def parse_details(html: str) -> tuple[str, str]:
    """(opis + osnovne informacije, stanje) sa stranice oglasa."""
    doc = LexborHTMLParser(html)
    description = _text(doc, ".ClassifiedDetailDescription-text")
    terms = [t.text(strip=True) for t in doc.css(".ClassifiedDetailBasicDetails-listTerm")]
    values = [v.text(strip=True) for v in doc.css(".ClassifiedDetailBasicDetails-listDefinition")]
    basics = dict(zip(terms, values))
    return "\n".join([description] + [f"{k}: {v}" for k, v in basics.items()]), basics.get("Stanje", "").lower()


async def details(offer: Offer) -> str:
    async with session() as client:
        response = await client.get(offer.url)
        response.raise_for_status()
    description, condition = parse_details(text(response))
    if condition:
        offer.condition = "new" if condition.startswith("nov") else "used"
    return description


PAGE_SIZE = 20  # Njuškalo prikazuje ~25 oglasa po stranici (+ izdvojene)


async def search(query: str) -> list[Offer]:
    async with session() as client:
        async def page(n: int) -> list[Offer]:
            response = await client.get(BASE + "/search/", params={"keywords": query, "sort": "new", "page": n})
            response.raise_for_status()
            return parse(text(response))

        return await fetch_pages(page, full_page=PAGE_SIZE)


SOURCES = [Source(NAME, LABEL, "market", search, details=details)]
