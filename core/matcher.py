"""Prepoznavanje točnog modela reketa u naslovu oglasa.

match() vraća (ocjena, napomena):
  EXACT        1.0  točno taj model (i godina, ako je zadana)
  YEAR_MISSING 0.8  taj model, ali oglas ne navodi godinu
  VARIANT      0.5  varijanta istog modela (Comfort, Hybrid, Light, Women...) -> prikazuje se kao "varijante"
  NO_MATCH     0.0  nije to (drugi model / godina / brend, torba, tenisice...)

Rječnici ispod su jedino mjesto koje treba dopunjavati kad se pojavi novi brend ili oznaka varijante.
"""
import re
import unicodedata

EXACT, YEAR_MISSING, VARIANT, NO_MATCH = 1.0, 0.8, 0.5, 0.0
NOTE_YEAR_MISSING = "godina nije navedena"

# ---------- rječnici (normalizirano: mala slova, bez dijakritika) ----------
BRANDS = {
    "bullpadel", "nox", "adidas", "babolat", "head", "wilson", "siux", "starvie", "star", "vie",
    "dropshot", "drop", "shot", "varlion", "vibora", "black", "crown", "blackcrown", "kuikma",
    "oxdog", "royal", "joma", "lok", "akkeron", "dunlop", "prince", "tecnifibre", "puma", "asics",
    "enebe", "softee", "cartri", "harlem", "slazenger", "mystica", "kombat", "endless", "vairo",
    "jhayber", "orygen", "artengo", "sane", "volt", "hirostar", "virtufit", "zephyr", "middlemoon",
}
# brendovi čija pojava u naslovu jednoznačno znači "drugi proizvođač"
STRONG_BRANDS = {
    "bullpadel", "nox", "adidas", "babolat", "head", "wilson", "siux", "starvie", "dropshot", "varlion",
    "vibora", "kuikma", "oxdog", "akkeron", "dunlop", "prince", "puma", "asics", "enebe", "lok", "joma",
    "tecnifibre", "vairo", "endless", "virtufit",
}
# oznake varijanti - ako ih ima u naslovu, a nema u upitu, to je "slični" a ne točan model
VARIANTS = {
    "comfort", "hybrid", "light", "lite", "ctr", "ctrl", "control", "soft", "hard", "hrd",
    "junior", "jr", "kids", "kid", "nino", "kinder",
    "women", "woman", "womens", "mujer", "femme", "damen", "lady", "mulher", "donna", "femenina", "frau",
    "zenski", "zenska", "zene", "w",
    "pro", "plus", "max", "tour", "power", "attack", "elite", "team", "carbon", "edge", "ltd", "limited",
    "edition", "mx", "mexico", "master", "final", "premier", "geo", "legend", "luxury", "genius", "air",
    "vibe", "evo", "x", "s",
}
SHORT_VARIANTS = {"w", "s", "x"}  # računaju se samo odmah iza broja modela ("Vertex 04 W")
ACCESSORY = {
    "paletero", "paleteros", "bolsa", "mochila", "bag", "backpack", "torba", "ruksak", "sac", "tasche",
    "borsa", "thermobag", "zapatillas", "zapatilla", "schuhe", "shoes", "shoe", "tenisice", "patike",
    "chaussures", "scarpe", "buty", "vibram", "sneakers", "camiseta", "shirt", "tshirt", "majica", "polo",
    "shorts", "short", "falda", "skirt", "sudadera", "hoodie", "jacket", "jakna", "socks", "calcetines",
    "carape", "gorra", "cap", "visera", "munequera", "wristband", "grip", "overgrip", "grips", "pelotas",
    "balls", "ball", "loptice", "lopte", "cordaje", "funda", "cover", "navlaka", "futrola", "llavero",
    "keychain", "privjesak", "poster", "sticker", "naljepnica", "minipala", "mini", "antivibrador",
    "dampener", "tubo", "pantalon", "hlace",
}
RACKET = {"pala", "palas", "reket", "reketi", "racket", "racquet", "raqueta", "raquette", "schlager",
          "padelschlager", "rakieta", "racchetta", "paddle"}
PACK = {"pack", "paket", "set", "kit", "bundle"}
STOPWORDS = RACKET | {"padel", "za", "de", "the", "for"}  # ne moraju biti u naslovu
NEW_HINTS = {"novo", "novi", "nov", "nova", "zapakiran", "zapakirano", "neotpakiran", "nekoristen",
             "nekoristeno", "nerabljen", "nerabljeno", "etiketom", "new", "neu"}


