"""Katalog reketa: brend, model, točna verzija, godina, specifikacije i ocjene.

Koristi se za dvije stvari:
  1. sučelje - filteri (brend, model, godina, oblik, balans, razina...) i odabir TOČNE verzije
  2. matcher - za svaki model zna sve oznake verzija (npr. Metalbone: carbon, ctrl, hrd, team, light,
     zz, reserve, superlight...), pa oglas s oznakom koju nisi odabrao nije tvoj reket

Izvori (PROVIDERS) se spajaju: isti reket iz više izvora postaje jedan zapis (merge()).
Novi izvor kataloga = nova async funkcija koja vraća list[Racket], dodana u PROVIDERS.
"""
import asyncio
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .http import next_payload, session, text
from .matcher import ACCESSORY, BRANDS, NEW_HINTS, PACK, STOPWORDS, VARIANTS, WantedRacket, generation, tokens, years

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
SHAPES = {"Tear": "Teardrop", "Drop": "Teardrop", "Round": "Round", "Diamond": "Diamond", "Hybrid": "Hybrid"}


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
    ratings: dict = field(default_factory=dict)  # power, control, rebound, maneuverability, sweetSpot (0-10)
    sources: list = field(default_factory=list)  # iz kojih izvora kataloga je zapis


def family_of(brand: str, title: str) -> str:
    """Prva riječ naslova nakon brenda: 'ADIDAS METALBONE CTRL 3.4 2025' -> 'METALBONE'."""
    brand_words = {w.lower() for w in re.split(r"[\s-]+", brand)} | {brand.lower()}
    words = [w for w in re.split(r"\s+", title) if w and w.lower() not in brand_words | {"pala", "racket", "padel"}]
    return words[0].upper().strip("-") if words else ""


def family_key(family: str) -> str:
    return "".join(tokens(family))  # "AT10" -> "at10", "X-ONE" -> "xone"


def brand_key(brand: str) -> str:
    return "".join(tokens(brand))  # "Black Crown" -> "blackcrown", "Vibor-A" -> "vibora"


def identity(r: Racket) -> tuple:
    """Ključ za prepoznavanje istog reketa iz različitih izvora: brend + riječi naziva + godina.
    Igrači, boje i godina u nazivu se ne gledaju ('METALBONE SUPERLIGHT' iz kolekcije 2026
    = 'Metalbone Superlight 2026')."""
    toks = tokens(r.title)
    year_toks = {str(y) for y in years(toks)}
    ignore = PLAYERS | COLORS | STOPWORDS | year_toks | {"plus"}
    return brand_key(r.brand), tuple(sorted(set(toks) - ignore)), r.year


# ---------- izvori kataloga ----------
async def _padelnuestro() -> list[Racket]:
    """Padel Nuestro (int): ~800 aktualnih reketa s punim specifikacijama, preko njihovog Doofinder API-ja."""
    url = "https://eu1-search.doofinder.com/5/search"
    params = {"hashid": "7e6b0c88e88ddd9134bc543a8a37572e", "query": "", "rpp": 100,
              "filter[categories][]": "Padel Rackets"}
    headers = {"origin": "https://www.padelnuestro.com"}
    items: list[dict] = []
    async with session() as client:
        for page in range(1, 30):
            response = await client.get(url, params={**params, "page": page}, headers=headers)
            response.raise_for_status()
            batch = response.json().get("results", [])
            if not batch:
                break
            items += batch

    def spec(p: dict, key: str) -> str:
        v = product.get(key)
        return "" if v in (None, "None") else str(v)

    rackets = []
    for product in items:
        if "Pack" in product.get("family", "") or spec(product, "forma") == "Beach Tennis":
            continue
        brand, title = spec(product, "brand"), spec(product, "title")
        collection = " ".join(product.get("categories") or [])
        year = max(years(tokens(title)) or years(re.findall(r"20\d\d", collection)) or {None}, key=lambda y: y or 0)
        rackets.append(Racket(
            id="pn:" + str(product.get("id")), brand=brand, title=title, family=family_of(brand, title), year=year,
            shape=spec(product, "forma"), balance=spec(product, "balance"), core=spec(product, "nucleo"), face=spec(product, "cara"),
            level=spec(product, "nivel de juego"), play=spec(product, "tipo de juego"), gender=spec(product, "jugador"),
            image=spec(product, "image_link"), price=product.get("sale_price"), list_price=product.get("price"),
            url=spec(product, "link"), sources=["Padel Nuestro"],
        ))
    return rackets


