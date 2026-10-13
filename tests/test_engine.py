"""Pretraga kad izvor zakaže: pauza nakon 429, rezervni (spremljeni) rezultati i ograničen broj otvaranja oglasa."""
import asyncio
import time

import pytest

from core import engine, http
from core.matcher import parse_query
from core.models import Offer
from sources.base import Source


def offer(id: str, title: str, price: float = 150.0) -> Offer:
    return Offer(source="fake", source_name="Fake", id=id, title=title, url=f"https://fake.test/{id}", price=price,
                 condition="used", shipping=3.99)


def fake_source(search, details=None, details_max=20) -> Source:
    source = Source("fake", "Fake", "market", search, details=details, details_max=details_max)
    engine.health["fake"] = engine.SourceHealth("Fake", "market")
    engine._search_cache.clear()
    engine._details_cache.clear()
    return source


def run(source: Source, query: str, **kwargs) -> list[Offer]:
    return asyncio.run(engine.run_source(source, query, parse_query(query), **kwargs))


def test_failed_source_serves_recent_results_with_note():
    state = {"fail": False}

    async def search(_term):
        if state["fail"]:
            raise http.RateLimited("fake ograničava zahtjeve (429)")
        return [offer("1", "Adidas Metalbone 3.4 2025")]

    source = fake_source(search)
    assert len(run(source, "adidas metalbone 3.4 2025", use_cache=False)) == 1
    state["fail"] = True
    assert len(run(source, "adidas metalbone 3.4 2025", use_cache=False)) == 1   # iz spremljenih
    status = engine.health["fake"]
    assert status.ok and "429" in status.error and "rezultati stari" in status.error


def test_failed_source_without_saved_results_fails():
    async def search(_term):
        raise http.RateLimited("fake ograničava zahtjeve (429)")

    source = fake_source(search)
    with pytest.raises(http.RateLimited):
        run(source, "adidas metalbone 3.4 2025")
    assert engine.health["fake"].ok is False and engine.health["fake"].fails == 1


def test_only_details_max_new_listings_are_opened_cheapest_first():
    opened = []

    async def search(_term):
        return [offer(str(n), "Adidas Metalbone", price=100 + n) for n in range(10)]   # naslov bez verzije

    async def details(listing: Offer) -> str:
        opened.append(listing.id)
        return "Metalbone 3.4, model 2025"

    source = fake_source(search, details, details_max=3)
    found = run(source, "adidas metalbone 3.4 2025")
    assert sorted(opened) == ["0", "1", "2"]                      # tri najjeftinija
    assert sorted(o.id for o in found) == ["0", "1", "2"]         # samo njima je opis potvrdio verziju

    run(source, "adidas metalbone 3.4 2025")                      # sljedeća pretraga: pročitani su besplatni
    assert sorted(opened) == ["0", "1", "2", "3", "4", "5"]


def test_host_is_paused_after_429():
    gate = http._Gate(http.Limit(parallel=1, spacing=0.0))
    gate.check("fake.test")                                       # nije blokiran
    gate.blocked_until = time.monotonic() + 30
    with pytest.raises(http.RateLimited):
        gate.check("fake.test")


def test_request_budget_allows_burst_then_slows_down():
    gate = http._Gate(http.Limit(parallel=1, spacing=0.0, burst=3, refill=10.0))
    waits = [gate._budget_wait() for _ in range(5)]
    assert waits[:3] == [0.0, 0.0, 0.0]                           # nalet ide odmah
    assert 9 < waits[3] <= 10 and 19 < waits[4] <= 20             # zatim jedan zahtjev svakih 10 s


def test_cancelled_wait_releases_its_slot():
    """Pretraga koja odustane (timeout) dok čeka red ne smije zauvijek zauzeti mjesto prema toj stranici."""
    async def scenario() -> bool:
        gate = http._Gate(http.Limit(parallel=1, spacing=0.0, burst=1, refill=60.0))
        async with gate:
            pass                                                  # potroši budžet
        waiting = asyncio.create_task(gate.__aenter__())          # ovaj bi čekao 60 s
        await asyncio.sleep(0.01)
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)
        return not gate.sem.locked()

    assert asyncio.run(scenario())
