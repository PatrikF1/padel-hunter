"""Zajednički HTTP klijent.

curl_cffi imitira pravi preglednik (TLS otisak). Uz to je klijent PRISTOJAN: prema svakoj stranici ide
ograničen broj istovremenih zahtjeva s razmakom, jer oglasnici (npr. Vinted) blokiraju prebrze klijente.
"""
import asyncio
import json
import re
import time
from urllib.parse import urlsplit

from curl_cffi.requests import AsyncSession

TIMEOUT = 10
# host -> (najviše istovremenih zahtjeva, najmanji razmak između zahtjeva u sekundama)
HOST_LIMITS = {
    "www.vinted.hr": (2, 0.6),
    "www.njuskalo.hr": (2, 0.4),
    "www.index.hr": (3, 0.2),
    "www.ebay.de": (1, 1.0),
}
DEFAULT_LIMIT = (6, 0.0)


class _Gate:
    def __init__(self, parallel: int, spacing: float):
        self.sem, self.spacing = asyncio.Semaphore(parallel), spacing
        self.lock, self.next_at = asyncio.Lock(), 0.0

    async def __aenter__(self):
        await self.sem.acquire()
        async with self.lock:  # razmak između početaka zahtjeva
            wait = self.next_at - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self.next_at = time.monotonic() + self.spacing

    async def __aexit__(self, *exc):
        self.sem.release()


_gates: dict[str, _Gate] = {}


def _gate(url: str) -> _Gate:
    host = urlsplit(url).hostname or ""
    if host not in _gates:
        _gates[host] = _Gate(*HOST_LIMITS.get(host, DEFAULT_LIMIT))
    return _gates[host]


class PoliteSession(AsyncSession):
    async def request(self, method, url, *args, **kwargs):
        async with _gate(url):
            return await super().request(method, url, *args, **kwargs)


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