async def _padelful() -> list[Racket]:
    """Padelful: baza ~1700 reketa 2021-2027 (i starijih koje trgovine više nemaju) s ocjenama."""
    base = "https://www.padelful.com"
    sem = asyncio.Semaphore(4)  # pristojno prema njihovom serveru

    async def page(client, n: int) -> tuple[list[dict], int]:
        """Vraća rekete sa stranice i ukupan broj reketa u bazi."""
        async with sem:
            response = await client.get(f"{base}/en/rackets", params={"page": n})
        payload = next_payload(text(response))
        out, pos, marker = [], 0, '{"_id":"en/rackets/'
        while (i := payload.find(marker, pos)) >= 0:
            try:
                obj, end = json.JSONDecoder().raw_decode(payload, i)
                out.append(obj)
                pos = end
            except ValueError:
                pos = i + len(marker)
        total = re.search(r'"total":(\d+),"page":\d+', payload)
        return out, int(total.group(1)) if total else 0

    async with session() as client:
        first, total = await page(client, 1)
        pages = -(-total // max(len(first), 1))  # zaokruži prema gore
        rest = await asyncio.gather(*(page(client, n) for n in range(2, pages + 1)))
    items = {o["slug"]: o for batch in [first, *(objs for objs, _ in rest)] for o in batch if o.get("slug")}

    rackets = []
    for o in items.values():
        brand, title = o.get("brand") or "", o.get("model") or ""
        image = o.get("image") or ""
        rackets.append(Racket(
            id="pf:" + o["slug"], brand=brand, title=title, family=family_of(brand, title),
            year=o.get("season") if isinstance(o.get("season"), int) else None,
            shape=SHAPES.get(o.get("shape") or "", o.get("shape") or ""),
            image=base + image if image.startswith("/") else image,
            price=o["bestPrice"] if isinstance(o.get("bestPrice"), (int, float)) else None,
            list_price=o.get("pvp") if isinstance(o.get("pvp"), (int, float)) else None,
            url=base + (o.get("url") or ""), ratings=o.get("ratings") or {}, sources=["Padelful"],
        ))
    return rackets


PROVIDERS = [_padelnuestro, _padelful]  # redoslijed = prioritet podataka kod spajanja


def merge(groups: list[list[Racket]]) -> list[Racket]:
    """Isti reket iz više izvora -> jedan zapis. Prvi izvor ima prednost, ostali popunjavaju prazna polja."""
    by_id: dict[tuple, Racket] = {}
    for rackets in groups:
        for r in rackets:
            key = identity(r)
            if key not in by_id:
                by_id[key] = r
                continue
            main = by_id[key]
            for f in fields(Racket):
                if f.name in ("id", "title", "sources"):
                    continue
                if not getattr(main, f.name) and getattr(r, f.name):
                    setattr(main, f.name, getattr(r, f.name))
            main.sources = main.sources + [s for s in r.sources if s not in main.sources]
    return list(by_id.values())


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
    groups = []
    for provider, res in zip(PROVIDERS, results):
        if isinstance(res, Exception):
            log.warning("katalog %s nije dohvaćen: %s", provider.__name__, res)
        else:
            groups.append(res)
    rackets = merge(groups)
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


def version_words(wanted: WantedRacket) -> set[str]:
    """Sve poznate oznake verzija za model iz upita (npr. 'adidas metalbone 3.4' -> {carbon, ctrl, hrd, ...}),
    bez riječi koje u katalogu ima SVAKI reket koji odgovara upitu: 'Nox AT10 Genius 18K 2025' se službeno
    zove '... 18K Alum 2025', pa 'alum' tu nije druga verzija."""
    words = wanted.model_words
    for n in range(min(3, len(words)), 0, -1):  # "at" + "10" -> "at10"
        family = "".join(words[:n])
        brands = catalog.families.get(family)
        if brands:
            if wanted.brand:  # "black" iz upita odgovara brendu "blackcrown"
                brands = {b for b in brands if wanted.brand in b} or brands
            found = set().union(*(catalog.vocab.get((b, family), set()) for b in brands))
            return found - _common_words(wanted)
    return set()


def _same_model(wanted: WantedRacket) -> list[tuple[Racket, list[str]]]:
    """Reketi iz kataloga čiji naziv sadrži sve riječi modela iz upita (i brend, ako je zadan)."""
    found = []
    for racket in catalog.rackets:
        words = tokens(racket.title)
        if wanted.brand and wanted.brand not in brand_key(racket.brand) and wanted.brand not in words:
            continue
        if all(w in words for w in wanted.model_words):
            found.append((racket, words))
    return found


def _common_words(wanted: WantedRacket) -> set[str]:
    """Riječi koje imaju svi reketi iz kataloga koji odgovaraju upitu i njegovoj godini. Opće oznake verzija
    (comfort, light...) se nikad ne izuzimaju - katalog možda samo nema osnovni model."""
    if not wanted.model_words or not wanted.years:
        return set()
    same = [set(words) for racket, words in _same_model(wanted) if racket.year in wanted.years]
    return set.intersection(*same) - VARIANTS if same else set()


def generations(wanted: WantedRacket) -> dict[tuple[str, ...], set[int]]:
    """Broj generacije -> godine, npr. za 'babolat technical viper': {('2','5'): {2025}, ('3','0'): {2026}}."""
    found: dict[tuple[str, ...], set[int]] = {}
    for racket, words in _same_model(wanted):
        number = generation(wanted, words)
        if number and racket.year:
            found.setdefault(number, set()).add(racket.year)
    return found
