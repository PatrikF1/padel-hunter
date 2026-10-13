"""Zajednički HTTP klijent.

curl_cffi imitira pravi preglednik (TLS otisak). Uz to je klijent PRISTOJAN: prema svakoj stranici ide
ograničen broj istovremenih zahtjeva s razmakom, jer oglasnici (npr. Vinted) blokiraju prebrze klijente.
Kad stranica ipak odgovori 429 (previše zahtjeva) ili Cloudflare provjerom, prema njoj se neko vrijeme ne šalje
ništa (RateLimited), a pretraga prikazuje nedavne rezultate tog izvora (core/engine.py -> fetch).
"""
import asyncio
import json
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from curl_cffi.requests import AsyncSession

TIMEOUT = 10


@dataclass(frozen=True)
class Limit:
    parallel: int          # najviše istovremenih zahtjeva
    spacing: float         # najmanji razmak između početaka zahtjeva (s)
    burst: int = 0         # budžet: toliko zahtjeva smije odmah... (0 = bez budžeta)
    refill: float = 0.0    # ...a zatim jedan novi svakih `refill` sekundi


HOST_LIMITS = {
    # Vinted, izmjereno 2026-10-13: 22 zahtjeva/min prolazi satima, ~25 zahtjeva u 25 s daje 429.
    # Jedna pretraga treba ~8 zahtjeva (stranice + opisi), pa ide odmah; sljedeće čekaju punjenje (20/min).
    "www.vinted.hr": Limit(parallel=2, spacing=0.5, burst=8, refill=3.0),
    "www.njuskalo.hr": Limit(2, 0.4),
    "www.index.hr": Limit(3, 0.2),
    "www.ebay.de": Limit(1, 1.0),
}
DEFAULT_LIMIT = Limit(6, 0.0)
COOLDOWN_SECONDS = 30    # pauza nakon 429 kad stranica ne pošalje Retry-After
CHALLENGE_SECONDS = 600  # pauza kad Cloudflare postavi provjeru (403): to je teža blokada, prolazi tek za neko vrijeme


class RateLimited(Exception):
    """Stranica je odgovorila 429 ili Cloudflare provjerom (403) - do isteka pauze zahtjevi prema njoj odmah padaju (ne pogoršavamo blokadu)."""


class _Gate:
    def __init__(self, limit: Limit):
        self.limit, self.sem = limit, asyncio.Semaphore(limit.parallel)
        self.lock, self.next_at = asyncio.Lock(), 0.0
        self.tokens, self.refilled_at = float(limit.burst), time.monotonic()
        self.blocked_until, self.status = 0.0, 429   # pauza nakon blokade i kod kojim je stranica odgovorila

    def _budget_wait(self) -> float:
        """Koliko čekati na sljedeći zahtjev iz budžeta (i odmah ga potroši)."""
        limit, now = self.limit, time.monotonic()
        if not limit.burst:
            return 0.0
        self.tokens = min(limit.burst, self.tokens + (now - self.refilled_at) / limit.refill)
        self.refilled_at = now
        self.tokens -= 1  # smije u minus: tko čeka, već je u redu
        return max(0.0, -self.tokens * limit.refill)

    def check(self, host: str, status: int = 0) -> None:
        wait = self.blocked_until - time.monotonic()
        if wait > 0:
            self.status = status or self.status
            raise RateLimited(f"{host} ograničava zahtjeve (HTTP {self.status}), pauza još {wait:.0f} s")

    async def __aenter__(self):
        await self.sem.acquire()
        try:
            async with self.lock:  # razmak između početaka zahtjeva
                wait = max(self.next_at - time.monotonic(), self._budget_wait())
                if wait > 0:
                    await asyncio.sleep(wait)
                self.next_at = time.monotonic() + self.limit.spacing
        except BaseException:  # pretraga je odustala dok smo čekali red - mjesto se mora osloboditi
            self.sem.release()
            raise

    async def __aexit__(self, *exc):
        self.sem.release()


_gates: dict[str, _Gate] = {}


def _gate(host: str) -> _Gate:
    if host not in _gates:
        _gates[host] = _Gate(HOST_LIMITS.get(host, DEFAULT_LIMIT))
    return _gates[host]


def _retry_after(response) -> float:
    value = response.headers.get("retry-after", "")
    return min(float(value), 300) if value.isdigit() else COOLDOWN_SECONDS


class PoliteSession(AsyncSession):
    async def request(self, method, url, *args, **kwargs):
        host = urlsplit(url).hostname or ""
        gate = _gate(host)
        gate.check(host)
        async with gate:
            gate.check(host)  # netko drugi je mogao dobiti 429 dok smo čekali red
            response = await super().request(method, url, *args, **kwargs)
        challenged = response.headers.get("cf-mitigated") == "challenge"  # Cloudflare traži provjeru preglednika
        if response.status_code == 429 or challenged:
            pause = CHALLENGE_SECONDS if challenged else _retry_after(response)
            gate.blocked_until = time.monotonic() + pause
            gate.check(host, response.status_code)
        return response


def session(impersonate: str = "chrome") -> AsyncSession:
    return PoliteSession(impersonate=impersonate, timeout=TIMEOUT)


def next_payload(html: str) -> str:
    """Next.js stranice šalju podatke kao self.__next_f.push([1,"..."]) - spoji sve u jedan string.
    Bez regexa jer stranice imaju i po nekoliko MB."""
    start_mark, end_mark = 'self.__next_f.push([1,"', '"])'
    parts, pos = [], 0
    while (start := html.find(start_mark, pos)) >= 0:
        start += len(start_mark)
        end = html.find(end_mark, start)
        while end > 0 and html[end - 1] == "\\" and html[end - 2] != "\\":  # preskoči escapane navodnike
            end = html.find(end_mark, end + 1)
        if end < 0:
            break
        try:
            parts.append(json.loads('"' + html[start:end] + '"'))
        except ValueError:
            pass
        pos = end
    return "".join(parts)


def text(resp) -> str:
    # curl_cffi zna krivo pogoditi encoding; stranice su gotovo sve UTF-8
    return resp.content.decode("utf-8", "replace")


def eur(s: str) -> float | None:
    """'1.234,56 €' / '€165.22' / 'EUR 207,21' -> float"""
    if s is None:
        return None
    s = str(s)
    m = re.search(r"\d[\d.,\s]*", s)
    if not m:
        return None
    n = m.group(0).strip().replace(" ", "").replace("\xa0", "")
    if "," in n and "." in n:
        n = n.replace(".", "").replace(",", ".") if n.rfind(",") > n.rfind(".") else n.replace(",", "")
    elif "," in n:
        n = n.replace(",", ".") if len(n.split(",")[-1]) <= 2 else n.replace(",", "")
    elif n.count(".") == 1 and len(n.split(".")[-1]) == 3:
        n = n.replace(".", "")  # 1.234 = tisuću
    try:
        return float(n)
    except ValueError:
        return None