# ---------- normalizacija ----------
def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def tokens(s: str) -> list[str]:
    """'Nox AT10 Genius 18K' -> ['nox', 'at', '10', 'genius', '18', 'k'];  '04' -> '4'."""
    s = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", _strip_accents(s))
    out = []
    for t in re.split(r"[^a-z0-9]+", s):
        if t:
            out.append(str(int(t)) if t.isdigit() and len(t) < 4 else t)
    return out


def years(toks: list[str]) -> set[int]:
    """2024 -> 2024;  dvoznamenkasti broj iza broja modela ('Vertex 04 25', '26V') -> 2025 / 2026."""
    found, prev_is_num = set(), False
    for t in toks:
        if t.isdigit():
            n = int(t)
            if 2015 <= n <= 2035:
                found.add(n)
            elif prev_is_num and 15 <= n <= 35:
                found.add(2000 + n)
        prev_is_num = t.isdigit()
    return found


def parse_query(q: str) -> dict:
    toks = tokens(q)
    query_years = years(toks)
    year_toks = {str(y) for y in query_years} | {str(y - 2000) for y in query_years}
    core = [t for t in toks if t not in year_toks and t not in BRANDS and t not in STOPWORDS]
    # broj koji slijedi riječ modela mora biti točan: "vertex 4" -> ("vertex", "4")
    pairs = [(core[i - 1], core[i]) for i in range(1, len(core)) if core[i].isdigit() and not core[i - 1].isdigit()]
    return {
        "raw": q, "tokens": toks, "core": core, "years": query_years, "pairs": pairs,
        "brand": next((t for t in toks if t in BRANDS), None),
    }


# ---------- provjere (svaka vraća razlog odbijanja ili None) ----------
def _number_after(toks: list[str], word: str) -> str | None:
    if word in toks:
        i = toks.index(word)
        return next((t for t in toks[i + 1:i + 3] if t.isdigit()), None)
    return None


def _reject_accessory(words: set[str], is_pack: bool) -> str | None:
    acc = words & ACCESSORY
    if acc and not (words & RACKET) and not is_pack:
        return "oprema: " + ", ".join(sorted(acc))
    return None


def _reject_brand(q: dict, words: set[str]) -> str | None:
    if q["brand"] and q["brand"] not in words:
        other = (words & STRONG_BRANDS) - {q["brand"]}
        if other:
            return "drugi brend: " + ", ".join(sorted(other))
    return None


def _reject_model(q: dict, toks: list[str]) -> str | None:
    missing = [t for t in q["core"] if t not in toks]
    if missing:
        return "nedostaje: " + " ".join(missing)
    for word, num in q["pairs"]:
        got = _number_after(toks, word)
        if got is not None and got != num:
            return f"drugi model: {word} {got}"
    return None


def _variants(q: dict, toks: list[str]) -> set[str]:
    """Oznake verzija u naslovu koje NISU u upitu. Uz opći popis koristi i oznake iz kataloga
    za taj model (q["version_words"], npr. Metalbone: zz, reserve, superlight...)."""
    known = VARIANTS | q.get("version_words", set())
    found = (set(toks) & known) - set(q["tokens"])
    for short in found & SHORT_VARIANTS:
        if not any(t == short and i > 0 and toks[i - 1].isdigit() for i, t in enumerate(toks)):
            found.discard(short)
    return found


# ---------- javno ----------
def match(q: dict, title: str, category: str = "") -> tuple[float, str]:
    toks = tokens(title)
    words = set(toks) | set(tokens(category))
    is_pack = bool(words & PACK)

    reason = _reject_accessory(words, is_pack) or _reject_brand(q, words) or _reject_model(q, toks)
    if reason:
        return NO_MATCH, reason

    score, notes = EXACT, []
    title_years = years(toks)
    if q["years"]:
        if title_years and not title_years & q["years"]:
            return NO_MATCH, "druga godina: " + ", ".join(map(str, sorted(title_years)))
        if not title_years:
            score, notes = YEAR_MISSING, [NOTE_YEAR_MISSING]
    elif title_years:
        notes.append("godina " + ", ".join(map(str, sorted(title_years))))

    if variants := _variants(q, toks):
        score = VARIANT
        notes.append("varijanta: " + ", ".join(sorted(variants)))
    if is_pack:
        notes.append("paket")
    return score, "; ".join(notes)


def looks_new(title: str) -> bool:
    """Njuškalo/Index nemaju polje stanja - 'NOVI, zapakiran' u naslovu znači novo."""
    return bool(set(tokens(title)) & NEW_HINTS)
