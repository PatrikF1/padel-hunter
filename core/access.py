"""Pristup s mobitela (i drugih uređaja na kućnoj mreži).

Računalo na kojem app radi uvijek ima pristup. Svaki drugi uređaj mora poslati tajni ključ:
jednom kroz ?key=... (QR kod u Postavkama), nakon čega ga preglednik pamti u kolačiću.
"""
import io
import secrets
import socket

import segno

from . import db

COOKIE = "ph_key"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def key() -> str:
    k = db.get_setting("access_key")
    if not k:
        k = secrets.token_urlsafe(18)
        db.set_setting("access_key", k)
    return k


def is_local(client_host: str | None) -> bool:
    return client_host in LOCAL_HOSTS


def allowed(client_host: str | None, cookie_key: str | None, query_key: str | None) -> bool:
    if is_local(client_host):
        return True
    expected = key()
    return any(k and secrets.compare_digest(k, expected) for k in (cookie_key, query_key))


def lan_ip() -> str:
    """IP adresa računala na kućnoj mreži (UDP 'connect' ne šalje nikakav paket)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def mobile_url(port: int) -> str:
    return f"http://{lan_ip()}:{port}/?key={key()}"


def qr_svg(text: str) -> str:
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="svg", scale=5, border=2, dark="#111", light="#fff")
    return buf.getvalue().decode()
