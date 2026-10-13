"""Primjeri prepoznavanja modela. Kad matcher pogriješi na stvarnom oglasu, dodaj taj naslov ovdje."""
import pytest

from core.matcher import (EXACT, NO_MATCH, NOTE_YEAR_MISSING, REASON_ACCESSORY, REASON_MISSING_WORDS,
                          REASON_NO_CONTEXT, REASON_NOT_FOR_SALE, REASON_OTHER_BRAND, REASON_OTHER_MODEL_NUMBER,
                          REASON_OTHER_SPORT, REASON_OTHER_YEAR, VARIANT, YEAR_MISSING, looks_new, match, parse_query,
                          tokens, worth_opening, years)


def score(query: str, title: str, category: str = "", details: str = "") -> float:
    return match(parse_query(query), title, category, details).score


# ---------- normalizacija i upit ----------
def test_tokens_normalize_numbers_and_accents():
    assert tokens("Vertex 04") == ["vertex", "4"]
    assert tokens("AT10 Genius 18K") == ["at", "10", "genius", "18", "k"]
    assert tokens("Galán") == ["galan"]


def test_query_parsing():
    wanted = parse_query("Bullpadel Vertex 04 2024")
    assert wanted.brand == "bullpadel"
    assert wanted.model_words == ["vertex", "4"]
    assert wanted.model_numbers == [("vertex", "4")]
    assert wanted.years == {2024}
    assert wanted.family == "vertex"
    assert parse_query("vertex 04 25").years == {2025}  # Bullpadel piše godinu kao "25"


def test_stopwords_not_required():
    assert score("padel reket nox at10 genius 18k", "NOX AT10 GENIUS 18K 2024 AGUSTIN TAPIA") == EXACT


# ---------- točan model ----------
@pytest.mark.parametrize("title", [
    "BULLPADEL VERTEX 04 2024",
    "Bullpadel Vertex 04 24",
    "Rakieta do padla Bullpadel Vertex 04 2024",
    "Vertex 04 2024 padel reket",               # bez brenda (često na Vintedu)
])
def test_exact_model(title):
    assert score("bullpadel vertex 04 2024", title) == EXACT


def test_year_missing_is_lower_but_kept():
    result = match(parse_query("bullpadel vertex 04 2024"), "BULLPADEL VERTEX 04")
    assert result.score == YEAR_MISSING and NOTE_YEAR_MISSING in result.note


def test_variant_in_query_is_exact():
    assert score("bullpadel vertex 04 comfort", "Bullpadel Vertex 04 Comfort 2024") == EXACT


def test_pack_with_bag_is_kept():
    result = match(parse_query("bullpadel vertex 04"), "PACK Bullpadel Vertex 04 + Paletero")
    assert result.score == EXACT and "paket" in result.note


# ---------- odbijeno (i ZAŠTO - kod razloga) ----------
@pytest.mark.parametrize("title, reason", [
    ("Bullpadel Vertex 03 2024", REASON_OTHER_MODEL_NUMBER),
    ("Bullpadel Vertex 05 2024", REASON_OTHER_MODEL_NUMBER),
    ("Bullpadel Vertex 04 2023", REASON_OTHER_YEAR),
    ("Bullpadel Hack 04 2024", REASON_MISSING_WORDS),
    ("Nox Vertex 04 2024", REASON_OTHER_BRAND),
    ("Paletero Bullpadel Vertex 04", REASON_ACCESSORY),
    ("Bullpadel Vertex Vibram 26V Black", REASON_ACCESSORY),   # tenisice
])
def test_rejected_with_reason(title, reason):
    result = match(parse_query("bullpadel vertex 04 2024"), title)
    assert (result.score, result.reason) == (NO_MATCH, reason)


def test_category_rejects_shoes():
    assert score("bullpadel vertex", "Bullpadel Vertex Pl Tour", "Padel shoes") == NO_MATCH


def test_test_rackets_for_rent_are_rejected():
    result = match(parse_query("adidas metalbone 2026"), "Metalbone 2026 Padelschläger Testschläger")
    assert result.reason == REASON_NOT_FOR_SALE


def test_decimal_models():
    assert score("adidas metalbone 3.4", "ADIDAS METALBONE 3.4 2025 ALE GALAN") == EXACT
    assert score("adidas metalbone 3.4", "Adidas Metalbone 3.3 2024") == NO_MATCH
    assert score("adidas metalbone 3.4", "ADIDAS METALBONE HRD+ 3.4 2025") == VARIANT


