"""Katalog reketa: brend, model, točna verzija, godina i specifikacije.

Koristi se za dvije stvari:
  1. sučelje - filteri (brend, model, godina, oblik, balans, razina...) i odabir TOČNE verzije
  2. matcher - za svaki model zna sve oznake verzija (npr. Metalbone: carbon, ctrl, hrd, team, light,
     zz, reserve, superlight...), pa oglas s oznakom koju nisi odabrao nije tvoj reket

Novi izvor kataloga = nova async funkcija koja vraća list[Racket], dodana u PROVIDERS.
"""
import asyncio
import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .http import session
from .matcher import ACCESSORY, BRANDS, NEW_HINTS, PACK, STOPWORDS, tokens, years

CATALOG_FILE = Path(__file__).resolve().parent.parent / "catalog.json"
MAX_AGE = 3 * 24 * 3600
log = logging.getLogger("catalog")

# imena igrača i boje nisu oznaka verzije ("Metalbone 3.4 - Ale Galán" je isti reket kao "Metalbone 3.4")
PLAYERS = {
    "ale", "alejandro", "galan", "agustin", "tapia", "arturo", "coello", "juan", "lebron", "fede", "federico",
    "chingotto", "tello", "franco", "stupaczuk", "stupa", "martin", "nenno", "di", "paquito", "navarro",
    "sanyo", "gutierrez", "fernando", "belasteguin", "bela", "pablo", "lima", "delfi", "brea", "bea",
    "gonzalez", "ari", "sanchez", "paula", "josemaria", "triay", "gemma", "alayeto", "mapi", "majo",
    "salazar", "marta", "ortega", "claudia", "fernandez", "lucas", "campagnolo", "yanguas", "mike",
    "javi", "garrido", "momo", "maxi", "miguel", "lamperti", "jon", "sanz", "coki", "nieto", "edu",
    "alonso", "aranzazu", "osoro", "victoria", "iglesias", "by", "signature",
}
COLORS = {
    "black", "white", "blue", "red", "green", "grey", "gray", "yellow", "orange", "pink", "purple", "gold",
    "silver", "navy", "azul", "negro", "blanco", "rojo", "verde", "gris", "amarillo", "naranja", "rosa",
    "morado", "dorado", "plata", "atomic", "neon", "fluor", "colour", "color",
}
NOT_VERSION = PLAYERS | COLORS | STOPWORDS | ACCESSORY | PACK | BRANDS | NEW_HINTS | {"edicion", "collection"}


@dataclass
class Racket:
    id: str
    brand: str
    title: str
    family: str          # model, npr. "METALBONE", "AT10", "VERTEX"
    year: int | None
    shape: str = ""      # Round / Diamond / Teardrop / Hybrid
    balance: str = ""    # Low / Medium / High
    core: str = ""       # EVA, Soft EVA, Foam...
    face: str = ""       # Fiberglass, Carbon 12K...
    level: str = ""      # Beginners / Advanced / Professional
    play: str = ""       # Control / Power / Balance
    gender: str = ""     # Man / Woman / Kids
    image: str = ""
    price: float | None = None       # trenutna cijena u izvornoj trgovini
    list_price: float | None = None  # puna (preporučena) cijena
    url: str = ""


def family_of(brand: str, title: str) -> str:
    """Prva riječ naslova nakon brenda: 'ADIDAS METALBONE CTRL 3.4 2025' -> 'METALBONE'."""
    brand_words = {w.lower() for w in re.split(r"[\s-]+", brand)} | {brand.lower()}
    words = [w for w in re.split(r"\s+", title) if w and w.lower() not in brand_words | {"pala", "racket", "padel"}]
    return words[0].upper().strip("-") if words else ""


def family_key(family: str) -> str:
    return "".join(tokens(family))  # "AT10" -> "at10", "X-ONE" -> "xone"


def brand_key(brand: str) -> str:
    return "".join(tokens(brand))  # "Black Crown" -> "blackcrown", "Vibor-A" -> "vibora"


