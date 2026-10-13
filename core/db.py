"""Lokalna baza (data.db, SQLite). SAV SQL je u ovoj datoteci - ostatak koda koristi funkcije ispod.

Tablice:
  watches   - praćeni modeli (watchlist)
  seen      - ponude koje je praćenje već vidjelo (da se o istoj ne javlja dvaput)
  settings  - postavke i tajne (Telegram token, eBay ključ, ključ za mobitel) - nikad ne idu na GitHub
"""
import sqlite3
import threading
import time
from dataclasses import dataclass, fields
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data.db"
FIRST_CHECK_MARKER = "__init__"  # red u "seen" koji znači: prvi krug praćenja je gotov

_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.executescript("""
CREATE TABLE IF NOT EXISTS watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    max_total REAL,              -- javi ako je ukupno (s dostavom) <= ovo; NULL = javi samo apsurdne cijene
    include_used INTEGER DEFAULT 1,
    include_similar INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1,
    created REAL,
    last_market REAL DEFAULT 0,  -- zadnja provjera oglasnika (unix vrijeme)
    last_shop REAL DEFAULT 0,    -- zadnja provjera trgovina
    ref REAL,                    -- uobičajena (medijan) cijena modela
    best_total REAL,             -- najniža viđena ukupna cijena
    best_url TEXT
);
CREATE TABLE IF NOT EXISTS seen (
    watch_id INTEGER, key TEXT, total REAL, first_seen REAL,
    PRIMARY KEY (watch_id, key)
);
CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT);
""")


def _rows(sql: str, args=()) -> list[dict]:
    with _lock:
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


def _execute(sql: str, args=()) -> int:
    with _lock:
        cursor = _conn.execute(sql, args)
        _conn.commit()
        return cursor.lastrowid


# ---------- postavke ----------
def get_setting(key: str, default: str = "") -> str:
    found = _rows("SELECT v FROM settings WHERE k=?", (key,))
    return found[0]["v"] if found else default


def set_setting(key: str, value: str) -> None:
    _execute("INSERT INTO settings(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, value))


# ---------- praćeni modeli ----------
@dataclass
class Watch:
    """Jedan red tablice watches (praćeni model)."""
    id: int
    query: str
    max_total: float | None      # javi ako je ukupno <= ovo; None = javi samo apsurdne cijene
    include_used: bool
    include_similar: bool
    active: bool
    created: float
    last_market: float           # zadnja provjera oglasnika (unix vrijeme)
    last_shop: float             # zadnja provjera trgovina
    ref: float | None            # uobičajena cijena modela
    best_total: float | None     # najniža viđena ukupna cijena
    best_url: str | None


def _watch(row: dict) -> Watch:
    return Watch(**{f.name: row[f.name] for f in fields(Watch)})


def list_watches() -> list[Watch]:
    return [_watch(r) for r in _rows("SELECT * FROM watches ORDER BY id DESC")]


def active_watches() -> list[Watch]:
    return [_watch(r) for r in _rows("SELECT * FROM watches WHERE active=1")]


def add_watch(query: str, max_total: float | None, include_used: bool, include_similar: bool) -> int:
    return _execute("INSERT INTO watches(query, max_total, include_used, include_similar, created) VALUES(?,?,?,?,?)",
                    (query.strip(), max_total, int(include_used), int(include_similar), time.time()))


def delete_watch(watch_id: int) -> None:
    _execute("DELETE FROM watches WHERE id=?", (watch_id,))
    _execute("DELETE FROM seen WHERE watch_id=?", (watch_id,))


def mark_checked(watch_id: int, markets: bool = False, shops: bool = False) -> None:
    now = time.time()
    if markets:
        _execute("UPDATE watches SET last_market=? WHERE id=?", (now, watch_id))
    if shops:
        _execute("UPDATE watches SET last_shop=? WHERE id=?", (now, watch_id))


def set_reference_price(watch_id: int, price: float) -> None:
    _execute("UPDATE watches SET ref=? WHERE id=?", (price, watch_id))


def set_best_offer(watch_id: int, total: float, url: str) -> None:
    _execute("UPDATE watches SET best_total=?, best_url=? WHERE id=?", (total, url, watch_id))


# ---------- viđene ponude ----------
def first_check_done(watch_id: int) -> bool:
    return bool(_rows("SELECT 1 FROM seen WHERE watch_id=? LIMIT 1", (watch_id,)))


def mark_first_check_done(watch_id: int) -> None:
    _execute("INSERT OR IGNORE INTO seen VALUES(?,?,?,?)", (watch_id, FIRST_CHECK_MARKER, 0, time.time()))


def seen_totals(watch_id: int) -> dict[str, float]:
    """offer.key -> zadnja viđena ukupna cijena."""
    return {r["key"]: r["total"] for r in _rows("SELECT key, total FROM seen WHERE watch_id=?", (watch_id,))}


def remember_offer(watch_id: int, offer_key: str, total: float) -> None:
    _execute("INSERT OR REPLACE INTO seen VALUES(?,?,?,?)", (watch_id, offer_key, total, time.time()))


def update_seen_total(watch_id: int, offer_key: str, total: float) -> None:
    _execute("UPDATE seen SET total=? WHERE watch_id=? AND key=?", (total, watch_id, offer_key))
