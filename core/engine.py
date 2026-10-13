"""Pretraga - srce aplikacije.

Za svaki izvor paralelno (run_source):
  1. fetch          izvor vrati SVE ponude za upit (sources/*.py -> search)
  2. match          matcher ocijeni svaku ponudu (točan model / varijanta / nije to)
  3. deep_check     oglasima kojima naslov nije dovoljan pročita se opis (source.details)
  4. enrich         pogođenima se dohvati stvarna dostava (source.enrich, npr. Shopify košarica)
Zatim za sve izvore zajedno: referentna cijena -> označavanje apsurdnih ponuda -> poredak.

Kad nešto ne radi: /api/health (koji izvor pada i zašto), /api/debug/explain?q=...&source=... (svaka
ponuda jednog izvora s ocjenom i razlogom), a greške se ispisuju u konzolu (logger "engine").
"""
import asyncio
import copy
import logging
import statistics
import time
from dataclasses import asdict, dataclass
from typing import AsyncIterator

from sources import SOURCES, BY_NAME
from sources.base import Source

from . import catalog
from .matcher import (BRANDS, NOTE_FROM_DETAILS, STOPWORDS, VARIANT, YEAR_MISSING, MatchResult, WantedRacket, match,
                      parse_query, tokens, worth_opening)
from .models import Offer

CACHE_SECONDS = {"market": 45, "shop": 600}
STALE_SECONDS = {"market": 1800, "shop": 6 * 3600}   # kad izvor padne, toliko stari rezultati još vrijede
DEAL_THRESHOLD = 0.30                     # 30 % ispod referentne cijene = "apsurdna" ponuda
EXACT_MIN = YEAR_MISSING                  # od ove ocjene ponuda se računa kao točan model
SIMILAR_MIN = VARIANT                     # od ove ocjene se prikazuje (kao varijanta)
DETAILS_PARALLEL = 8                      # istovremeno otvorenih oglasa (koliko novih po pretrazi: Source.details_max)
DETAILS_CACHE_SECONDS = 24 * 3600         # opis oglasa se rijetko mijenja

log = logging.getLogger("engine")


# ---------- stanje izvora (prikazuje se u Postavke -> Izvori i na /api/health) ----------
@dataclass
class SourceHealth:
    label: str
    kind: str
    ok: bool | None = None       # None = još nije korišten
    last_ok: float | None = None
    error: str = ""              # zadnja greška, npr. "HTTPError: HTTP Error 403"
    fails: int = 0               # uzastopne greške (watcher javlja na Telegram nakon 3)
    found: int = 0               # koliko je ponuda izvor vratio (prije filtriranja)
    ms: int = 0                  # trajanje zadnje pretrage


health: dict[str, SourceHealth] = {s.name: SourceHealth(s.label, s.kind) for s in SOURCES}


def health_report() -> dict[str, dict]:
    return {name: asdict(h) for name, h in health.items()}


# ---------- upiti prema izvorima ----------
def _consists_of(word: str, vocabulary: set[str]) -> bool:
    word_tokens = set(tokens(word))
    return bool(word_tokens) and word_tokens <= vocabulary


def search_terms(query: str, kind: str) -> list[str]:
    """Što točno šaljemo tražilici izvora. Bez godine i riječi poput 'padel reket' (to provjerava matcher,
    a trgovine ih često ne pišu). Oglasnicima šaljemo i širi upit, jer ljudi pišu nepotpune naslove:
      - samo model:   'Metalbone'   (verziju onda potvrđuje opis oglasa - vidi deep_check)
    Upit bez brenda ('Metalbone CTRL 3.4') se ne šalje posebno: pokriva ga 'samo model', a svaki dodatni
    upit troši ograničen broj zahtjeva prema oglasniku (Vinted)."""
    wanted = parse_query(query)
    year_words = {str(y) for y in wanted.years} | {str(y - 2000) for y in wanted.years}
    words = [w for w in query.split() if not _consists_of(w, year_words | STOPWORDS)]
    terms = [" ".join(words) or query]
    if kind == "market" and wanted.model_words:
        family_only = next((w for w in words if not _consists_of(w, BRANDS)), "")
        if len(family_only) >= 3:
            terms.append(family_only)
    return list(dict.fromkeys(terms))  # bez duplikata, redoslijed ostaje


# ---------- 1. dohvat (s cacheom) ----------
_search_cache: dict[tuple[str, str], tuple[float, list[Offer]]] = {}   # (izvor, upit) -> (vrijeme, ponude)


