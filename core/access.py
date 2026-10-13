"""Tko smije otvoriti app.

Pouzdani uređaji (bez ključa):
  - računalo/server na kojem app radi (localhost)
  - uređaji u TVOJOJ Tailscale mreži (adrese 100.64.0.0/10) - Tailscale pušta samo uređaje prijavljene
    tvojim računom, pa je to zaštita sama po sebi (tako radi i Oracle server)
Svi ostali (npr. mobitel na kućnom Wi-Fiju bez Tailscalea) moraju poslati tajni ključ: jednom kroz
?key=... (QR kod u Postavkama), nakon čega ga preglednik pamti u kolačiću.
"""
import io
import ipaddress
import secrets
import shutil
import socket
import subprocess

import segno

from . import db

COOKIE = "ph_key"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
TAILSCALE_NETWORKS = [ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48")]


def key() -> str:
    access_key = db.get_setting("access_key")
    if not access_key:
        access_key = secrets.token_urlsafe(18)
        db.set_setting("access_key", access_key)
    return access_key


def is_local(client_host: str | None) -> bool:
    return client_host in LOCAL_HOSTS


def is_tailscale(client_host: str | None) -> bool:
    try:
        address = ipaddress.ip_address(client_host or "")
    except ValueError:
        return False
    return any(address in network for network in TAILSCALE_NETWORKS)


def is_trusted(client_host: str | None) -> bool:
    """Uređaj kojem ne treba ključ: računalo/server ili tvoj uređaj u Tailscale mreži."""
    return is_local(client_host) or is_tailscale(client_host)


def allowed(client_host: str | None, cookie_key: str | None, query_key: str | None) -> bool:
    if is_trusted(client_host):
        return True
    expected = key()
    return any(given and secrets.compare_digest(given, expected) for given in (cookie_key, query_key))


def lan_ip() -> str:
    """IP adresa na kućnoj mreži (UDP 'connect' ne šalje nikakav paket)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("10.255.255.255", 1))
            return probe.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def tailscale_ip() -> str | None:
    """Tailscale adresa ovog računala/servera (100.x.y.z), ako je Tailscale instaliran i spojen."""
    command = shutil.which("tailscale")
    if not command:
        return None
    try:
        result = subprocess.run([command, "ip", "-4"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    address = result.stdout.strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else ""
    return address if is_tailscale(address) else None


def mobile_url(port: int) -> str:
    """Adresa za mobitel: Tailscale adresa (radi s bilo kojeg mjesta, bez ključa) ili kućna mreža s ključem."""
    tailnet = tailscale_ip()
    return f"http://{tailnet}:{port}/" if tailnet else f"http://{lan_ip()}:{port}/?key={key()}"


def qr_svg(text: str) -> str:
    buffer = io.BytesIO()
    segno.make(text, error="m").save(buffer, kind="svg", scale=5, border=2, dark="#111", light="#fff")
    return buffer.getvalue().decode()