# ---------- varijante (druga verzija istog modela) ----------
@pytest.mark.parametrize("title", [
    "Bullpadel Vertex 04 Comfort 2024",
    "Bullpadel Vertex 04 W 2024",
    "BULLPADEL VERTEX 04 Woman 2024",
    "BULLPADEL VERTEX 04 25 MULHER",
    "Bullpadel Vertex 04 Hybrid",
])
def test_variants_are_similar_not_exact(title):
    assert score("bullpadel vertex 04", title) == VARIANT


def test_typo_variant_is_not_exact():
    assert score("adidas metalbone 2026", "Adidas Metalbone HDR+") == VARIANT


def test_youth_is_variant():
    assert score("adidas metalbone", "Adidas Metalbone Youth 3.4") == VARIANT


def test_other_generation_when_query_has_year_but_no_number():
    assert score("adidas metalbone 2026", "Pala Adidas Metalbone 3.3 Ale Galán") == VARIANT
    assert score("adidas metalbone 2026", "Adidas Metalbone 2026 Ale Galán") == EXACT
    assert score("adidas metalbone", "Adidas Metalbone 3.3") == EXACT          # bez godine: sve generacije
    assert score("bullpadel vertex 04 2024", "Bullpadel Vertex 04 2024") == EXACT


# ---------- dubinska provjera (opis oglasa) ----------
def test_description_confirms_version():
    assert score("adidas metalbone 3.3 2024", "Adidas Metalbone") == NO_MATCH   # samo naslov nije dovoljan
    assert score("adidas metalbone 3.3 2024", "Adidas Metalbone",
                 details="Prodajem Metalbone 3.3 iz 2024, malo korišten") == EXACT


def test_description_reveals_other_version():
    assert score("adidas metalbone 3.3", "Adidas Metalbone", details="Metalbone CTRL 3.3, okrugli oblik") == VARIANT


def test_description_year_only_confirms_never_rejects():
    assert score("adidas metalbone 3.3 2024", "Adidas Metalbone 3.3", details="kupljen 2023") == YEAR_MISSING


def test_description_bag_mention_is_not_accessory():
    assert score("adidas metalbone 3.3", "Adidas Metalbone 3.3", details="uz reket dolazi i torba") == EXACT


def test_worth_opening():
    wanted = parse_query("adidas metalbone 3.3 2024")
    assert worth_opening(wanted, "Adidas Metalbone", match(wanted, "Adidas Metalbone"))
    assert not worth_opening(wanted, "Bullpadel Vertex 04", match(wanted, "Bullpadel Vertex 04"))


# ---------- stanje ----------
def test_looks_new():
    assert looks_new("Bullpadel Vertex 04 W – NOVI, zapakiran")
    assert not looks_new("Bullpadel Vertex 04 korišten 2 mjeseca")


def test_year_after_model_name_is_not_a_model_number():
    # "Metalbone 2024" je možda baš 3.3 (model 2024) - ne smije biti odbijen kao "drugi model", nego provjeren opisom
    wanted = parse_query("adidas metalbone 3.3")
    result = match(wanted, "Adidas Metalbone 2024")
    assert result.reason == REASON_MISSING_WORDS and worth_opening(wanted, "Adidas Metalbone 2024", result)


# ---------- oprema za reket (štitnici, gripovi) ----------
def test_frame_protector_with_racket_word_is_accessory_when_cheap():
    wanted = parse_query("adidas metalbone 3.3")
    title = "Adidas Metalbone 3.3 - Adidas Metalbone 09 Stoßfänger Protektor Schläger"
    assert match(wanted, title, price=25.0).reason == REASON_ACCESSORY   # 15-40 € s riječju "reket" = oprema
    assert tokens("Stoßfänger") == ["stossfanger"]


def test_racket_sold_with_protector_is_kept():
    wanted = parse_query("bullpadel vertex 03")
    title = "Rakieta do padla Bullpadel Vertex 03 Maxi Sanchez + Protector"
    assert match(wanted, title, price=89.98).score == EXACT


def test_too_cheap_to_be_a_racket():
    from core.matcher import REASON_TOO_CHEAP
    assert match(parse_query("nox at10"), "Nox AT10 mini privjesak reket", price=7.5).reason == REASON_TOO_CHEAP


# ---------- stvarni naslovi na kojima je matcher griješio (pregled ~10 000 oglasa, 2026-10-13) ----------
def market_score(query: str, title: str, details: str = "") -> float:
    return match(parse_query(query), title, details=details, marketplace=True).score