async def fetch(source: Source, term: str, use_cache: bool) -> tuple[list[Offer], str]:
    """Vraća (ponude, napomena). Napomena nije prazna kad izvor nije odgovorio pa su ponude iz spremljenih."""
    key = (source.name, term.lower())
    cached = _search_cache.get(key)
    note = ""
    if not (use_cache and cached and time.time() - cached[0] < CACHE_SECONDS[source.kind]):
        try:
            cached = (time.time(), await asyncio.wait_for(source.search(term), source.timeout))
            _search_cache[key] = cached
        except Exception as e:
            if not cached or time.time() - cached[0] > STALE_SECONDS[source.kind]:
                raise
            note = f"izvor ne odgovara ({_describe(e, source)}), rezultati stari {int((time.time() - cached[0]) / 60)} min"
    return copy.deepcopy(cached[1]), note  # match/enrich mijenjaju ponude - cache mora ostati netaknut


def _describe(error: Exception, source: Source) -> str:
    if isinstance(error, asyncio.TimeoutError):
        return f"nema odgovora u {source.timeout} s"
    return f"{type(error).__name__}: {str(error)[:150]}"


# ---------- 2. ocjena ----------
def score_offer(wanted: WantedRacket, offer: Offer, marketplace: bool) -> None:
    result = match(wanted, offer.title, offer.category, price=offer.price, marketplace=marketplace)
    offer.match, offer.match_note, offer.match_reason = result.score, result.note, result.reason


# ---------- 3. dubinska provjera (opis oglasa) ----------
@dataclass
class _CachedDetails:
    at: float
    text: str
    condition: str


_details_cache: dict[str, _CachedDetails] = {}   # url oglasa -> opis


def _details_cached(offer: Offer) -> _CachedDetails | None:
    cached = _details_cache.get(offer.url)
    return cached if cached and time.time() - cached.at < DETAILS_CACHE_SECONDS else None


async def _read_details(source: Source, offer: Offer) -> str:
    if cached := _details_cached(offer):
        offer.condition = cached.condition
        return cached.text
    text = await source.details(offer)
    _details_cache[offer.url] = _CachedDetails(time.time(), text, offer.condition)
    return text


async def deep_check(source: Source, wanted: WantedRacket, offers: list[Offer]) -> None:
    """Oglasi čiji naslov spominje model, ali ne i verziju/godinu (npr. samo 'Adidas Metalbone'):
    otvori oglas i pročitaj opis. Ako opis potvrdi točnu verziju, ponuda ulazi u rezultate.
    Već pročitani opisi su besplatni; novih se otvara najviše source.details_max, najjeftiniji oglasi prvi."""
    candidates = [o for o in offers
                  if worth_opening(wanted, o.title, MatchResult(o.match, o.match_note, o.match_reason))]
    known = [o for o in candidates if _details_cached(o)]
    new = sorted((o for o in candidates if not _details_cached(o)), key=lambda o: o.price)[:source.details_max]
    to_open = known + new
    limit = asyncio.Semaphore(DETAILS_PARALLEL)

    async def check(offer: Offer) -> None:
        async with limit:
            details = await _read_details(source, offer)
        result = match(wanted, offer.title, offer.category, details=details, price=offer.price,
                       marketplace=source.kind == "market")
        if result.score > offer.match:
            offer.match, offer.match_reason = result.score, ""
            offer.match_note = "; ".join(filter(None, [NOTE_FROM_DETAILS, result.note]))

    results = await asyncio.gather(*(check(o) for o in to_open), return_exceptions=True)
    failed = [r for r in results if isinstance(r, Exception)]
    if failed:  # opis je bonus - greška ne ruši izvor, ali mora biti vidljiva
        log.warning("%s: %d/%d opisa nije pročitano (%s)", source.name, len(failed), len(to_open), failed[0])


