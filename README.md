# 🎾 Padel Hunter

Upišeš model padel reketa, a alat za ~5 s pretraži oglasnike i trgovine i pokaže **sve ponude tog modela**,
nove i rabljene. Sortirane su po **ukupnoj cijeni s najjeftinijom dostavom u Hrvatsku**, a apsurdno jeftine
ponude su označene. U pozadini prati odabrane modele i šalje **Telegram poruku** čim se pojavi nova dobra ponuda.

## Pokretanje

Dvoklik na **`start.bat`**. Prvi put instalira sve potrebno, zatim otvara http://127.0.0.1:8777.

Potreban je Python 3.11+. Ručno pokretanje:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py
```

Provjera iz terminala (radi li svaki izvor):

```bash
.venv\Scripts\python check.py "nox at10 genius 18k 2024"
```

Testovi: `.venv\Scripts\python -m pip install -r requirements-dev.txt`, pa `.venv\Scripts\python -m pytest`.

## Odabir točne verzije (katalog)

Na vrhu stranice je **katalog s ~2200 reketa, modeli 2020–2027**. Osvježava se svaka 3 dana iz dva izvora
koji se spajaju (isti reket iz oba izvora postaje jedan zapis):

| izvor | što daje |
|---|---|
| Padel Nuestro | ~800 aktualnih reketa: oblik, balans, jezgra, površina, razina, tip igre, spol, cijena |
| Padelful | ~1700 reketa uključujući starije modele: oblik, godina, preporučena cijena, **ocjene** (snaga, kontrola, sweet spot, upravljivost, odskok) |

Filteri se međusobno sužavaju: **brend → model → godina → oblik → balans → razina → tip igre → površina →
jezgra → spol**, plus minimalne ocjene (**snaga, kontrola, sweet spot, upravljivost, odskok ≥ X**) i pretraga
po nazivu. Klik na verziju pokreće pretragu **točno te verzije**.

Katalog za svaki model zna sve oznake verzija. Za Metalbone to su `carbon, ctrl, hrd, team, light, zz,
reserve, superlight, pro, edt`, pa kod pretrage "Metalbone CTRL 3.4 2025":

| oglas | rezultat |
|---|---|
| Metalbone CTRL 3.4 2025 Ale Galán | ✅ točan (imena igrača i boje se ignoriraju) |
| Metalbone **Carbon** CTRL 3.4 2025 | ↪ varijanta (prikazuje se samo uz "prikaži varijante") |
| Metalbone CTRL **3.3 2024** | ❌ odbačen |

Novi izvor kataloga = async funkcija koja vraća `list[Racket]`, dodana u `PROVIDERS` u [core/catalog.py](core/catalog.py).

## Dubinska provjera oglasa

Ljudi na oglasnicima često pišu nepotpune naslove: naslov kaže "Adidas Metalbone", a opis "Metalbone 3.3, 2024".
Zato se oglasnici (Vinted, Njuškalo, Index) pretražuju i šire, samo po nazivu modela (npr. `metalbone`).
Oglasi čiji naslov spominje model, ali ne i verziju ili godinu, **otvaraju se i čita se opis**
(do 30 po izvoru, opisi se pamte 24 h). Ako opis potvrdi točnu verziju, oglas ulazi u rezultate s
oznakom "✓ potvrđeno iz opisa oglasa".

Pravila: opis može **dopuniti** naslov (verzija, broj, godina). Torba ili brend iz opisa ne odbacuju oglas
("dolazi s torbom"), a godina iz opisa samo potvrđuje ("kupljen 2023" ne odbacuje).

## Mobitel

Server radi i na kućnoj Wi-Fi mreži. U **Postavkama** na računalu je QR kod: skeniraš ga mobitelom i
app se otvori (u pregledniku mobitela "Dodaj na početni zaslon" daje ikonu kao aplikacija).

- Svaki uređaj osim računala treba tajni ključ (u QR kodu). Bez njega dobiva "403 zabranjeno"
  ([core/access.py](core/access.py)).
- Pri prvom pokretanju Windows pita za vatrozid: dopusti **privatne mreže**.
- Izvan kuće: instaliraj [Tailscale](https://tailscale.com) na računalo i mobitel (besplatno), pa ista adresa radi svugdje.

## Izvori

| Izvor | Vrsta | Kako | Dostava u HR |
|---|---|---|---|
| Vinted | rabljeno/novo, i iz drugih EU zemalja | podaci iz stranice pretrage | procjena 3,99 € (paketomat) + stvarna naknada za zaštitu kupca |
| Njuškalo | rabljeno | HTML pretraga | procjena 3,50 € (BOX NOW) |
| Index oglasi | rabljeno | njihov JSON API | procjena 3,50 € (BOX NOW) |
| eBay.de | novo/rabljeno, samo EU | službeni Browse API (ključ u Postavkama) ili scraping kao rezerva | **stvarna**, za Zagreb 10000 |
| Padel Market, Padel Pro Shop, Padelshop, Padel-Point | novo | Shopify `suggest.json` | **stvarna**, iz košarice (`/cart/shipping_rates.json`) |
| Padel Nuestro, Padel Reference | novo | Doofinder search API | cjenik trgovine |
| Zona de Padel, Time2Padel | novo | PrestaShop AJAX pretraga | cjenik trgovine |

Cjenici dostave u [core/shipping.py](core/shipping.py) provjereni su 2026-10-13 na stranicama trgovina:
[Padel Nuestro](https://www.padelnuestro.com/int/shipping-and-delivery),
[Time2Padel](https://www.time2padel.com/en/content/1-shipping-policy),
[Zona de Padel](https://www.zonadepadel.com/content/28-shipment-information),
[Padel Reference](https://www.padelreference.com/en/terms-and-conditions).
U sučelju je procjena označena s **~** i točkastom crtom.

Ponude koje se šalju izvan EU (npr. iz UK-a) se izbacuju jer se na njih plaća carina i PDV.

## Kako radi

```
upit ──► engine.stream()  ── paralelno svi izvori (timeout 15 s, cache 45 s / 10 min)
             │
             ├─ source.search(term)        ► sirove ponude (Offer)
             ├─ matcher.match()            ► točan model / godina / varijanta / odbaci
             ├─ source.enrich() [opcija]   ► stvarna dostava samo za pogođene ponude
             └─ engine.mark_deals()        ► "apsurdno" = ≥30 % ispod medijana novih ponuda
                    │
        ┌───────────┴───────────┐
   SSE /api/search          watcher.loop()  ── oglasnici svakih 90 s, trgovine 15 min
   (UI prikazuje odmah)          └─ novo / pad cijene ispod praga ► telegram.send()
