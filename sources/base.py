"""Zajedničko sučelje svih izvora.

Novi izvor = nova datoteka u sources/ koja definira listu `SOURCES` s jednim ili više `Source` objekata,
i jedan red u sources/__init__.py (MODULES). Vidi README -> "Dodavanje novog izvora".
"""
import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from core.models import Offer

MAX_PAGES = 5  # najviše stranica rezultata po izvoru i upitu


async def fetch_pages(get_page: Callable[[int], Awaitable[list]], full_page: int, max_pages: int = MAX_PAGES) -> list:
    """Stranica 1, a ako je puna (ima još rezultata), ostale stranice paralelno.
    Stranica koja ne uspije se preskače - bolje dio rezultata nego ništa."""
    first = await get_page(1)
    if len(first) < full_page or max_pages <= 1:
        return first
    rest = await asyncio.gather(*(get_page(n) for n in range(2, max_pages + 1)), return_exceptions=True)
    return first + [item for page in rest if isinstance(page, list) for item in page]

SearchFn = Callable[[str], Awaitable[list[Offer]]]
EnrichFn = Callable[[list[Offer]], Awaitable[None]]
DetailsFn = Callable[[Offer], Awaitable[str]]


@dataclass(frozen=True)
class Source:
    name: str                 # interni ključ, npr. "vinted"
    label: str                # za prikaz, npr. "Vinted"
    kind: str                 # "market" = oglasnik (provjera svake ~90 s) | "shop" = trgovina (svakih 15 min)
    search: SearchFn          # upit -> sve ponude (matcher filtrira kasnije)
    enrich: EnrichFn | None = None    # opcionalno: dodatni podaci (npr. stvarna dostava) za pogođene ponude
    details: DetailsFn | None = None  # opcionalno: tekst oglasa (opis, atributi) za dubinsku provjeru modela;
                                      # smije ažurirati offer.condition ako stranica oglasa navodi stanje
    details_max: int = 20     # najviše NOVIH opisa po pretrazi (već pročitani se pamte 24 h i ne broje se)
    timeout: int = 15         # s - koliko pretraga čeka izvor; više samo izvorima s budžetom zahtjeva (Vinted)
