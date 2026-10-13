"""Offer = jedna ponuda (oglas ili proizvod u trgovini). Sve što izvori vrate i što UI prikazuje je Offer."""
from dataclasses import asdict, dataclass


@dataclass
class Offer:
    # --- popunjava izvor (sources/*.py) ---
    source: str              # interni ključ izvora, npr. "vinted", "padelnuestro"
    source_name: str         # za prikaz, npr. "Vinted"
    id: str                  # jedinstven unutar izvora
    title: str
    url: str
    price: float             # cijena artikla u EUR
    condition: str = "new"   # "new" | "used"
    image: str = ""
    category: str = ""       # kategorija iz trgovine (npr. "Palas", "Padel shoes") - pomaže odbaciti opremu
    fees: float = 0.0        # npr. Vinted zaštita kupca
    shipping: float | None = None   # najjeftinija dostava u HR (EUR); None = nepoznato
    shipping_note: str = ""         # odakle je cijena dostave (cjenik, košarica, procjena...)
    shipping_exact: bool = False    # True = stvarna cijena iz trgovine, False = procjena
    location: str = ""
    posted: str = ""         # kad je oglas objavljen (ISO datum), ako izvor to zna
    is_auction: bool = False
    excluded: str = ""       # razlog zašto ponuda NE ide u rezultate (rasprodano, ne šalje u HR...)

    # --- popunjava engine (core/engine.py) ---
    match: float = 0.0       # ocjena iz core/matcher.py (EXACT / YEAR_MISSING / VARIANT / NO_MATCH)
    match_note: str = ""     # zašto takva ocjena, npr. "varijanta: ctrl"
    match_reason: str = ""   # kod razloga odbijanja (matcher.REASON_*), prazno ako nije odbijena
    deal_pct: float = 0.0    # koliko je ispod uobičajene cijene (0.35 = 35 %)
    is_deal: bool = False    # "apsurdna" cijena

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"

    @property
    def total(self) -> float:
        """Ukupno za kupca: cijena + naknade + dostava u HR."""
        return round(self.price + self.fees + (self.shipping or 0.0), 2)

    def to_dict(self) -> dict:
        return {**asdict(self), "total": self.total, "key": self.key}