# ---------- izvori kataloga ----------
async def _padelnuestro() -> list[Racket]:
    """Padel Nuestro (int) - ~800 reketa sa specifikacijama, preko njihovog Doofinder API-ja."""
    url = "https://eu1-search.doofinder.com/5/search"
    params = {"hashid": "7e6b0c88e88ddd9134bc543a8a37572e", "query": "", "rpp": 100,
              "filter[categories][]": "Padel Rackets"}
    headers = {"origin": "https://www.padelnuestro.com"}
    items: list[dict] = []
    async with session() as s:
        for page in range(1, 30):
            r = await s.get(url, params={**params, "page": page}, headers=headers)
            r.raise_for_status()
            batch = r.json().get("results", [])
            if not batch:
                break
            items += batch

    def spec(p: dict, key: str) -> str:
        v = p.get(key)
        return "" if v in (None, "None") else str(v)

    rackets = []
    for p in items:
        if "Pack" in p.get("family", "") or spec(p, "forma") == "Beach Tennis":
            continue
        brand, title = spec(p, "brand"), spec(p, "title")
        collection = " ".join(p.get("categories") or [])
        year = max(years(tokens(title)) or years(re.findall(r"20\d\d", collection)) or {None},
                   key=lambda y: y or 0)
        rackets.append(Racket(
            id="pn:" + str(p.get("id")), brand=brand, title=title, family=family_of(brand, title), year=year,
            shape=spec(p, "forma"), balance=spec(p, "balance"), core=spec(p, "nucleo"), face=spec(p, "cara"),
            level=spec(p, "nivel de juego"), play=spec(p, "tipo de juego"), gender=spec(p, "jugador"),
            image=spec(p, "image_link"), price=p.get("sale_price"), list_price=p.get("price"), url=spec(p, "link"),
        ))
    return rackets


PROVIDERS = [_padelnuestro]


# ---------- stanje ----------
class _Catalog:
    def __init__(self):
        self.rackets: list[Racket] = []
        self.updated: float = 0.0
        self.vocab: dict[tuple[str, str], set[str]] = {}  # (brand, family_key) -> oznake verzija
        self.families: dict[str, set[str]] = {}            # family_key -> brendovi

    def set(self, rackets: list[Racket], updated: float) -> None:
        self.rackets, self.updated = rackets, updated
        self.vocab, self.families = {}, {}
        for r in rackets:
            brand, fam = brand_key(r.brand), family_key(r.family)
            words = {t for t in tokens(r.title) if len(t) > 1 and not t.isdigit() and t not in NOT_VERSION}
            words -= set(tokens(r.family)) | set(tokens(r.brand))
            self.vocab.setdefault((brand, fam), set()).update(words)
            self.families.setdefault(fam, set()).add(brand)


catalog = _Catalog()


def load() -> None:
    if CATALOG_FILE.exists():
        data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        catalog.set([Racket(**r) for r in data["rackets"]], data["updated"])


async def refresh() -> int:
    results = await asyncio.gather(*(p() for p in PROVIDERS), return_exceptions=True)
    rackets = []
    for provider, res in zip(PROVIDERS, results):
        if isinstance(res, Exception):
            log.warning("katalog %s nije dohvaćen: %s", provider.__name__, res)
        else:
            rackets += res
    if rackets:
        now = time.time()
        CATALOG_FILE.write_text(json.dumps({"updated": now, "rackets": [asdict(r) for r in rackets]},
                                           ensure_ascii=False), encoding="utf-8")
        catalog.set(rackets, now)
    return len(rackets)


async def refresh_if_stale() -> None:
    if not catalog.rackets:
        load()
    if time.time() - catalog.updated > MAX_AGE:
        try:
            log.info("osvježavam katalog: %d reketa", await refresh())
        except Exception:
            log.exception("osvježavanje kataloga nije uspjelo")


def version_words(pq: dict) -> set[str]:
    """Sve poznate oznake verzija za model iz upita (npr. 'adidas metalbone 3.4' -> {carbon, ctrl, hrd, ...})."""
    core = pq["core"]
    for n in range(min(3, len(core)), 0, -1):  # "at" + "10" -> "at10"
        key = "".join(core[:n])
        brands = catalog.families.get(key)
        if brands:
            if pq["brand"]:  # "black" iz upita odgovara brendu "blackcrown"
                brands = {b for b in brands if pq["brand"] in b} or brands
            return set().union(*(catalog.vocab.get((b, key), set()) for b in brands))
    return set()
