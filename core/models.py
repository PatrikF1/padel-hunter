from dataclasses import dataclass, field, asdict


@dataclass
class Offer:
    source: str              # npr. "vinted", "padelnuestro"
    source_name: str         # za prikaz, npr. "Vinted"
    id: str                  # jedinstven unutar izvora
    title: str
    url: str
    price: float             # cijena artikla u EUR
    condition: str = "new"   # "new" | "used"
    image: str = ""
    fees: float = 0.0        # npr. Vinted zaštita kupca
    shipping: float | None = None   # najjeftinija dostava u HR (EUR); None = nepoznato
    shipping_note: str = ""
    shipping_exact: bool = False    # True = stvarna cijena iz trgovine, False = procjena
    location: str = ""
    posted: str = ""
    is_auction: bool = False
    excluded: str = ""       # razlog zašto ponuda ne ide u rezultate (rasprodano, ne šalje u HR...)
    extra: dict = field(default_factory=dict)
    # popunjava matcher / ranking
    match: float = 0.0
    match_note: str = ""
    deal_pct: float = 0.0
    is_deal: bool = False

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"

    @property
    def total(self) -> float:
        return round(self.price + self.fees + (self.shipping or 0.0), 2)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total"] = self.total
        d["key"] = self.key
        return d
