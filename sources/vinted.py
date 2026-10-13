"""Vinted (vinted.hr) - rabljeno i novo, uključuje oglase iz drugih EU zemalja koji šalju u HR.

Stranica pretrage sadrži podatke kao Next.js payload, pa ne treba prijava ni API ključ.
"""
import json
import re
from urllib.parse import quote

from core.http import next_payload, session, text
from core.models import Offer
from core.shipping import marketplace_shipping

from .base import Source, fetch_pages

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
        product = item.get("productItem") or {}
        if not product.get("id"):
            continue
        price = float(product["price"]["amount"])
        total = float((product.get("totalItemPrice") or {}).get("amount") or price)  # cijena + zaštita kupca
        state = conditions.get(str(product["id"]), "")
        offers.append(Offer(
            source=NAME, source_name=LABEL, id=str(product["id"]), title=product.get("title", ""),
            url="https://www.vinted.hr" + product.get("url", ""), price=price, fees=round(total - price, 2),
            condition="new" if state.startswith(_NEW_STATES) else "used",
            image=product.get("thumbnailUrl") or "",
            shipping=ship, shipping_note=note, shipping_exact=exact,
        ))
    return offers


_PLUGINS = '{"plugins":[{"data":{"item_id"'


def parse_details(html: str) -> str:
    """Opis i atributi (marka, stanje...) sa stranice oglasa."""
    payload = next_payload(html)
    i = payload.find(_PLUGINS)
    if i < 0:
        return ""
    plugins, _ = json.JSONDecoder().raw_decode(payload, i)
    parts = []
    for plugin in plugins["plugins"]:
        data = plugin.get("data") or {}
        if plugin.get("name") == "description":
            parts.append(data.get("description") or "")
        elif plugin.get("name") == "attributes":
            parts += [f"{a['data'].get('title')}: {a['data'].get('value')}" for a in data.get("attributes", [])
                      if isinstance(a.get("data"), dict)]
    return "\n".join(p for p in parts if p)


async def details(offer: Offer) -> str:
    async with session() as client:
        response = await client.get(offer.url)
        response.raise_for_status()
        return parse_details(text(response))


PAGE_SIZE = 96
# Vinted blokira (429) iznad ~20 zahtjeva u minuti (budžet je u core/http.py), pa jedna pretraga smije malo:
MAX_PAGES = 2    # najviše ~190 najnovijih oglasa po upitu
DETAILS_MAX = 4  # novih opisa po pretrazi; ostali dođu na red u sljedećoj (opisi se pamte 24 h)
TIMEOUT = 40     # s - kad je budžet potrošen (više pretraga zaredom), zahtjevi čekaju red umjesto da padnu


async def search(query: str) -> list[Offer]:
    async with session() as client:
        async def page(n: int) -> list[Offer]:
            response = await client.get(f"https://www.vinted.hr/catalog?search_text={quote(query)}&order=newest_first&page={n}")
            response.raise_for_status()
            return parse(text(response))

        return await fetch_pages(page, full_page=PAGE_SIZE, max_pages=MAX_PAGES)


SOURCES = [Source(NAME, LABEL, "market", search, details=details, details_max=DETAILS_MAX, timeout=TIMEOUT)]
