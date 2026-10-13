import pytest

from core import engine
from core.http import eur
from core.models import Offer
from core.shipping import shop_shipping


@pytest.mark.parametrize("raw, value", [
    ("120 €", 120.0), ("EUR 207,21", 207.21), ("€165.22", 165.22), ("1.234,56 €", 1234.56),
    ("1,234.56", 1234.56), ("27,00\xa0€", 27.0), ("+ ca. EUR 28,87 Versand", 28.87), ("", None),
])
def test_eur(raw, value):
    assert eur(raw) == value


def test_shop_shipping_tiers():
    assert shop_shipping("padelnuestro", 99)[0] == 22.95
    assert shop_shipping("padelnuestro", 150)[0] == 14.95
    assert shop_shipping("padelnuestro", 250)[0] == 9.95
    assert shop_shipping("zonadepadel", 160)[0] == 0.0
    assert shop_shipping("nepoznata", 100)[0] is None


def offer(total: float, condition="new", match=1.0) -> Offer:
    return Offer(source="t", source_name="T", id=str(total), title="x", url="", price=total,
                 shipping=0.0, condition=condition, match=match)


def test_total_includes_fees_and_shipping():
    o = Offer(source="t", source_name="T", id="1", title="x", url="", price=100, fees=5.5, shipping=3.99)
    assert o.total == 109.49


def test_reference_prefers_new_offers():
    offers = [offer(200), offer(220), offer(60, "used")]
    assert engine.reference_price(offers) == 210


def test_deals_marked_against_reference():
    offers = [offer(200), offer(220), offer(100, "used"), offer(50, match=0.5)]
    engine.mark_deals(offers, engine.reference_price(offers))
    assert [o.is_deal for o in offers] == [False, False, True, False]  # varijante se ne označavaju


def test_rank_exact_first_then_cheapest():
    a, b, c = offer(150), offer(100, match=0.5), offer(120)
    assert engine.rank([a, b, c]) == [c, a, b]


def test_search_terms_strip_year_and_add_brandless_for_markets():
    assert engine.search_terms("Bullpadel Vertex 04 2024", "shop") == ["Bullpadel Vertex 04"]
    assert engine.search_terms("Bullpadel Vertex 04 2024", "market") == ["Bullpadel Vertex 04", "Vertex 04", "Vertex"]
    assert engine.search_terms("nox at10", "market") == ["nox at10", "at10"]  # bez duplikata
    assert engine.search_terms("padel reket Nox AT10", "shop") == ["Nox AT10"]


def test_polite_gate_limits_parallel_requests_and_spacing():
    import asyncio
    import time
    from core.http import _Gate

    async def run():
        gate, active, peak, starts = _Gate(parallel=2, spacing=0.05), 0, 0, []

        async def job():
            nonlocal active, peak
            async with gate:
                starts.append(time.monotonic())
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(*(job() for _ in range(5)))
        return peak, starts

    peak, starts = asyncio.run(run())
    assert peak <= 2
    assert all(b - a >= 0.045 for a, b in zip(starts, starts[1:]))


def test_access_trusts_localhost_and_tailscale_only():
    from core import access
    assert access.is_trusted("127.0.0.1") and access.is_trusted("100.101.102.103")
    assert not access.is_trusted("192.168.1.20") and not access.is_trusted("8.8.8.8") and not access.is_trusted(None)
    assert not access.allowed("192.168.1.20", None, "pogresan-kljuc")
    assert access.allowed("192.168.1.20", access.key(), None)
