"""Vinted (vinted.hr) - rabljeno i novo, uključuje oglase iz drugih EU zemalja koji šalju u HR.

Stranica pretrage sadrži podatke kao Next.js payload, pa ne treba prijava ni API ključ.
"""
import json
import re
from urllib.parse import quote

from core.http import next_payload, session, text
from core.models import Offer
from core.shipping import marketplace_shipping

from .base import Source

NAME, LABEL = "vinted", "Vinted"
_ITEMS_KEY = '"items":{"items":'
_CONDITION = re.compile(r'product-item-id-(\d+)--overlay-link" title="[^"]*?Stanje: ([^,"]+)')
_NEW_STATES = ("novo s etiketom", "novo bez etikete", "novo bez etiketa")


def parse(html: str) -> list[Offer]:
    payload = next_payload(html)
    i = payload.find(_ITEMS_KEY)
    if i < 0:
        return []
    items, _ = json.JSONDecoder().raw_decode(payload, i + len(_ITEMS_KEY))
    conditions = {m.group(1): m.group(2).strip().lower() for m in _CONDITION.finditer(html)}
    ship, note, exact = marketplace_shipping(NAME)

    offers = []
    for item in items:
        p = item.get("productItem") or {}
        if not p.get("id"):
            continue
        price = float(p["price"]["amount"])
        total = float((p.get("totalItemPrice") or {}).get("amount") or price)  # cijena + zaštita kupca
        state = conditions.get(str(p["id"]), "")
        offers.append(Offer(
            source=NAME, source_name=LABEL, id=str(p["id"]), title=p.get("title", ""),
            url="https://www.vinted.hr" + p.get("url", ""), price=price, fees=round(total - price, 2),
            condition="new" if state.startswith(_NEW_STATES) else "used",
            image=p.get("thumbnailUrl") or "",
            shipping=ship, shipping_note=note, shipping_exact=exact,
            extra={"stanje": state},
        ))
    return offers


async def search(query: str) -> list[Offer]:
    async with session() as s:
        r = await s.get(f"https://www.vinted.hr/catalog?search_text={quote(query)}&order=newest_first")
        r.raise_for_status()
        return parse(text(r))


SOURCES = [Source(NAME, LABEL, "market", search)]
