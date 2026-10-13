"""Najjeftinija dostava u HR.

- Shopify trgovine: STVARNA cijena (košarica -> shipping_rates za Zagreb 10000), vidi sources/shopify.py
- eBay: stvarna cijena iz oglasa (eBay prepoznaje HR kao odredište)
- ostale trgovine: cjenik s njihovih stranica (provjereno 2026-10-13, izvori u README)
- oglasnici (Vinted / Njuškalo / Index): procjena za paketomat, jasno označena
"""
import time

from .http import session

# (prag_od_EUR, cijena_dostave) - prvi red čiji je prag <= vrijednost narudžbe
SHOP_RULES = {
    # padelnuestro.com/int/shipping-and-delivery - "Central & Eastern Europe", HR naveden
    "padelnuestro": {"tiers": [(200, 9.95), (100, 14.95), (0, 22.95)], "exact": True,
                     "note": "cjenik trgovine za HR"},
    # time2padel.com/en/content/1-shipping-policy - HR ima svoj red
    "time2padel": {"tiers": [(200, 9.95), (100, 14.95), (0, 22.95)], "exact": True,
                   "note": "cjenik trgovine za HR"},
    # zonadepadel.com - "besplatno u Europu od 150 EUR", HR nije izričito naveden
    "zonadepadel": {"tiers": [(150, 0.0), (0, 14.95)], "exact": False,
                    "note": "procjena: besplatno od 150 € za EU, provjeri u košarici"},
    # padelreference.com - Schengen, cijena za HR nije objavljena
    "padelreference": {"tiers": [(0, 15.0)], "exact": False,
                       "note": "procjena: trgovina ne objavljuje cijenu za HR"},
    # stockpadel.com/en/content/18-shipping-costs- (UPS, EU)
    "stockpadel": {"tiers": [(400, 4.95), (200, 9.95), (100, 14.95), (0, 19.95)], "exact": True,
                   "note": "cjenik trgovine za EU"},
    "areapadel": {"tiers": [(0, 14.95)], "exact": False, "note": "procjena: UPS, cijena vidljiva u košarici"},
    "ipontennis": {"tiers": [(0, 14.95)], "exact": False, "note": "procjena: cijena vidljiva u košarici"},
    # padel.tienda/envios - Hrvatska navedena
    "padeltienda": {"tiers": [(390, 0.0), (0, 34.95)], "exact": True, "note": "cjenik trgovine za HR"},
    # todopadel.shop/envios - Europa, po težini, od 8,47 € + PDV
    "todopadel": {"tiers": [(0, 10.59)], "exact": False, "note": "procjena: od 8,47 € + PDV, ovisi o težini"},
    # hrvatske trgovine - domaća dostava
    "sportivo": {"tiers": [(100, 0.0), (0, 4.99)], "exact": False, "note": "HR trgovina: besplatno od 100 €, inače procjena"},
    "vidmarsport": {"tiers": [(100, 0.0), (0, 4.99)], "exact": False, "note": "HR trgovina: besplatno od 100 €, inače procjena"},
    "tenniszone": {"tiers": [(129, 0.0), (0, 4.99)], "exact": False, "note": "HR trgovina: besplatno od 129 €, inače procjena"},
    "teniswil": {"tiers": [(0, 4.99)], "exact": False, "note": "HR trgovina: procjena domaće dostave"},
    "marines": {"tiers": [(0, 4.99)], "exact": False, "note": "HR trgovina: procjena domaće dostave"},
}

MARKETPLACE_EST = {
    "vinted": (3.99, "procjena: najjeftiniji paketomat, točno na Vintedu pri kupnji"),
    "njuskalo": (3.50, "procjena: paketomat (BOX NOW) po dogovoru ili osobno preuzimanje"),
    "index": (3.50, "procjena: paketomat (BOX NOW) po dogovoru ili osobno preuzimanje"),
}


def shop_shipping(shop: str, order_value: float) -> tuple[float | None, str, bool]:
    r = SHOP_RULES.get(shop)
    if not r:
        return None, "dostava nepoznata", False
    for threshold, cost in r["tiers"]:
        if order_value >= threshold:
            return cost, r["note"], r["exact"]
    return None, "dostava nepoznata", False


def marketplace_shipping(source: str) -> tuple[float, str, bool]:
    cost, note = MARKETPLACE_EST[source]
    return cost, note, False


# ---- tečaj (neke Shopify trgovine naplaćuju HR kupcima u USD/GBP) ----
FX_TTL = 12 * 3600
_fx: dict[str, tuple[float, float]] = {"USD": (0.0, 0.86), "GBP": (0.0, 1.15)}  # valuta -> (vrijeme, tečaj u EUR)


async def to_eur(amount: float, currency: str) -> float:
    currency = (currency or "EUR").upper()
    if currency == "EUR":
        return round(amount, 2)
    fetched_at, rate = _fx.get(currency, (0.0, 1.0))
    if time.time() - fetched_at > FX_TTL:
        try:
            async with session() as client:
                response = await client.get("https://api.frankfurter.app/latest", params={"from": currency, "to": "EUR"})
                rate = float(response.json()["rates"]["EUR"])
                _fx[currency] = (time.time(), rate)
        except Exception:
            pass  # zadrži zadnji poznati tečaj
    return round(amount * rate, 2)
