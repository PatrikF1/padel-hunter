import pytest

from core.matcher import NOTE_YEAR_MISSING, looks_new, match, parse_query, tokens


def score(query: str, title: str, category: str = "") -> float:
    return match(parse_query(query), title, category)[0]


def test_tokens_normalize_numbers_and_accents():
    assert tokens("Vertex 04") == ["vertex", "4"]
    assert tokens("AT10 Genius 18K") == ["at", "10", "genius", "18", "k"]
    assert tokens("Galán") == ["galan"]


def test_query_parsing():
    pq = parse_query("Bullpadel Vertex 04 2024")
    assert pq["brand"] == "bullpadel"
    assert pq["core"] == ["vertex", "4"]
    assert pq["years"] == {2024}
    assert parse_query("vertex 04 25")["years"] == {2025}  # Bullpadel piše godinu kao "25"


@pytest.mark.parametrize("title", [
    "BULLPADEL VERTEX 04 2024",
    "Bullpadel Vertex 04 24",
    "Rakieta do padla Bullpadel Vertex 04 2024",
    "Vertex 04 2024 padel reket",               # bez brenda (često na Vintedu)
])
def test_exact_model(title):
    assert score("bullpadel vertex 04 2024", title) == 1.0


@pytest.mark.parametrize("title, reason", [
    ("Bullpadel Vertex 03 2024", "drugi broj modela"),
    ("Bullpadel Vertex 05 2024", "drugi broj modela"),
    ("Bullpadel Vertex 04 2023", "druga godina"),
    ("Bullpadel Hack 04 2024", "drugi model"),
    ("Nox Vertex 04 2024", "drugi brend"),
    ("Paletero Bullpadel Vertex 04", "torba"),
    ("Bullpadel Vertex Vibram 26V Black", "tenisice"),
])
def test_rejected(title, reason):
    assert score("bullpadel vertex 04 2024", title) == 0.0, reason


def test_year_missing_is_lower_but_kept():
    s, note = match(parse_query("bullpadel vertex 04 2024"), "BULLPADEL VERTEX 04")
    assert s == 0.8 and NOTE_YEAR_MISSING in note


@pytest.mark.parametrize("title", [
    "Bullpadel Vertex 04 Comfort 2024",
    "Bullpadel Vertex 04 W 2024",
    "BULLPADEL VERTEX 04 Woman 2024",
    "BULLPADEL VERTEX 04 25 MULHER",
    "Bullpadel Vertex 04 Hybrid",
])
def test_variants_are_similar_not_exact(title):
    assert score("bullpadel vertex 04", title) == 0.5


def test_variant_in_query_is_exact():
    assert score("bullpadel vertex 04 comfort", "Bullpadel Vertex 04 Comfort 2024") == 1.0


def test_pack_with_bag_is_kept():
    s, note = match(parse_query("bullpadel vertex 04"), "PACK Bullpadel Vertex 04 + Paletero")
    assert s == 1.0 and "paket" in note


def test_decimal_models():
    assert score("adidas metalbone 3.4", "ADIDAS METALBONE 3.4 2025 ALE GALAN") == 1.0
    assert score("adidas metalbone 3.4", "Adidas Metalbone 3.3 2024") == 0.0
    assert score("adidas metalbone 3.4", "ADIDAS METALBONE HRD+ 3.4 2025") == 0.5


def test_category_rejects_shoes():
    assert score("bullpadel vertex", "Bullpadel Vertex Pl Tour", "Padel shoes") == 0.0


def test_looks_new():
    assert looks_new("Bullpadel Vertex 04 W – NOVI, zapakiran")
    assert not looks_new("Bullpadel Vertex 04 korišten 2 mjeseca")


def test_stopwords_not_required():
    assert score("padel reket nox at10 genius 18k", "NOX AT10 GENIUS 18K 2024 AGUSTIN TAPIA") == 1.0
