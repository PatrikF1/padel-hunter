"""Padel Hunter - web server (FastAPI). Pokretanje: start.bat  ->  http://127.0.0.1:8777

Ova datoteka samo povezuje dijelove; logika je u core/ (pretraga, praćenje...) i sources/ (izvori).
Rute:
  /                      sučelje (static/)
  /api/search            pretraga - rezultati stižu izvor po izvor (Server-Sent Events)
  /api/catalog           katalog reketa za filtere
  /api/watches           praćeni modeli
  /api/settings          Telegram, eBay ključ
  /api/mobile            QR kod za mobitel
  /api/health            stanje svakog izvora
  /api/debug/...         traženje grešaka (vidi README -> "Kad nešto ne radi")
Mobitel na istoj Wi-Fi mreži: Postavke -> QR kod (adresa s tajnim ključem)."""
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import access, catalog, db, engine, telegram, watcher
from core.matcher import match
from sources import BY_NAME, SOURCES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATIC = Path(__file__).parent / "static"
HOST, PORT = "0.0.0.0", 8777  # 0.0.0.0 = dostupno i mobitelu na kućnoj mreži (uz tajni ključ, vidi core/access.py)


@asynccontextmanager
async def lifespan(_app):
    catalog.load()
    tasks = [asyncio.create_task(watcher.loop()), asyncio.create_task(catalog.refresh_if_stale())]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="Padel Hunter", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def require_key(request: Request, call_next):
    """Računalo uvijek smije; ostali uređaji samo s ključem (?key=... jednom, zatim kolačić)."""
    host = request.client.host if request.client else None
    query_key = request.query_params.get("key")
    if not access.allowed(host, request.cookies.get(access.COOKIE), query_key):
        return PlainTextResponse("Pristup zabranjen - skeniraj QR kod iz Postavki na računalu.", status_code=403)
    if query_key:  # zapamti ključ i makni ga iz adrese
        params = urlencode([(k, v) for k, v in request.query_params.multi_items() if k != "key"])
        target = request.url.path + ("?" + params if params else "")
        response = RedirectResponse(target, status_code=303)
        response.set_cookie(access.COOKIE, query_key, max_age=365 * 24 * 3600, httponly=True, samesite="lax")
        return response
    return await call_next(request)


@app.middleware("http")
async def always_revalidate_ui(request: Request, call_next):
    """Preglednik (i iPhone ikona) uvijek provjeri ima li novije verzije sučelja - inače bi nakon ažuriranja
    servera još danima prikazivao stari izgled iz predmemorije."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/search")
async def search(q: str, fresh: int = 0):
    """Server-Sent Events: 'start' (popis izvora), 'source' (rezultati jednog izvora), 'done'."""
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(400, "upiši model")

    async def events():
        started = time.time()
        yield f"event: start\ndata: {json.dumps({'sources': [s.label for s in SOURCES]})}\n\n"
        async for source, offers, error in engine.stream(query, use_cache=not fresh):
            status = engine.health[source.name]
            payload = {"source": source.name, "label": source.label, "ok": error is None,
                       "error": status.error, "ms": status.ms,  # i izvor koji radi može imati napomenu
                       "offers": [o.to_dict() for o in offers]}
            yield f"event: source\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        yield f"event: done\ndata: {json.dumps({'ms': int((time.time() - started) * 1000)})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---- katalog (filteri i odabir točne verzije) ----
@app.get("/api/catalog")
def get_catalog():
    return {"updated": catalog.catalog.updated, "rackets": [asdict(r) for r in catalog.catalog.rackets]}


@app.post("/api/catalog/refresh")
async def refresh_catalog():
    return {"count": await catalog.refresh()}


# ---- mobitel ----
@app.get("/api/mobile")
def mobile(request: Request):
    """Adresa i QR kod za mobitel - samo za pouzdane uređaje (računalo/server ili tvoja Tailscale mreža),
    jer adresa za kućnu mrežu sadrži tajni ključ."""
    if not access.is_trusted(request.client.host if request.client else None):
        raise HTTPException(403, "samo s računala ili iz tvoje Tailscale mreže")
    url = access.mobile_url(PORT)
    return {"url": url, "qr": access.qr_svg(url)}


@app.get("/api/health")
def health():
    return engine.health_report()


# ---- traženje grešaka ----
@app.get("/api/debug/parse")
def debug_parse(q: str):
    """Kako je upit shvaćen: brend, riječi modela, brojevi, godina, oznake verzija iz kataloga."""
    wanted = engine.wanted_racket(q)
    return asdict(wanted) | {"years": sorted(wanted.years), "version_words": sorted(wanted.version_words)}


@app.get("/api/debug/match")
def debug_match(q: str, title: str, details: str = ""):
    """Zašto (ne) prolazi jedan naslov oglasa, npr. ?q=adidas metalbone 3.3&title=Adidas Metalbone CTRL 3.3"""
    return asdict(match(engine.wanted_racket(q), title, details=details))


@app.get("/api/debug/explain")
async def debug_explain(q: str, source: str):
    """SVE ponude jednog izvora s ocjenom i razlogom, npr. ?q=adidas metalbone&source=vinted"""
    if source not in BY_NAME:
        raise HTTPException(404, "nepoznat izvor; postoje: " + ", ".join(BY_NAME))
    return await engine.explain(q, source)


# ---- praćenje ----
class WatchIn(BaseModel):
    query: str
    max_total: float | None = None
    include_used: bool = True
    include_similar: bool = False


@app.get("/api/watches")
def list_watches():
    return [asdict(w) for w in db.list_watches()]


@app.post("/api/watches")
def add_watch(watch: WatchIn):
    if len(watch.query.strip()) < 2:
        raise HTTPException(400, "upiši model")
    return {"id": db.add_watch(watch.query, watch.max_total, watch.include_used, watch.include_similar)}


@app.delete("/api/watches/{watch_id}")
def delete_watch(watch_id: int):
    db.delete_watch(watch_id)
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
    token = db.get_setting("tg_token")
    return {"tg_token_set": bool(token), "tg_token_hint": _hint(token), "tg_chat": db.get_setting("tg_chat"),
            "configured": telegram.configured(),
            "ebay_set": bool(db.get_setting("ebay_client_id") and db.get_setting("ebay_client_secret")),
            "ebay_hint": _hint(db.get_setting("ebay_client_id"))}


@app.post("/api/settings")
def save_settings(settings: SettingsIn):
    for key, value in settings.model_dump(exclude_none=True).items():
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
    print(f"Padel Hunter radi:  http://127.0.0.1:{PORT}   (mobitel: QR kod u Postavkama)")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
