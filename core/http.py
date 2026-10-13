"""Zajednički HTTP klijent. curl_cffi imitira pravi preglednik (TLS otisak), pa nas stranice ne blokiraju."""
from curl_cffi.requests import AsyncSession

TIMEOUT = 10


def session(impersonate: str = "chrome") -> AsyncSession:
    return AsyncSession(impersonate=impersonate, timeout=TIMEOUT)


def text(resp) -> str:
    # curl_cffi zna krivo pogoditi encoding; stranice su gotovo sve UTF-8
    return resp.content.decode("utf-8", "replace")


def eur(s: str) -> float | None:
    """'1.234,56 €' / '€165.22' / 'EUR 207,21' -> float"""
    import re
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
