"""Pozadinsko praćenje (watchlist).

Oglasnici se provjeravaju svakih ~90 s, trgovine svakih 15 min. Kad se pojavi NOVI oglas ili PADNE cijena,
a ukupna cijena je ispod tvog praga (ili je apsurdno niska ako prag nije zadan) -> Telegram poruka.
Prvi krug samo zapamti postojeće oglase (bez spama) i javi trenutno najbolju ponudu.
"""
import asyncio
import logging
import time

from sources import SOURCES

from . import db, engine, telegram
from .models import Offer

MARKET_EVERY = 90          # s
SHOP_EVERY = 15 * 60       # s
TICK = 15                  # s - koliko često petlja provjerava je li nešto "na redu"
FAIL_ALERT = 3             # uzastopnih grešaka izvora prije upozorenja
PRICE_DROP_MIN = 0.5       # EUR - manje promjene ignoriramo
INIT_KEY = "__init__"      # oznaka da je prvi krug za watch gotov

MARKETS = {s.name for s in SOURCES if s.kind == "market"}
SHOPS = {s.name for s in SOURCES if s.kind == "shop"}
log = logging.getLogger("watcher")
_alerted_sources: set[str] = set()


# ---------- pravila ----------
def is_relevant(o: Offer, w: dict) -> bool:
    min_match = engine.SIMILAR_MIN if w["include_similar"] else engine.EXACT_MIN
    return o.match >= min_match and (w["include_used"] or o.condition == "new")


def is_notifiable(o: Offer, w: dict) -> bool:
    return o.total <= w["max_total"] if w["max_total"] else o.is_deal


# ---------- jedna provjera ----------
async def check(w: dict, only: set[str], first: bool) -> None:
    offers, ref = await engine.search_all(w["query"], use_cache=False, only=only)
    if ref and (first or only == SHOPS):  # referentnu cijenu računamo kad imamo trgovine
        w["ref"] = ref
        db.x("UPDATE watches SET ref=? WHERE id=?", (ref, w["id"]))
    engine.mark_deals(offers, w.get("ref"))
    offers = [o for o in offers if is_relevant(o, w)]

    if first:
        db.x("INSERT OR IGNORE INTO seen VALUES(?,?,?,?)", (w["id"], INIT_KEY, 0, time.time()))
    await _process_offers(w, offers, notify=not first)
    _update_best(w, offers)

    if first and offers:
        best = min(offers, key=lambda o: o.total)
        await telegram.send(telegram.format_offer(best, f"👀 Pratim: {w['query']} - trenutno najbolje"))


async def _process_offers(w: dict, offers: list[Offer], notify: bool) -> None:
    seen = {r["key"]: r["total"] for r in db.q("SELECT key, total FROM seen WHERE watch_id=?", (w["id"],))}
    for o in offers:
        old = seen.get(o.key)
        if old is None:
            db.x("INSERT OR REPLACE INTO seen VALUES(?,?,?,?)", (w["id"], o.key, o.total, time.time()))
            if notify and is_notifiable(o, w):
                await telegram.send(telegram.format_offer(o, f"🆕 NOVO: {w['query']}"))
        elif o.total < old - PRICE_DROP_MIN:
            db.x("UPDATE seen SET total=? WHERE watch_id=? AND key=?", (o.total, w["id"], o.key))
            if notify and is_notifiable(o, w):
                header = f"📉 PAD CIJENE ({old:.2f} → {o.total:.2f} €): {w['query']}"
                await telegram.send(telegram.format_offer(o, header))


def _update_best(w: dict, offers: list[Offer]) -> None:
    best = min(offers, key=lambda o: o.total, default=None)
    if best and (w["best_total"] is None or best.total < w["best_total"]):
        db.x("UPDATE watches SET best_total=?, best_url=? WHERE id=?", (best.total, best.url, w["id"]))


# ---------- zdravlje izvora ----------
async def alert_broken_sources() -> None:
    for name, h in engine.health.items():
        if h["fails"] >= FAIL_ALERT and name not in _alerted_sources:
            _alerted_sources.add(name)
            await telegram.send(f"⚠️ Izvor <b>{h['label']}</b> ne radi ({h['fails']}x zaredom): {h['error']}")
        elif h["ok"] and name in _alerted_sources:
            _alerted_sources.discard(name)
            await telegram.send(f"✅ Izvor <b>{h['label']}</b> opet radi")


# ---------- petlja ----------
async def _run_due(w: dict) -> None:
    now = time.time()
    if not db.q("SELECT 1 FROM seen WHERE watch_id=? LIMIT 1", (w["id"],)):
        db.x("UPDATE watches SET last_market=?, last_shop=? WHERE id=?", (now, now, w["id"]))
        await check(w, MARKETS | SHOPS, first=True)
        return
    if now - w["last_market"] >= MARKET_EVERY:
        db.x("UPDATE watches SET last_market=? WHERE id=?", (now, w["id"]))
        await check(w, MARKETS, first=False)
    if now - w["last_shop"] >= SHOP_EVERY:
        db.x("UPDATE watches SET last_shop=? WHERE id=?", (now, w["id"]))
        await check(w, SHOPS, first=False)


async def loop() -> None:
    while True:
        for w in db.q("SELECT * FROM watches WHERE active=1"):
            try:
                await _run_due(w)
            except Exception:
                log.exception("praćenje '%s' nije uspjelo", w["query"])
        try:
            await alert_broken_sources()
        except Exception:
            log.exception("slanje upozorenja nije uspjelo")
        await asyncio.sleep(TICK)