@pytest.mark.parametrize("title, expected", [
    ("Bullpadel Hack 03 Comfort 24", {2024}),          # godina iza oznake verzije
    ("Bullpadel Vertex 04 Women 25 Pack", {2025}),
    ("Pala Bullpadel Vertex 04 W 25", {2025}),         # 'W' je oznaka verzije, ne dio broja modela
    ("Vertex PL Tour Final 26V", {2026}),
    ("Nox AT10 18K Alum", set()),                      # 18K je karbon, ne 2018
    ("Nox AT10 Genius 24K", set()),
    ("Royal Padel M27 Hybrid", set()),                 # M27 je model
    ("Head Speed Pro 38 mm", set()),
])
def test_two_digit_years(title, expected):
    assert years(tokens(title)) == expected


def test_marketplace_listing_must_mention_brand_or_padel():
    query = "head extreme pro 2025"
    assert market_score(query, "SanDisk Extreme Pro 128 GB micro sd") == NO_MATCH
    assert market_score(query, "X-fact Extreme Pro") == NO_MATCH
    assert market_score(query, "Padel reket Extreme Pro") == YEAR_MISSING     # bez brenda, ali je padel reket
    assert market_score(query, "Head Extreme Pro 2025") == EXACT
    assert market_score(query, "Extreme Pro 2025", details="Head padel reket, malo korišten") == EXACT
    assert score(query, "Extreme Pro 2025 Padelschläger") == EXACT            # trgovina: brend je u zasebnom polju
    assert market_score("bullpadel hack 03 2024", "HACK OUTBREAK PART 3 PS2") == NO_MATCH


def test_listing_without_context_is_opened_only_when_model_matches():
    wanted = parse_query("adidas metalbone 3.4 2025")
    no_context = match(wanted, "Metalbone 3.4", marketplace=True)
    assert no_context.reason == REASON_NO_CONTEXT and worth_opening(wanted, "Metalbone 3.4", no_context)
    wanted = parse_query("head extreme pro 2025")
    car = match(wanted, "Dacia Jogger 1.0 Extreme", marketplace=True)
    assert not worth_opening(wanted, "Dacia Jogger 1.0 Extreme", car)         # ne trošimo otvaranja na aute


def test_other_sports_rejected():
    assert match(parse_query("head extreme pro"), "HEAD Extreme Pro Pickleball Paddle").reason == REASON_OTHER_SPORT
    assert score("head extreme pro", "Head Extreme Pro tennis racket") == NO_MATCH
    assert score("head extreme pro", "Head Extreme Pro Padel Tennis Racket") == EXACT


def test_bag_is_not_a_racket_even_with_word_racket():
    assert match(parse_query("babolat technical viper"), "Babolat RH Pro Technical Viper Racket Bag").reason == REASON_ACCESSORY
    assert score("head extreme pro", "Head Pro Duffle L Extreme Bag", category="Rackets") == NO_MATCH
    assert score("bullpadel hack 03 2024", "Pala BULLPADEL HACK 03 2024 + Paletero BULLPADEL BPP-24014") == EXACT
    assert score("bullpadel hack 03", "PACK Hack 03 bag AVANT") == EXACT
    assert score("bullpadel hack 03", "Bullpadel Hack 03 reket sa torbom") == EXACT


def test_plus_in_model_name_is_not_a_bundle():
    assert "paket" not in match(parse_query("adidas metalbone hrd 3.4"), "ADIDAS METALBONE HRD+ 3.4 2025").note


def test_decimal_is_part_of_model_number():
    assert score("wilson bela pro v2", "Wilson Bela Pro V2.5 Padel Racket") == NO_MATCH
    assert score("wilson bela pro v2", "Wilson Bela Pro V2 Padel Racket") == EXACT
    assert score("wilson bela pro v2.5", "Pala Wilson Bela Pro V2.5 2025") == EXACT
    assert score("nox at10 genius 18k", "Nox AT10 12K Genius 18K") == EXACT   # '10 12' nije decimala


def test_test_racket_is_variant():
    result = match(parse_query("head extreme pro 2025"), "Pala de TEST Head Extreme Pro 2025")
    assert result.score == VARIANT and "testni" in result.note


def test_generation_checked_against_catalog():
    wanted = parse_query("babolat technical viper 2025")
    wanted.generations = {("2", "5"): {2025}, ("3", "0"): {2026}}             # inače puni engine iz kataloga
    assert match(wanted, "Babolat Technical Viper 2.5").score == EXACT        # katalog: 2.5 je model 2025
    assert match(wanted, "Babolat Technical Viper 3.0").reason == REASON_OTHER_YEAR
    assert match(wanted, "Babolat Technical Viper 3.1 Lebron").score == VARIANT   # katalog ne zna 3.1
    assert match(wanted, "Babolat Technical Viper 2.5 2025").score == EXACT
    assert match(wanted, "Babolat Technical Viper Juan Lebrón").score == YEAR_MISSING
