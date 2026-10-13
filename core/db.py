import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data.db"
_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.executescript("""
CREATE TABLE IF NOT EXISTS watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    max_total REAL,              -- javi ako je ukupno (s dostavom) <= ovo
    include_used INTEGER DEFAULT 1,
    include_similar INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1,
    created REAL,
    last_market REAL DEFAULT 0,
    last_shop REAL DEFAULT 0,
    ref REAL,                    -- referentna (medijan) cijena modela
    best_total REAL,
    best_url TEXT
);
CREATE TABLE IF NOT EXISTS seen (
    watch_id INTEGER, key TEXT, total REAL, first_seen REAL,
    PRIMARY KEY (watch_id, key)
);
CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT);
""")


def q(sql: str, args=()) -> list[dict]:
    with _lock:
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


def x(sql: str, args=()) -> int:
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur.lastrowid


def get_setting(k: str, default: str = "") -> str:
    r = q("SELECT v FROM settings WHERE k=?", (k,))
    return r[0]["v"] if r else default


def set_setting(k: str, v: str):
    x("INSERT INTO settings(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


def add_watch(query: str, max_total: float | None, include_used: bool, include_similar: bool) -> int:
    return x("INSERT INTO watches(query, max_total, include_used, include_similar, created) VALUES(?,?,?,?,?)",
             (query.strip(), max_total, int(include_used), int(include_similar), time.time()))
