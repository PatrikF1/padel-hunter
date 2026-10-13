"""Index oglasi - JSON API koji koristi i njihova web stranica (treba samo kolačić s naslovnice)."""
from core.http import session
from core.matcher import looks_new
from core.models import Offer
from core.shipping import marketplace_shipping

from .base import Source, fetch_pages

PAGE_SIZE = 50  # najviše što API vraća

NAME, LABEL = "index", "Index oglasi"
BASE = "https://www.index.hr/oglasi"
_url_slugs: dict[tuple[str, str], tuple[str, str]] = {}  # (module, category) -> ("sport", "tenis")


async def _load_url_slugs(client) -> None:
    """URL oglasa koristi hrvatske nazive modula/kategorije - mapiranje čitamo iz njihove konfiguracije."""
    if _url_slugs:
        return
    modules = (await client.get(BASE + "/api/configuration/module")).json()
    categories = (await client.get(BASE + "/api/configuration/category")).json()
    module_hr = {m["name"]: m["nameHr"] for m in modules}
    for c in categories:
        _url_slugs[(c["module"], c["name"])] = (module_hr.get(c["module"], c.get("moduleHr", "")), c["nameHr"])


def parse(data: dict) -> list[Offer]:
    ship, note, exact = marketplace_shipping(NAME)
    offers = []
    for ad in data.get("data", []):
        if not ad.get("price"):
            continue
        module, category = _url_slugs.get((ad.get("module"), ad.get("category")), ("sport", "tenis"))
        images = ad.get("images") or []
        title = ad.get("title", "")
        offers.append(Offer(
            source=NAME, source_name=LABEL, id=str(ad.get("code") or ad.get("id")), title=title,
            url=f"{BASE}/{module}/{category}/oglas/{ad.get('smartLink')}/{ad.get('code')}",
            price=float(ad["price"]), condition="new" if looks_new(title) else "used",
            image=f"{BASE}/api/image/direct/{images[0]}?m=card_large" if images else "",
            shipping=ship, shipping_note=note, shipping_exact=exact,
            location=ad.get("cityName") or "", posted=ad.get("postedTime") or "",
        ))
    return offers


async def details(offer: Offer) -> str:
    async with session() as client:
        await client.get(BASE)  # kolačić potreban za API
        response = await client.get(BASE + "/api/aditem/single-ad", params={"code": offer.id},
                        headers={"accept": "application/json"})
        response.raise_for_status()
        ads = response.json().get("data") or [{}]
    return ads[0].get("description") or ""


async def search(query: str) -> list[Offer]:
    async with session() as client:
        await client.get(BASE)
        await _load_url_slugs(client)

        async def page(n: int) -> list[Offer]:
            response = await client.get(BASE + "/api/aditem", params={"text": query, "sortOption": 4, "itemPerPage": PAGE_SIZE,
                                                          "page": n},
                            headers={"accept": "application/json", "referer": BASE + "/pretraga"})
            response.raise_for_status()
            return parse(response.json())

        return await fetch_pages(page, full_page=PAGE_SIZE)


SOURCES = [Source(NAME, LABEL, "market", search, details=details)]
