"""Telegram obavijesti. Token bota i chat ID upisuje korisnik u Postavkama (spremaju se samo lokalno u data.db).

Ne stižu poruke? Postavke -> "Pošalji test" pokaže točnu grešku koju vrati Telegram.
"""
import html

from . import db
from .http import session
from .models import Offer

API = "https://api.telegram.org/bot{token}/{method}"


def configured() -> bool:
    return bool(db.get_setting("tg_token") and db.get_setting("tg_chat"))


async def send(message: str) -> tuple[bool, str]:
    """Pošalji poruku (HTML). Vraća (uspjelo, opis greške)."""
    token, chat_id = db.get_setting("tg_token"), db.get_setting("tg_chat")
    if not token or not chat_id:
        return False, "Telegram nije podešen"
    async with session() as client:
        response = await client.post(API.format(token=token, method="sendMessage"),
                                     json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"})
    ok = response.status_code == 200 and response.json().get("ok")
    return bool(ok), "" if ok else response.text[:200]


async def detect_chat() -> tuple[str | None, str]:
    """Nakon što korisnik pošalje bilo koju poruku svom botu, ovdje pročitamo njegov chat ID.
    Vraća (chat_id ili None, ime ili opis problema)."""
    token = db.get_setting("tg_token")
    if not token:
        return None, "prvo upiši token"
    async with session() as client:
        response = await client.get(API.format(token=token, method="getUpdates"))
    data = response.json()
    if not data.get("ok"):
        return None, data.get("description", "neispravan token")
    for update in reversed(data.get("result", [])):
        chat = (update.get("message") or update.get("my_chat_member") or {}).get("chat")
        if chat:
            return str(chat["id"]), chat.get("first_name") or chat.get("title") or ""
    return None, "nema poruka - pošalji botu bilo što (npr. /start) pa pokušaj ponovno"


def format_offer(offer: Offer, header: str) -> str:
    """Poruka o jednoj ponudi: naslov, ukupna cijena s raspisom, dostava, izvor, link."""
    esc = html.escape
    price_parts = f"cijena {offer.price:.2f} €"
    if offer.fees:
        price_parts += f" + naknada {offer.fees:.2f} €"
    price_parts += f" + dostava {offer.shipping:.2f} €" if offer.shipping is not None else " + dostava ?"
    source_line = f"🏷 {esc(offer.source_name)} · {'novo' if offer.condition == 'new' else 'rabljeno'}"
    if offer.location:
        source_line += f" · {esc(offer.location)}"
    if offer.is_auction:
        source_line += " · AUKCIJA"

    lines = [f"<b>{esc(header)}</b>", f"<b>{esc(offer.title)}</b>",
             f"💶 <b>UKUPNO {offer.total:.2f} €</b>  ({price_parts})",
             f"📦 {esc(offer.shipping_note)}", source_line]
    if offer.deal_pct > 0:
        lines.append(f"🔥 {offer.deal_pct * 100:.0f}% ispod uobičajene cijene")
    if offer.match_note:
        lines.append(f"ℹ️ {esc(offer.match_note)}")
    lines.append(offer.url)
    return "\n".join(lines)
