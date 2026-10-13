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

SOURCE_TIMEOUT = 15                       # s - spori izvor ne smije blokirati ostale
CACHE_SECONDS = {"market": 45, "shop": 600}
DEAL_THRESHOLD = 0.30                     # 30 % ispod referentne cijene = "apsurdna" ponuda
EXACT_MIN = YEAR_MISSING                  # od ove ocjene ponuda se računa kao točan model
SIMILAR_MIN = VARIANT                     # od ove ocjene se prikazuje (kao varijanta)
DETAILS_MAX = 20                          # najviše oglasa po izvoru koje otvaramo radi opisa
DETAILS_PARALLEL = 8
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
    a trgovine ih često ne pišu). Oglasnicima šaljemo i šire upite, jer ljudi pišu nepotpune naslove:
      - bez brenda:   'Metalbone CTRL 3.4'
      - samo model:   'Metalbone'   (verziju onda potvrđuje opis oglasa - vidi deep_check)"""
    wanted = parse_query(query)
    year_words = {str(y) for y in wanted.years} | {str(y - 2000) for y in wanted.years}
    words = [w for w in query.split() if not _consists_of(w, year_words | STOPWORDS)]
    terms = [" ".join(words) or query]
    if kind == "market" and wanted.model_words:
        without_brand = " ".join(w for w in words if not _consists_of(w, BRANDS))
        family_only = next((w for w in words if not _consists_of(w, BRANDS)), "")
        terms += [t for t in (without_brand, family_only) if t and len(t) >= 3]
    return list(dict.fromkeys(terms))  # bez duplikata, redoslijed ostaje


# ---------- 1. dohvat (s cacheom) ----------
_search_cache: dict[tuple[str, str], tuple[float, list[Offer]]] = {}   # (izvor, upit) -> (vrijeme, ponude)


async def fetch(source: Source, term: str, use_cache: bool) -> list[Offer]:
    key = (source.name, term.lower())
    cached = _search_cache.get(key)
    if not (use_cache and cached and time.time() - cached[0] < CACHE_SECONDS[source.kind]):
        cached = (time.time(), await asyncio.wait_for(source.search(term), SOURCE_TIMEOUT))
        _search_cache[key] = cached
    return copy.deepcopy(cached[1])  # match/enrich mijenjaju ponude - cache mora ostati netaknut


# ---------- 2. ocjena ----------
def score_offer(wanted: WantedRacket, offer: Offer, details: str = "") -> None:
    result = match(wanted, offer.title, offer.category, details=details)
    offer.match, offer.match_note, offer.match_reason = result.score, result.note, result.reason


# ---------- 3. dubinska provjera (opis oglasa) ----------
@dataclass
class _CachedDetails:
    at: float
    text: str
    condition: str


_details_cache: dict[str, _CachedDetails] = {}   # url oglasa -> opis


async def _read_details(source: Source, offer: Offer) -> str:
    cached = _details_cache.get(offer.url)
    if cached and time.time() - cached.at < DETAILS_CACHE_SECONDS:
        offer.condition = cached.condition
        return cached.text
    text = await source.details(offer)
    _details_cache[offer.url] = _CachedDetails(time.time(), text, offer.condition)
    return text


async def deep_check(source: Source, wanted: WantedRacket, offers: list[Offer]) -> None:
    """Oglasi čiji naslov spominje model, ali ne i verziju/godinu (npr. samo 'Adidas Metalbone'):
    otvori oglas i pročitaj opis. Ako opis potvrdi točnu verziju, ponuda ulazi u rezultate."""
    to_open = [o for o in offers
               if worth_opening(wanted, o.title, MatchResult(o.match, o.match_note, o.match_reason))][:DETAILS_MAX]
    limit = asyncio.Semaphore(DETAILS_PARALLEL)

    async def check(offer: Offer) -> None:
        async with limit:
            details = await _read_details(source, offer)
        result = match(wanted, offer.title, offer.category, details=details)
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
        batches = await asyncio.gather(*(fetch(source, t, use_cache) for t in search_terms(query, source.kind)))
        offers = list({o.key: o for batch in batches for o in batch}.values())
        for offer in offers:
            score_offer(wanted, offer)
        if source.details:
            try:
                await asyncio.wait_for(deep_check(source, wanted, offers), SOURCE_TIMEOUT)
            except asyncio.TimeoutError:
                log.info("%s: dubinska provjera prekinuta nakon %ss (dio oglasa provjeren)", source.name, SOURCE_TIMEOUT)
        hits = [o for o in offers if o.match >= SIMILAR_MIN]
        if source.enrich and hits:
            await asyncio.wait_for(source.enrich(hits), SOURCE_TIMEOUT)
        status.ok, status.last_ok, status.error, status.fails, status.found = True, time.time(), "", 0, len(offers)
        return offers if keep_rejected else [o for o in hits if not o.excluded]
    except Exception as e:
        status.ok, status.error, status.fails = False, f"{type(e).__name__}: {str(e)[:150]}", status.fails + 1
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