```

| Datoteka | Odgovornost |
|---|---|
| [app.py](app.py) | FastAPI rute (pretraga kao SSE stream, watchlist, postavke) |
| [core/models.py](core/models.py) | `Offer`, jedna ponuda; `total = cijena + naknade + dostava` |
| [core/matcher.py](core/matcher.py) | prepoznavanje točnog modela; **rječnici** brendova, varijanti i opreme |
| [core/catalog.py](core/catalog.py) | katalog reketa sa specifikacijama; oznake verzija po modelu |
| [core/access.py](core/access.py) | pristup s mobitela: tajni ključ, LAN adresa, QR kod |
| [core/engine.py](core/engine.py) | paralelno pokretanje izvora, cache, zdravlje izvora, rangiranje |
| [core/shipping.py](core/shipping.py) | pravila dostave u HR, tečaj |
| [core/watcher.py](core/watcher.py) | pozadinsko praćenje i obavijesti |
| [core/telegram.py](core/telegram.py) | slanje poruka, povezivanje chata |
| [core/db.py](core/db.py) | SQLite (`data.db`, lokalno, nije na GitHubu) |
| [sources/](sources/) | po jedan modul po izvoru ili platformi |
| [static/](static/) | sučelje (HTML + CSS + JS, bez build koraka); filteri kataloga u `catalog.js` |

## Proširenja

### Nova trgovina na već podržanoj platformi (1 red)
- **Shopify**: dodaj red u `SHOPS` u [sources/shopify.py](sources/shopify.py). Dostava se računa sama.
- **Doofinder**: dodaj red u `SHOPS` u [sources/doofinder.py](sources/doofinder.py) (hashid je u
  `eu1-config.doofinder.com/2.x/<id>.js` na njihovoj stranici) i pravilo u `SHOP_RULES` u [core/shipping.py](core/shipping.py).
- **PrestaShop**: red u `SHOPS` u [sources/prestashop.py](sources/prestashop.py) i pravilo u `SHOP_RULES`.

Kako prepoznati platformu: ako `https://trgovina/search/suggest.json?q=x` vrati JSON, to je Shopify.

### Potpuno novi izvor
1. Napravi `sources/novi_izvor.py`:
   ```python
   from core.models import Offer
   from .base import Source

   async def search(query: str) -> list[Offer]:
       ...  # vrati SVE ponude za upit; matcher sam odbacuje krive modele
       return [Offer(source="novi", source_name="Novi", id=..., title=..., url=..., price=...,
                     shipping=..., shipping_note=..., shipping_exact=False)]

   SOURCES = [Source("novi", "Novi", "market", search)]  # "market" ili "shop"
   ```
   Opcionalno `details=` funkcija koja vraća opis oglasa (za dubinsku provjeru, vidi `sources/vinted.py`).
2. Dodaj modul u `MODULES` u [sources/__init__.py](sources/__init__.py).
3. Dodaj test parsera u [tests/test_sources.py](tests/test_sources.py) i provjeri s `check.py`.

Sve ostalo (UI, praćenje, Telegram, zdravlje izvora) radi automatski.

### Matcher griješi?
Dopuni rječnike na vrhu [core/matcher.py](core/matcher.py) (`VARIANTS`, `ACCESSORY`, `BRANDS`...) i dodaj
primjer u [tests/test_matcher.py](tests/test_matcher.py).

## Telegram i eBay ključ
Upute su u aplikaciji, na kartici **Postavke**. Tokeni i ključevi spremaju se samo u lokalni `data.db`
(u `.gitignore`) i nikad se ne šalju natrag u preglednik.

## Ograničenja
- Facebook Marketplace traži prijavu, pa nije podržan.
- Stranice mijenjaju strukturu. Kad izvor prestane raditi, vidi se u Postavkama → Izvori, a nakon
  3 uzastopne greške stiže Telegram upozorenje.
- Praćenje radi dok je app pokrenut na računalu.
