"""Prepoznavanje točnog modela reketa u naslovu (i opisu) oglasa.

Tijek:  parse_query("Adidas Metalbone CTRL 3.4 2025")  ->  WantedRacket  (što tražimo)
        match(wanted, naslov_oglasa)                    ->  MatchResult   (koliko oglas odgovara i zašto)

Ocjene (MatchResult.score):
  EXACT        1.0  točno taj model (i godina, ako je zadana)
  YEAR_MISSING 0.8  taj model, ali oglas ne navodi godinu        -> i dalje "točan model"
  VARIANT      0.5  druga verzija istog modela (CTRL, Carbon...) -> "varijanta"
  NO_MATCH     0.0  nije to (drugi model / godina / brend, torba...) -> ne prikazuje se

Kad oglas "ne bi trebao" ili "bi trebao" proći: pogledaj MatchResult.note (zašto), a rječnike ispod
dopuni (novi brend, oznaka verzije, oprema). Svaku izmjenu pokrij primjerom u tests/test_matcher.py.
Brzo testiranje bez kodiranja: http://127.0.0.1:8777/api/debug/match?q=...&title=...
"""
import re
import unicodedata
from dataclasses import dataclass, field

EXACT, YEAR_MISSING, VARIANT, NO_MATCH = 1.0, 0.8, 0.5, 0.0
NOTE_YEAR_MISSING = "godina nije navedena"
NOTE_FROM_DETAILS = "✓ potvrđeno iz opisa oglasa"

# kodovi razloga odbijanja (MatchResult.reason) - stabilni, za kod; MatchResult.note je tekst za ljude
REASON_NOT_FOR_SALE = "not_for_sale"
REASON_ACCESSORY = "accessory"
REASON_TOO_CHEAP = "too_cheap"
REASON_OTHER_BRAND = "other_brand"
REASON_MISSING_WORDS = "missing_words"
REASON_OTHER_MODEL_NUMBER = "other_model_number"
REASON_OTHER_YEAR = "other_year"

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
# oznake verzija - ako ih ima u oglasu, a nema u upitu, to je "varijanta", a ne točan model
VARIANTS = {
    "comfort", "hybrid", "light", "lite", "ctr", "ctrl", "control", "soft", "hard", "hrd",
    "junior", "jr", "kids", "kid", "nino", "kinder", "youth", "jugend", "enfant", "djecji", "decji",
    "women", "woman", "womens", "mujer", "femme", "damen", "lady", "mulher", "donna", "femenina", "frau",
    "zenski", "zenska", "zene", "w",
    "pro", "plus", "max", "tour", "power", "attack", "elite", "team", "carbon", "edge", "ltd", "limited",
    "edition", "mx", "mexico", "master", "final", "premier", "geo", "legend", "luxury", "genius", "air",
    "vibe", "evo", "x", "s",
}
# česti tipfeleri oznaka verzija u oglasima (hdr = hrd, crtl = ctrl...) - i oni znače "druga verzija"
VARIANTS |= {"hdr", "crtl", "cntrl", "contol", "hibrid", "hybird", "confort", "comfor"}
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
# izrazita oprema ZA reket - naslov često sadrži i "reket" ("Protektor für Metalbone Schläger"), pa ovdje
# odlučuje cijena: ispod ACCESSORY_MAX_PRICE to je oprema, iznad je reket koji dolazi s tom opremom
STRONG_ACCESSORY = {"protector", "protektor", "protectores", "stossfanger", "bumper", "schutz", "schutzband",
                    "titanskin", "skin", "overgrip", "grip", "grips", "funda", "cover", "hulle", "navlaka", "futrola"}
ACCESSORY_MAX_PRICE = 40.0   # EUR
MIN_RACKET_PRICE = 15.0      # EUR - ispod ovoga nijedan pravi reket (ni rabljen) - privjesci, mini reketi...
RACKET = {"pala", "palas", "reket", "reketi", "racket", "racquet", "raqueta", "raquette", "schlager",
          "padelschlager", "rakieta", "racchetta", "paddle"}
PACK = {"pack", "paket", "set", "kit", "bundle"}
# testni reketi za posudbu (npr. Padel-Point "Testschläger") - ne prodaju se
NOT_FOR_SALE = {"testschlager", "probeschlager", "testracket", "testracquet", "demo", "alquiler", "rental",
                "verleih", "mietschlager", "najam"}
STOPWORDS = RACKET | {"padel", "za", "de", "the", "for"}  # ne moraju biti u naslovu
NEW_HINTS = {"novo", "novi", "nov", "nova", "zapakiran", "zapakirano", "neotpakiran", "nekoristen",
             "nekoristeno", "nerabljen", "nerabljeno", "etiketom", "new", "neu"}


