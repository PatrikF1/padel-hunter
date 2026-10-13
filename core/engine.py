"""Pretraga: svi izvori paralelno -> prepoznavanje modela -> stvarna dostava -> ukupna cijena -> apsurdne ponude."""
import asyncio
import copy
import statistics
import time
from typing import AsyncIterator

from sources import SOURCES
from sources.base import Source

from . import catalog
from .matcher import (BRANDS, NOTE_FROM_DETAILS, STOPWORDS, VARIANT, YEAR_MISSING, match, parse_query, tokens,
                      worth_details)
from .models import Offer

SOURCE_TIMEOUT = 15                      # s - spori izvor ne smije blokirati ostale
CACHE_TTL = {"market": 45, "shop": 600}  # s
DEAL_THRESHOLD = 0.30                    # 30 % ispod referentne cijene = apsurdno
EXACT_MIN = YEAR_MISSING                 # od ove ocjene ponuda se računa kao točan model
SIMILAR_MIN = VARIANT                    # od ove ocjene se prikazuje kao varijanta
DETAILS_MAX = 20                         # najviše oglasa po izvoru koje otvaramo radi opisa
DETAILS_PARALLEL = 8
DETAILS_TTL = 24 * 3600                  # opis oglasa se rijetko mijenja

_cache: dict[tuple[str, str], tuple[float, list[Offer]]] = {}
_details_cache: dict[str, tuple[float, str, str]] = {}  # url -> (vrijeme, tekst, stanje)
health: dict[str, dict] = {
    s.name: {"label": s.label, "kind": s.kind, "ok": None, "last_ok": None, "error": "", "fails": 0, "n": 0, "ms": 0}
    for s in SOURCES
}


# ---------- upiti ----------
def _is_only(word: str, vocab: set[str]) -> bool:
    toks = set(tokens(word))
    return bool(toks) and toks <= vocab


def search_terms(q: str, kind: str) -> list[str]:
    """Upit bez godine i riječi poput 'padel reket' (to provjerava matcher, a trgovine ih često ne pišu).

    Oglasnicima šaljemo još dvije šire verzije, jer ljudi pišu nepotpune naslove:
      - bez brenda:        'Metalbone CTRL 3.4'
      - samo model:        'Metalbone'  (verziju onda potvrđuje opis oglasa - vidi run_source)"""
    pq = parse_query(q)
    year_tokens = {str(y) for y in pq["years"]} | {str(y - 2000) for y in pq["years"]}
    words = [w for w in q.split() if not _is_only(w, year_tokens | STOPWORDS)]
    terms = [" ".join(words) or q]
    if kind == "market" and pq["core"]:
        without_brand = " ".join(w for w in words if not _is_only(w, BRANDS))
        family = next((w for w in words if not _is_only(w, BRANDS)), "")
        terms += [t for t in (without_brand, family) if t and len(t) >= 3]
    return list(dict.fromkeys(terms))  # bez duplikata, redoslijed ostaje


# ---------- dohvat ----------
async def _fetch(src: Source, term: str, use_cache: bool) -> list[Offer]:
    key = (src.name, term.lower())
    hit = _cache.get(key)
    if not (use_cache and hit and time.time() - hit[0] < CACHE_TTL[src.kind]):
        hit = (time.time(), await asyncio.wait_for(src.search(term), SOURCE_TIMEOUT))
        _cache[key] = hit
    return copy.deepcopy(hit[1])  # enrich/match mijenjaju ponude - cache mora ostati čist


async def _details(src: Source, o: Offer) -> str:
    hit = _details_cache.get(o.url)
    if hit and time.time() - hit[0] < DETAILS_TTL:
        o.condition = hit[2]
        return hit[1]
    text = await src.details(o)
    _details_cache[o.url] = (time.time(), text, o.condition)
    return text


