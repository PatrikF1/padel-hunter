from core import catalog
from core.catalog import Racket, family_of
from core.matcher import match, parse_query


def racket(brand: str, title: str) -> Racket:
    return Racket(id=title, brand=brand, title=title, family=family_of(brand, title), year=None)


def setup_module():
    catalog.catalog.set([
        racket("Adidas", "ADIDAS METALBONE CTRL 3.4 2025"),
        racket("Adidas", "ADIDAS METALBONE CARBON CTRL 3.4 2025"),
        racket("Adidas", "ADIDAS METALBONE ZZ TEAM"),
        racket("Adidas", "ADIDAS METALBONE 3.4 2025 - ALE GALÁN"),
        racket("Nox", "NOX AT10 GENIUS 18K ALUM 2025"),
        racket("Black Crown", "BLACK CROWN PITON 13"),
    ], updated=0)


def test_family_of():
    assert family_of("Adidas", "ADIDAS METALBONE CTRL 3.4 2025") == "METALBONE"
    assert family_of("Vibor-A", "VIBOR-A BLACK MAMBA") == "BLACK"
    assert family_of("Black Crown", "BLACK CROWN PITON 13") == "PITON"


def test_version_words_from_catalog_ignore_players():
    words = catalog.version_words(parse_query("adidas metalbone 3.4"))
    assert {"ctrl", "carbon", "zz", "team"} <= words
    assert not {"ale", "galan"} & words


def test_version_words_multi_token_family():
    assert "alum" in catalog.version_words(parse_query("nox at10 genius 18k"))


def test_exact_version_with_catalog():
    pq = parse_query("adidas metalbone ctrl 3.4 2025")
    pq["version_words"] = catalog.version_words(pq)
    assert match(pq, "Metalbone CTRL 3.4 2025 Ale Galán")[0] == 1.0
    assert match(pq, "ADIDAS METALBONE ZZ CTRL 3.4 2025")[0] == 0.5   # zz poznat samo iz kataloga
    assert match(pq, "Adidas Metalbone Carbon CTRL 3.4 2025")[0] == 0.5


def test_merge_same_racket_from_two_sources():
    pn = Racket(id="pn:1", brand="Adidas", title="ADIDAS METALBONE SUPERLIGHT", family="METALBONE", year=2026,
                shape="Diamond", core="EVA", sources=["Padel Nuestro"])
    pf = Racket(id="pf:1", brand="Adidas", title="Adidas Metalbone Superlight 2026", family="METALBONE", year=2026,
                shape="Diamond", ratings={"power": 8.1}, sources=["Padelful"])
    older = Racket(id="pf:2", brand="Adidas", title="Adidas Metalbone 3.2 2023", family="METALBONE", year=2023,
                   sources=["Padelful"])
    merged = catalog.merge([[pn], [pf, older]])
    assert len(merged) == 2
    main = merged[0]
    assert main.core == "EVA" and main.ratings == {"power": 8.1}          # podaci iz oba izvora
    assert main.sources == ["Padel Nuestro", "Padelful"]


def test_identity_ignores_players_and_year_in_title():
    a = Racket(id="a", brand="Adidas", title="ADIDAS METALBONE 3.4 2025 - ALE GALÁN", family="METALBONE", year=2025)
    b = Racket(id="b", brand="Adidas", title="Adidas Metalbone 3.4 2025", family="METALBONE", year=2025)
    c = Racket(id="c", brand="Adidas", title="Adidas Metalbone CTRL 3.4 2025", family="METALBONE", year=2025)
    assert catalog.identity(a) == catalog.identity(b) != catalog.identity(c)
