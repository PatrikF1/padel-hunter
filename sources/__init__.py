"""Registar izvora. Novi izvor: dodaj modul u MODULES (modul mora imati listu SOURCES)."""
from . import doofinder, ebay, index_oglasi, njuskalo, prestashop, shopify, vinted
from .base import Source

MODULES = [vinted, njuskalo, index_oglasi, ebay, shopify, doofinder, prestashop]

SOURCES: list[Source] = [src for m in MODULES for src in m.SOURCES]
BY_NAME: dict[str, Source] = {s.name: s for s in SOURCES}

assert len(BY_NAME) == len(SOURCES), "dva izvora imaju isti name"