async def deep_check(src: Source, pq: dict, offers: list[Offer]) -> None:
    """Oglasi čiji naslov spominje model, ali ne i verziju/godinu (npr. samo 'Adidas Metalbone'):
    otvori oglas i provjeri opis. Ako opis potvrdi točnu verziju, ponuda ulazi u rezultate."""
    todo = [o for o in offers if worth_details(pq, o.title, o.match, o.match_note)][:DETAILS_MAX]
    sem = asyncio.Semaphore(DETAILS_PARALLEL)

    async def one(o: Offer):
        async with sem:
            text = await _details(src, o)
        score, note = match(pq, o.title, o.extra.get("category", ""), details=text)
        if score > o.match:
            o.match, o.match_note = score, "; ".join(filter(None, [NOTE_FROM_DETAILS, note]))

    await asyncio.gather(*(one(o) for o in todo), return_exceptions=True)  # opis je bonus, ne smije srušiti izvor


async def run_source(src: Source, q: str, pq: dict, use_cache: bool = True) -> list[Offer]:
    """Dohvati, prepoznaj model (naslov, pa po potrebi opis oglasa) i dohvati stvarnu dostavu."""
    t0 = time.time()
    h = health[src.name]
    try:
        batches = await asyncio.gather(*(_fetch(src, t, use_cache) for t in search_terms(q, src.kind)))
        offers = list({o.key: o for batch in batches for o in batch}.values())
        for o in offers:
            o.match, o.match_note = match(pq, o.title, o.extra.get("category", ""))
        if src.details:
            try:
                await asyncio.wait_for(deep_check(src, pq, offers), SOURCE_TIMEOUT)
            except asyncio.TimeoutError:
                pass  # što je stiglo provjeriti, provjereno je
        hits = [o for o in offers if o.match >= SIMILAR_MIN]
        if src.enrich and hits:
            await asyncio.wait_for(src.enrich(hits), SOURCE_TIMEOUT)
        hits = [o for o in hits if not o.excluded]
        h.update(ok=True, last_ok=time.time(), error="", fails=0, n=len(offers))
        return hits
    except Exception as e:
        h.update(ok=False, error=f"{type(e).__name__}: {str(e)[:150]}", fails=h["fails"] + 1)
        raise
    finally:
        h["ms"] = int((time.time() - t0) * 1000)


# ---------- rangiranje ----------
def reference_price(offers: list[Offer]) -> float | None:
    """Medijan ukupne cijene točnog modela - iz novih ponuda ako ih ima barem 2, inače iz svih."""
    exact = [o for o in offers if o.match >= EXACT_MIN]
    new = [o.total for o in exact if o.condition == "new"]
    pool = new if len(new) >= 2 else [o.total for o in exact]
    return round(statistics.median(pool), 2) if len(pool) >= 2 else None


def mark_deals(offers: list[Offer], ref: float | None, threshold: float = DEAL_THRESHOLD) -> None:
    for o in offers:
        if ref and o.match >= EXACT_MIN:
            o.deal_pct = round(1 - o.total / ref, 3)
            o.is_deal = o.deal_pct >= threshold


def rank(offers: list[Offer]) -> list[Offer]:
    """Prvo točan model, zatim po ukupnoj cijeni (s dostavom)."""
    return sorted(offers, key=lambda o: (o.match < EXACT_MIN, o.total))


# ---------- javno sučelje ----------
async def _safe(src: Source, q: str, pq: dict, use_cache: bool):
    try:
        return src, await run_source(src, q, pq, use_cache), None
    except Exception as e:  # jedan izvor ne smije srušiti pretragu
        return src, [], e


async def stream(q: str, use_cache: bool = True, only: set[str] | None = None) -> AsyncIterator[tuple]:
    """Vraća (izvor, ponude, greška) čim pojedini izvor završi - UI prikazuje rezultate odmah."""
    pq = parse_query(q)
    pq["version_words"] = catalog.version_words(pq)
    sources = [s for s in SOURCES if not only or s.name in only]
    for fut in asyncio.as_completed([_safe(s, q, pq, use_cache) for s in sources]):
        yield await fut


async def search_all(q: str, use_cache: bool = True, only: set[str] | None = None) -> tuple[list[Offer], float | None]:
    offers = [o async for _src, res, _err in stream(q, use_cache, only) for o in res]
    ref = reference_price(offers)
    mark_deals(offers, ref)
    return rank(offers), ref