# ---------- normalizacija teksta ----------
def _strip_accents(text: str) -> str:
    text = (text or "").replace("ß", "ss").replace("ẞ", "SS")  # "Stoßfänger" -> "stossfanger"
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def tokens(text: str) -> list[str]:
    """Normalizirane riječi: 'Nox AT10 Genius 18K' -> ['nox', 'at', '10', 'genius', '18', 'k'];  '04' -> '4'."""
    text = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", _strip_accents(text))
    words = []
    for word in re.split(r"[^a-z0-9]+", text):
        if word:
            words.append(str(int(word)) if word.isdigit() and len(word) < 4 else word)
    return words


def years(words: list[str]) -> set[int]:
    """2024 -> 2024;  dvoznamenkasti broj iza broja modela ('Vertex 04 25', '26V') -> 2025 / 2026."""
    found, previous_is_number = set(), False
    for word in words:
        if word.isdigit():
            n = int(word)
            if 2015 <= n <= 2035:
                found.add(n)
            elif previous_is_number and 15 <= n <= 35:
                found.add(2000 + n)
        previous_is_number = word.isdigit()
    return found


# ---------- što tražimo ----------
@dataclass
class WantedRacket:
    """Rastavljen upit. Primjer za 'Adidas Metalbone CTRL 3.4 2025':
    brand='adidas', model_words=['metalbone','ctrl','3','4'], model_numbers=[('ctrl','3')], years={2025}"""
    raw: str
    words: list[str]                      # sve normalizirane riječi upita
    brand: str | None                     # prvi poznati brend iz upita
    model_words: list[str]                # riječi koje MORAJU biti u oglasu (bez brenda, godine, "padel reket")
    model_numbers: list[tuple[str, str]]  # broj iza riječi mora biti točan: ("vertex", "4") -> Vertex 04, ne 03
    years: set[int]
    version_words: set[str] = field(default_factory=set)  # oznake verzija tog modela iz kataloga (puni engine)

    @property
    def family(self) -> str:
        """Naziv modela, npr. 'metalbone' (prva riječ modela)."""
        return self.model_words[0] if self.model_words else ""


def parse_query(query: str) -> WantedRacket:
    words = tokens(query)
    query_years = years(words)
    year_words = {str(y) for y in query_years} | {str(y - 2000) for y in query_years}
    model_words = [w for w in words if w not in year_words and w not in BRANDS and w not in STOPWORDS]
    model_numbers = [(model_words[i - 1], model_words[i]) for i in range(1, len(model_words))
                     if model_words[i].isdigit() and not model_words[i - 1].isdigit()]
    return WantedRacket(raw=query, words=words, brand=next((w for w in words if w in BRANDS), None),
                        model_words=model_words, model_numbers=model_numbers, years=query_years)


# ---------- rezultat ----------
@dataclass(frozen=True)
class MatchResult:
    score: float       # EXACT / YEAR_MISSING / VARIANT / NO_MATCH
    note: str = ""     # objašnjenje za ljude, npr. "varijanta: ctrl" ili "nedostaje: 3 4"
    reason: str = ""   # kod razloga odbijanja (REASON_*), prazno ako oglas nije odbijen


# ---------- provjere (svaka vraća MatchResult odbijanja ili None) ----------
def _is_year(word: str) -> bool:
    return len(word) == 4 and word.isdigit() and 2015 <= int(word) <= 2035


def _number_after(words: list[str], word: str) -> str | None:
    """Broj modela iza riječi ('vertex 04' -> '4'). Godina nije broj modela ('metalbone 2024' -> None)."""
    if word in words:
        i = words.index(word)
        return next((w for w in words[i + 1:i + 3] if w.isdigit() and not _is_year(w)), None)
    return None


def _reject_not_racket(title_words: set[str], is_pack: bool, price: float | None) -> MatchResult | None:
    if test := title_words & NOT_FOR_SALE:
        return MatchResult(NO_MATCH, "testni reket / najam: " + ", ".join(sorted(test)), REASON_NOT_FOR_SALE)
    if price is not None and price < MIN_RACKET_PRICE:
        return MatchResult(NO_MATCH, f"prejeftino za reket ({price:.2f} €) - vjerojatno oprema", REASON_TOO_CHEAP)
    accessories = title_words & ACCESSORY
    if accessories and not (title_words & RACKET) and not is_pack:
        return MatchResult(NO_MATCH, "oprema: " + ", ".join(sorted(accessories)), REASON_ACCESSORY)
    strong = title_words & STRONG_ACCESSORY
    if strong and not is_pack and price is not None and price < ACCESSORY_MAX_PRICE:
        return MatchResult(NO_MATCH, f"oprema za reket: {', '.join(sorted(strong))} ({price:.2f} €)", REASON_ACCESSORY)
    return None


