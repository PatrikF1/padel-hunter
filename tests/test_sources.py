"""Testovi parsera na malim, ručno napisanim primjerima (bez mreže)."""
from sources import BY_NAME, SOURCES, ebay, index_oglasi, njuskalo


def test_registry_has_unique_names_and_valid_kinds():
    assert len(BY_NAME) == len(SOURCES)
    assert all(s.kind in ("market", "shop") for s in SOURCES)


def test_ebay_api_offer_keeps_eu_with_shipping():
    item = {"itemId": "v1|1|0", "title": "Nox AT10 Genius 18K 2024", "itemWebUrl": "https://ebay.de/itm/1",
            "price": {"value": "120.00", "currency": "EUR"}, "conditionId": "3000",
            "itemLocation": {"country": "DE"}, "buyingOptions": ["FIXED_PRICE"],
            "shippingOptions": [{"shippingCost": {"value": "9.90"}}, {"shippingCost": {"value": "14.00"}}]}
    o = ebay._api_offer(item)
    assert (o.price, o.shipping, o.condition, o.total) == (120.0, 9.9, "used", 129.9)


def test_ebay_api_offer_drops_non_eu_and_unknown_shipping():
    base = {"itemId": "1", "title": "x", "price": {"value": "1", "currency": "EUR"}}
    assert ebay._api_offer({**base, "itemLocation": {"country": "GB"},
                            "shippingOptions": [{"shippingCost": {"value": "5"}}]}) is None
    assert ebay._api_offer({**base, "itemLocation": {"country": "DE"}}) is None


def test_njuskalo_parse():
    html = """<ul><li class="listing"><article><h3 class="title">
      <a href="/tenis-reketi/nox-at10-oglas-123" name="123"><span>NOX AT10 Genius 18K</span></a></h3>
      <img src="https://img/1.jpg"><div class="price"><p>155 €</p></div>
      <time datetime="2026-10-09T17:15:04.000Z"></time><span class="locationText">Zagreb</span>
      <ul class="features"><li><button class="feature residentialSeller"></button></li></ul>
    </article></li></ul>"""
    [o] = njuskalo.parse(html)
    assert (o.id, o.price, o.location, o.url) == ("123", 155.0, "Zagreb", "https://www.njuskalo.hr/tenis-reketi/nox-at10-oglas-123")
    assert o.extra["trgovac"] is False


def test_index_parse_builds_listing_url():
    index_oglasi._url_slugs[("sports-and-equipments", "equipment-for-tennis")] = ("sport", "tenis")
    data = {"data": [{"code": 7492497, "title": "Siux Fenix Pro 2026 padel reket", "price": 160,
                      "smartLink": "siux-fenix-pro-2026-padel-reket", "module": "sports-and-equipments",
                      "category": "equipment-for-tennis", "images": [], "cityName": "Pula"}]}
    [o] = index_oglasi.parse(data)
    assert o.url == "https://www.index.hr/oglasi/sport/tenis/oglas/siux-fenix-pro-2026-padel-reket/7492497"
