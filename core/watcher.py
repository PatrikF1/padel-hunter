"""Pozadinsko praćenje (watchlist).

Oglasnici se provjeravaju svakih ~90 s, trgovine svakih 15 min. Kad se pojavi NOVI oglas ili PADNE cijena,
a ukupna cijena je ispod tvog praga (ili je apsurdno niska ako prag nije zadan) -> Telegram poruka.
Prvi krug samo zapamti postojeće oglase (bez spama) i javi trenutno najbolju ponudu.

Ne stiže obavijest? Provjeri: Postavke -> Telegram (Pošalji test), Praćenje -> "provjereno u" (radi li petlja),
i konzolu (logger "watcher").
"""
import asyncio
import logging
import time

from sources import SOURCES

from . import db, engine, telegram
from .db import Watch
from .models import Offer

MARKET_EVERY_SECONDS = 90
SHOP_EVERY_SECONDS = 15 * 60
LOOP_TICK_SECONDS = 15         # koliko često petlja provjerava je li nešto "na redu"
FAILS_BEFORE_ALERT = 3         # uzastopnih grešaka izvora prije upozorenja na Telegram
PRICE_DROP_MIN = 0.5           # EUR - manje promjene cijene ignoriramo

MARKETS = {s.name for s in SOURCES if s.kind == "market"}
SHOPS = {s.name for s in SOURCES if s.kind == "shop"}
log = logging.getLogger("watcher")
_alerted_sources: set[str] = set()


# ---------- pravila ----------
def is_relevant(offer: Offer, watch: Watch) -> bool:
    """Spada li ponuda u ovo praćenje (točan model ili i varijante; i rabljeno ili samo novo)."""
    min_match = engine.SIMILAR_MIN if watch.include_similar else engine.EXACT_MIN
    return offer.match >= min_match and (watch.include_used or offer.condition == "new")


def is_notifiable(offer: Offer, watch: Watch) -> bool:
    """Isplati li se javiti: ispod praga, ili apsurdno jeftino ako prag nije zadan."""
    return offer.total <= watch.max_total if watch.max_total else offer.is_deal


# ---------- jedna provjera ----------
async def check(watch: Watch, sources: set[str], first: bool) -> None:
    offers, reference = await engine.search_all(watch.query, use_cache=False, only=sources)
    if reference and (first or sources == SHOPS):  # uobičajenu cijenu računamo kad imamo trgovine
        watch.ref = reference
        db.set_reference_price(watch.id, reference)
    engine.mark_deals(offers, watch.ref)
    offers = [o for o in offers if is_relevant(o, watch)]

    if first:
        db.mark_first_check_done(watch.id)
    await _notify_new_and_cheaper(watch, offers, notify=not first)
    _remember_best(watch, offers)

    if first and offers:
        best = min(offers, key=lambda o: o.total)
        await telegram.send(telegram.format_offer(best, f"👀 Pratim: {watch.query} - trenutno najbolje"))


async def _notify_new_and_cheaper(watch: Watch, offers: list[Offer], notify: bool) -> None:
    seen = db.seen_totals(watch.id)
    for offer in offers:
        previous_total = seen.get(offer.key)
        if previous_total is None:
            db.remember_offer(watch.id, offer.key, offer.total)
            if notify and is_notifiable(offer, watch):
                await telegram.send(telegram.format_offer(offer, f"🆕 NOVO: {watch.query}"))
        elif offer.total < previous_total - PRICE_DROP_MIN:
            db.update_seen_total(watch.id, offer.key, offer.total)
            if notify and is_notifiable(offer, watch):
                header = f"📉 PAD CIJENE ({previous_total:.2f} → {offer.total:.2f} €): {watch.query}"
                await telegram.send(telegram.format_offer(offer, header))


def _remember_best(watch: Watch, offers: list[Offer]) -> None:
    best = min(offers, key=lambda o: o.total, default=None)
    if best and (watch.best_total is None or best.total < watch.best_total):
        db.set_best_offer(watch.id, best.total, best.url)


# ---------- zdravlje izvora ----------
async def alert_broken_sources() -> None:
    for name, status in engine.health.items():
        if status.fails >= FAILS_BEFORE_ALERT and name not in _alerted_sources:
            _alerted_sources.add(name)
            await telegram.send(f"⚠️ Izvor <b>{status.label}</b> ne radi ({status.fails}x zaredom): {status.error}")
        elif status.ok and name in _alerted_sources:
            _alerted_sources.discard(name)
            await telegram.send(f"✅ Izvor <b>{status.label}</b> opet radi")


# ---------- petlja ----------
async def _run_if_due(watch: Watch) -> None:
    now = time.time()
    if not db.first_check_done(watch.id):
        db.mark_checked(watch.id, markets=True, shops=True)
        await check(watch, MARKETS | SHOPS, first=True)
        return
    if now - watch.last_market >= MARKET_EVERY_SECONDS:
        db.mark_checked(watch.id, markets=True)
        await check(watch, MARKETS, first=False)
    if now - watch.last_shop >= SHOP_EVERY_SECONDS:
        db.mark_checked(watch.id, shops=True)
        await check(watch, SHOPS, first=False)


async def loop() -> None:
    while True:
        for watch in db.active_watches():
            try:
                await _run_if_due(watch)
            except Exception:
                log.exception("praćenje '%s' nije uspjelo", watch.query)
        try:
            await alert_broken_sources()
        except Exception:
            log.exception("slanje upozorenja nije uspjelo")
        await asyncio.sleep(LOOP_TICK_SECONDS)