# ---------- jedan izvor od početka do kraja ----------
async def run_source(source: Source, query: str, wanted: WantedRacket, use_cache: bool = True,
                     keep_rejected: bool = False) -> list[Offer]:
    """Koraci 1-4 za jedan izvor. keep_rejected=True vraća i odbijene ponude (za /api/debug/explain)."""
    started = time.time()
    status = health[source.name]
    try:
        fetched = await asyncio.gather(*(fetch(source, t, use_cache) for t in search_terms(query, source.kind)),
                                       return_exceptions=True)
        batches = [f for f in fetched if not isinstance(f, Exception)]
        if not batches:  # nijedan upit nije uspio (ni iz spremljenih)
            raise fetched[0]
        failed = [_describe(f, source) for f in fetched if isinstance(f, Exception)]
        stale = next((note for _offers, note in batches if note), "")
        problem = stale or (f"dio upita nije uspio ({failed[0]})" if failed else "")
        offers = list({o.key: o for batch, _note in batches for o in batch}.values())
        for offer in offers:
            score_offer(wanted, offer, marketplace=source.kind == "market")
        if source.details:
            try:
                await asyncio.wait_for(deep_check(source, wanted, offers), source.timeout)
            except asyncio.TimeoutError:
                log.info("%s: dubinska provjera prekinuta nakon %ss (dio oglasa provjeren)", source.name, source.timeout)
        hits = [o for o in offers if o.match >= SIMILAR_MIN]
        if source.enrich and hits:
            await asyncio.wait_for(source.enrich(hits), source.timeout)
        # djelomičan uspjeh: izvor "radi" (ima rezultate), ali napomena ostaje vidljiva u Postavkama i na /api/health
        status.ok, status.error, status.found = True, problem, len(offers)
        if not problem:
            status.last_ok, status.fails = time.time(), 0
        return offers if keep_rejected else [o for o in hits if not o.excluded]
    except Exception as e:
        status.ok, status.error, status.fails = False, _describe(e, source), status.fails + 1
        log.warning("%s: izvor nije uspio (%s)", source.name, status.error)
        raise
    finally:
        status.ms = int((time.time() - started) * 1000)


# ---------- poredak i apsurdne cijene ----------
def reference_price(offers: list[Offer]) -> float | None:
    """'Uobičajena cijena' = medijan ukupne cijene točnog modela; iz novih ponuda ako ih ima barem 2."""
    exact = [o for o in offers if o.match >= EXACT_MIN]
    new = [o.total for o in exact if o.condition == "new"]
    pool = new if len(new) >= 2 else [o.total for o in exact]
    return round(statistics.median(pool), 2) if len(pool) >= 2 else None


def mark_deals(offers: list[Offer], reference: float | None, threshold: float = DEAL_THRESHOLD) -> None:
    for offer in offers:
        if reference and offer.match >= EXACT_MIN:
            offer.deal_pct = round(1 - offer.total / reference, 3)
            offer.is_deal = offer.deal_pct >= threshold


def rank(offers: list[Offer]) -> list[Offer]:
    """Prvo točan model, zatim po ukupnoj cijeni (s dostavom)."""
    return sorted(offers, key=lambda o: (o.match < EXACT_MIN, o.total))


# ---------- javno sučelje ----------
def wanted_racket(query: str) -> WantedRacket:
    """Upit + oznake verzija tog modela iz kataloga."""
    wanted = parse_query(query)
    wanted.version_words = catalog.version_words(wanted)
    wanted.generations = catalog.generations(wanted)
    return wanted


async def _run_safely(source: Source, query: str, wanted: WantedRacket, use_cache: bool):
    try:
        return source, await run_source(source, query, wanted, use_cache), None
    except Exception as e:  # jedan izvor ne smije srušiti pretragu (greška je već zapisana u health i log)
        return source, [], e


async def stream(query: str, use_cache: bool = True, only: set[str] | None = None) -> AsyncIterator[tuple]:
    """Vraća (izvor, ponude, greška) čim pojedini izvor završi - UI prikazuje rezultate odmah."""
    wanted = wanted_racket(query)
    sources = [s for s in SOURCES if not only or s.name in only]
    for finished in asyncio.as_completed([_run_safely(s, query, wanted, use_cache) for s in sources]):
        yield await finished


async def search_all(query: str, use_cache: bool = True, only: set[str] | None = None
                     ) -> tuple[list[Offer], float | None]:
    offers = [o async for _source, found, _error in stream(query, use_cache, only) for o in found]
    reference = reference_price(offers)
    mark_deals(offers, reference)
    return rank(offers), reference


async def explain(query: str, source_name: str) -> dict:
    """Za traženje grešaka: SVE ponude jednog izvora s ocjenom i razlogom (i one odbijene)."""
    source = BY_NAME[source_name]
    wanted = wanted_racket(query)
    offers = await run_source(source, query, wanted, use_cache=False, keep_rejected=True)
    offers.sort(key=lambda o: -o.match)
    return {
        "query": asdict(wanted) | {"years": sorted(wanted.years), "version_words": sorted(wanted.version_words)},
        "search_terms": search_terms(query, source.kind),
        "offers": [{"title": o.title, "match": o.match, "note": o.match_note, "reason": o.match_reason,
                    "excluded": o.excluded, "total": o.total, "url": o.url} for o in offers],
    }
