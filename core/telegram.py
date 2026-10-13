"""Telegram obavijesti. Token bota i chat ID upisuje korisnik u postavkama (spremaju se samo lokalno u data.db)."""
import html

from . import db
from .http import session
from .models import Offer


def configured() -> bool:
    return bool(db.get_setting("tg_token") and db.get_setting("tg_chat"))


async def send(msg: str) -> tuple[bool, str]:
    token, chat = db.get_setting("tg_token"), db.get_setting("tg_chat")
    if not token or not chat:
        return False, "Telegram nije podešen"
    async with session() as s:
        r = await s.post(f"https://api.telegram.org/bot{token}/sendMessage",
                         json={"chat_id": chat, "text": msg, "parse_mode": "HTML"})
    ok = r.status_code == 200 and r.json().get("ok")
    return bool(ok), "" if ok else r.text[:200]


async def detect_chat() -> tuple[str | None, str]:
    """Nakon što korisnik pošalje bilo koju poruku svom botu, ovdje pročitamo njegov chat ID."""
    token = db.get_setting("tg_token")
    if not token:
        return None, "prvo upiši token"
    async with session() as s:
        r = await s.get(f"https://api.telegram.org/bot{token}/getUpdates")
    j = r.json()
    if not j.get("ok"):
        return None, j.get("description", "neispravan token")
    for upd in reversed(j.get("result", [])):
        chat = (upd.get("message") or upd.get("my_chat_member") or {}).get("chat")
        if chat:
            return str(chat["id"]), chat.get("first_name") or chat.get("title") or ""
    return None, "nema poruka - pošalji botu bilo što (npr. /start) pa pokušaj ponovno"


def format_offer(o: Offer, header: str) -> str:
    e = html.escape
    lines = [f"<b>{e(header)}</b>", f"<b>{e(o.title)}</b>",
             f"💶 <b>UKUPNO {o.total:.2f} €</b>  (cijena {o.price:.2f} €"
             + (f" + naknada {o.fees:.2f} €" if o.fees else "")
             + (f" + dostava {o.shipping:.2f} €" if o.shipping is not None else " + dostava ?") + ")",
             f"📦 {e(o.shipping_note)}",
             f"🏷 {e(o.source_name)} · {'novo' if o.condition == 'new' else 'rabljeno'}"
             + (f" · {e(o.location)}" if o.location else "") + (" · AUKCIJA" if o.is_auction else "")]
    if o.deal_pct > 0:
        lines.append(f"🔥 {o.deal_pct * 100:.0f}% ispod uobičajene cijene")
    if o.match_note:
        lines.append(f"ℹ️ {e(o.match_note)}")
    lines.append(o.url)
    return "\n".join(lines)