def _reject_brand(wanted: WantedRacket, title_words: set[str]) -> MatchResult | None:
    if wanted.brand and wanted.brand not in title_words:
        other = (title_words & STRONG_BRANDS) - {wanted.brand}
        if other:
            return MatchResult(NO_MATCH, "drugi brend: " + ", ".join(sorted(other)), REASON_OTHER_BRAND)
    return None


def _reject_model(wanted: WantedRacket, words: list[str]) -> MatchResult | None:
    # prvo broj modela - "drugi model: vertex 3" je jasnije od "nedostaje: 4"
    for word, number in wanted.model_numbers:
        found = _number_after(words, word)
        if found is not None and found != number:
            return MatchResult(NO_MATCH, f"drugi model: {word} {found}", REASON_OTHER_MODEL_NUMBER)
    missing = [w for w in wanted.model_words if w not in words]
    if missing:
        return MatchResult(NO_MATCH, "nedostaje: " + " ".join(missing), REASON_MISSING_WORDS)
    return None


def _extra_versions(wanted: WantedRacket, words: list[str]) -> set[str]:
    """Oznake verzija u oglasu koje NISU u upitu (opći popis VARIANTS + oznake iz kataloga za taj model)."""
    found = (set(words) & (VARIANTS | wanted.version_words)) - set(wanted.words)
    for short in found & SHORT_VARIANTS:
        if not any(w == short and i > 0 and words[i - 1].isdigit() for i, w in enumerate(words)):
            found.discard(short)
    return found


def _other_generation(wanted: WantedRacket, words: list[str]) -> str | None:
    """Upit 'Metalbone 2026' (godina, bez broja) vs oglas 'Metalbone 3.3' -> druga generacija (2024).
    Vrijedi samo kad upit ima godinu, a nema nikakav broj modela (inače to provjerava _reject_model)."""
    if not wanted.years or not wanted.family or any(w.isdigit() for w in wanted.model_words):
        return None
    if wanted.family not in words:
        return None
    i = words.index(wanted.family)
    following = words[i + 1] if i + 1 < len(words) else ""
    return f"{wanted.family} {following}" if following.isdigit() and int(following) < 15 else None


# ---------- javno ----------
def match(wanted: WantedRacket, title: str, category: str = "", details: str = "",
          price: float | None = None) -> MatchResult:
    """Koliko oglas odgovara traženom reketu. price (EUR, bez dostave) pomaže razlikovati reket od opreme.

    details = opis/atributi sa stranice oglasa (dubinska provjera). Opis smije DOPUNITI naslov
    (naslov 'Adidas Metalbone', opis '... Metalbone 3.3 2024'), ali torba/brend se gledaju samo u naslovu,
    a godina iz opisa samo potvrđuje (opis 'kupljen 2023' ne odbacuje oglas)."""
    title_words = tokens(title)
    all_words = title_words + tokens(details)
    title_and_category = set(title_words) | set(tokens(category))
    is_pack = bool(title_and_category & PACK)

    rejected = (_reject_not_racket(title_and_category, is_pack, price) or _reject_brand(wanted, title_and_category)
                or _reject_model(wanted, all_words))
    if rejected:
        return rejected

    score, notes = EXACT, []
    title_years = years(title_words)
    if wanted.years:
        if title_years and not title_years & wanted.years:
            return MatchResult(NO_MATCH, "druga godina: " + ", ".join(map(str, sorted(title_years))),
                               REASON_OTHER_YEAR)
        if not title_years and not years(tokens(details)) & wanted.years:
            score, notes = YEAR_MISSING, [NOTE_YEAR_MISSING]
    elif title_years:
        notes.append("godina " + ", ".join(map(str, sorted(title_years))))

    if versions := _extra_versions(wanted, all_words):
        score = VARIANT
        notes.append("varijanta: " + ", ".join(sorted(versions)))
    if generation := _other_generation(wanted, all_words):
        score = VARIANT
        notes.append(f"druga generacija: {generation}")
    if is_pack:
        notes.append("paket")
    return MatchResult(score, "; ".join(notes))


def worth_opening(wanted: WantedRacket, title: str, result: MatchResult) -> bool:
    """Isplati li se otvoriti oglas i pročitati opis: naslov spominje model, ali mu fali verzija/broj/godina."""
    if not wanted.family or wanted.family not in tokens(title):
        return False
    return result.score == YEAR_MISSING or result.reason == REASON_MISSING_WORDS


def looks_new(title: str) -> bool:
    """Njuškalo/Index nemaju polje stanja - 'NOVI, zapakiran' u naslovu znači novo."""
    return bool(set(tokens(title)) & NEW_HINTS)
