"""Padel Hunter - pokretanje: start.bat  (ili: .venv\\Scripts\\python app.py)  ->  http://127.0.0.1:8777"""
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import catalog, db, engine, telegram, watcher
from core.matcher import parse_query
from sources import SOURCES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_app):
    catalog.load()
    tasks = [asyncio.create_task(watcher.loop()), asyncio.create_task(catalog.refresh_if_stale())]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Padel Hunter", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/search")
async def search(q: str, fresh: int = 0):
    q = q.strip()
    if len(q) < 2:
        raise HTTPException(400, "upiši model")

    async def events():
        t0 = time.time()
        yield f"event: start\ndata: {json.dumps({'sources': [s.label for s in SOURCES]})}\n\n"
        async for src, offers, err in engine.stream(q, use_cache=not fresh):
            h = engine.health[src.name]
            payload = {"source": src.name, "label": src.label, "ok": err is None,
                       "error": h["error"] if err else "", "ms": h["ms"],
                       "offers": [o.to_dict() for o in offers]}
            yield f"event: source\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        yield f"event: done\ndata: {json.dumps({'ms': int((time.time() - t0) * 1000)})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/parse")
def parse(q: str):
    pq = parse_query(q)
    pq["years"] = sorted(pq["years"])
    return pq


# ---- katalog (filteri i odabir točne verzije) ----
@app.get("/api/catalog")
def get_catalog():
    return {"updated": catalog.catalog.updated, "rackets": [asdict(r) for r in catalog.catalog.rackets]}


@app.post("/api/catalog/refresh")
async def refresh_catalog():
    return {"count": await catalog.refresh()}


@app.get("/api/health")
def health():
    return engine.health


# ---- praćenje ----
class WatchIn(BaseModel):
    query: str
    max_total: float | None = None
    include_used: bool = True
    include_similar: bool = False


@app.get("/api/watches")
def watches():
    return db.q("SELECT * FROM watches ORDER BY id DESC")


@app.post("/api/watches")
def add_watch(w: WatchIn):
    if len(w.query.strip()) < 2:
        raise HTTPException(400, "upiši model")
    return {"id": db.add_watch(w.query, w.max_total, w.include_used, w.include_similar)}


@app.delete("/api/watches/{wid}")
def del_watch(wid: int):
    db.x("DELETE FROM watches WHERE id=?", (wid,))
    db.x("DELETE FROM seen WHERE watch_id=?", (wid,))
    return {"ok": True}


# ---- postavke / Telegram ----
class SettingsIn(BaseModel):
    """Tajne (tokeni, ključevi) se spremaju samo lokalno u data.db i nikad se ne vraćaju u preglednik."""
    tg_token: str | None = None
    tg_chat: str | None = None
    ebay_client_id: str | None = None
    ebay_client_secret: str | None = None


def _hint(secret: str) -> str:
    return secret[:6] + "…" if secret else ""


@app.get("/api/settings")
def get_settings():
    tok = db.get_setting("tg_token")
    return {"tg_token_set": bool(tok), "tg_token_hint": _hint(tok), "tg_chat": db.get_setting("tg_chat"),
            "configured": telegram.configured(),
            "ebay_set": bool(db.get_setting("ebay_client_id") and db.get_setting("ebay_client_secret")),
            "ebay_hint": _hint(db.get_setting("ebay_client_id"))}


@app.post("/api/settings")
def save_settings(s: SettingsIn):
    for key, value in s.model_dump(exclude_none=True).items():
        db.set_setting(key, value.strip())
    return get_settings()


@app.post("/api/telegram/detect")
async def tg_detect():
    chat, info = await telegram.detect_chat()
    if chat:
        db.set_setting("tg_chat", chat)
    return {"chat": chat, "info": info}


@app.post("/api/telegram/test")
async def tg_test():
    ok, err = await telegram.send("✅ Padel Hunter radi - ovdje stižu obavijesti o reketima.")
    return {"ok": ok, "error": err}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8777, log_level="warning")
