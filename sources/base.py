"""Zajedničko sučelje svih izvora.

Novi izvor = nova datoteka u sources/ koja definira listu `SOURCES` s jednim ili više `Source` objekata,
i jedan red u sources/__init__.py (MODULES). Vidi README -> "Dodavanje novog izvora".
"""
from dataclasses import dataclass
from typing import Awaitable, Callable

from core.models import Offer

SearchFn = Callable[[str], Awaitable[list[Offer]]]
EnrichFn = Callable[[list[Offer]], Awaitable[None]]


@dataclass(frozen=True)
class Source:
    name: str                 # interni ključ, npr. "vinted"
    label: str                # za prikaz, npr. "Vinted"
    kind: str                 # "market" = oglasnik (provjera svake ~90 s) | "shop" = trgovina (svakih 15 min)
    search: SearchFn          # upit -> sve ponude (matcher filtrira kasnije)
    enrich: EnrichFn | None = None  # opcionalno: dohvati dodatne podatke (npr. stvarnu dostavu) samo za pogođene ponude
