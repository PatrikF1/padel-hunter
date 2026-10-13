"""eBay.de - novo i rabljeno, samo oglasi koji šalju u HR iz EU (izvan EU = carina).

Dva načina, automatski:
  1. Službeni Browse API (pouzdano) - ako su u Postavkama upisani eBay Client ID i Secret
     (besplatno na developer.ebay.com). Dostava se računa za Zagreb 10000.
  2. Scraping stranice pretrage (rezerva) - eBay ga povremeno blokira.
"""
import base64
import re
import time
from urllib.parse import quote_plus

from selectolax.lexbor import LexborHTMLParser

from core import db
from core.http import eur, session, text
from core.models import Offer

from .base import Source

NAME, LABEL = "ebay", "eBay"
EU_ISO = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV",
          "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}


# ===================== 1) službeni Browse API =====================
API = "https://api.ebay.com"
API_HEADERS = {"X-EBAY-C-MARKETPLACE-ID": "EBAY_DE",
               "X-EBAY-C-ENDUSERCTX": "contextualLocation=country%3DHR%2Czip%3D10000"}
_token = {"value": "", "expires": 0.0}


def _api_keys() -> tuple[str, str]:
    return db.get_setting("ebay_client_id"), db.get_setting("ebay_client_secret")


async def _api_token(client, client_id: str, secret: str) -> str:
    if _token["value"] and time.time() < _token["expires"] - 60:
        return _token["value"]
    basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    response = await client.post(API + "/identity/v1/oauth2/token",
                     headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
                     data="grant_type=client_credentials&scope=https%3A%2F%2Fapi.ebay.com%2Foauth%2Fapi_scope")
    response.raise_for_status()
    j = response.json()
    _token.update(value=j["access_token"], expires=time.time() + j.get("expires_in", 7200))
    return _token["value"]


def _api_offer(item: dict) -> Offer | None:
    country = (item.get("itemLocation") or {}).get("country", "")
    options = item.get("shippingOptions") or []
    costs = [float((o.get("shippingCost") or {}).get("value", 0)) for o in options if o.get("shippingCost")]
    if (country and country not in EU_ISO) or not costs or (item.get("price") or {}).get("currency") != "EUR":
        return None
    return Offer(
        source=NAME, source_name=LABEL, id=item["itemId"], title=item.get("title", ""),
        url=item.get("itemWebUrl", ""), price=float(item["price"]["value"]),
        condition="new" if str(item.get("conditionId", "")).startswith("1") else "used",
        image=(item.get("image") or {}).get("imageUrl", ""),
        shipping=min(costs), shipping_note=f"eBay API: dostava u HR, šalje iz: {country}", shipping_exact=True,
        location=country, is_auction="AUCTION" in (item.get("buyingOptions") or []),
    )


async def _search_api(query: str, client_id: str, secret: str) -> list[Offer]:
    async with session() as client:
        token = await _api_token(client, client_id, secret)
        response = await client.get(API + "/buy/browse/v1/item_summary/search",
                        params={"q": query, "limit": 100, "filter": "deliveryCountry:HR"},
                        headers={**API_HEADERS, "Authorization": f"Bearer {token}"})
        response.raise_for_status()
        return [o for o in map(_api_offer, response.json().get("itemSummaries", [])) if o]


# ===================== 2) scraping (rezerva) =====================
SEARCH_URL = "https://www.ebay.de/sch/i.html?_nkw={q}&_sop=15&_fcid=53&_ipg=120"  # _fcid=53: dostava u HR
FINGERPRINTS = ["firefox144", "chrome136", "firefox135", "firefox133", "chrome142"]
EU_COUNTRIES_DE = {
    "deutschland", "österreich", "belgien", "bulgarien", "kroatien", "zypern", "tschechien",
    "tschechische republik", "dänemark", "estland", "finnland", "frankreich", "griechenland",
    "ungarn", "irland", "italien", "lettland", "litauen", "luxemburg", "malta", "niederlande",
    "polen", "portugal", "rumänien", "slowakei", "slowenien", "spanien", "schweden",
}
USED_WORDS = ("gebraucht", "generalüberholt", "ersatzteile", "defekt")
_next_fp = 0


def _parse_card(card) -> Offer | None:
    listing_id = card.attributes.get("data-listingid")
    title_el = card.css_first(".su-styled-text.primary.default")
    price = eur(card.css_first(".s-card__price").text()) if card.css_first(".s-card__price") else None
    if not listing_id or not title_el or not price:
        return None

    texts = [t for t in (n.text(deep=False, strip=True) for n in card.css(".su-styled-text.secondary")) if t]
    shipping, origin, auction = None, "", False
    for t in texts:
        tl = t.lower()
        if "versand" in tl or "lieferung" in tl:
            shipping = 0.0 if "kostenlos" in tl else (eur(t) if "eur" in tl else shipping)
        if m := re.match(r"aus (.+)", t):
            origin = m.group(1).strip()
        if re.search(r"\bgebote?\b", tl):
            auction = True
    if (origin and origin.lower() not in EU_COUNTRIES_DE) or shipping is None:
        return None  # izvan EU (carina) ili ne šalje u HR

    condition_text = (texts[0] if texts else "").lower()
    img = card.css_first("img.s-card__image")
    return Offer(
        source=NAME, source_name=LABEL, id=listing_id, title=title_el.text(strip=True),
        url=f"https://www.ebay.de/itm/{listing_id}", price=price,
        condition="used" if any(w in condition_text for w in USED_WORDS) else "new",
        image=(img.attributes.get("src") or "") if img else "",
        shipping=shipping, shipping_note="eBay: dostava u HR" + (f", šalje iz: {origin}" if origin else ""),
        shipping_exact=True, location=origin, is_auction=auction,
    )


def parse(html: str) -> list[Offer]:
    return [o for o in map(_parse_card, LexborHTMLParser(html).css("li.s-card")) if o]


async def _search_scrape(query: str) -> list[Offer]:
    global _next_fp
    url = SEARCH_URL.format(q=quote_plus(query))
    last_error = ""
    for _ in FINGERPRINTS:
        fp = FINGERPRINTS[_next_fp % len(FINGERPRINTS)]
        async with session(fp) as client:
            response = await client.get(url)
        html = text(response)
        if response.status_code == 200 and "s-card" in html:
            return parse(html)
        last_error = f"HTTP {response.status_code}"
        _next_fp += 1
    raise RuntimeError(f"eBay blokira scraping ({last_error}) - upiši eBay API ključ u Postavkama")


# ===================== ulaz =====================
async def search(query: str) -> list[Offer]:
    client_id, secret = _api_keys()
    if client_id and secret:
        return await _search_api(query, client_id, secret)
    return await _search_scrape(query)


SOURCES = [Source(NAME, LABEL, "market", search)]
