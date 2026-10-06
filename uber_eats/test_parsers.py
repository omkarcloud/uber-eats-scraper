"""Offline tests: ref parsing, request schemas and the normalizers against
raw www.ubereats.com/_p/api responses captured 2026-10-05 (trimmed, in
uber_eats/fixtures/*.json.gz).

    python -m pytest uber_eats/test_parsers.py -q
"""
import gzip
import json
import os

import pytest

from schema_fields import load_query
from uber_eats import parsers as P
from uber_eats import refs
from uber_eats import schemas as S

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
FIVE_GUYS = "65686398-f585-439b-ae4c-dabe058a0a60"
FIVE_GUYS_LINK = "https://www.ubereats.com/store/five-guys-253-w-42nd-st-ny-1499/ZWhjmPWFQ5uuTNq-BYoKYA"


def fx(name):
    with gzip.open(os.path.join(FIX, name + ".json.gz"), "rt", encoding="utf-8") as f:
        return json.load(f)


def _no_camel_or_url_keys(obj, path="$"):
    """Every emitted key is snake_case and no key is named *url*."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert key == key.lower() and " " not in key, f"{path}.{key} not snake_case"
            assert "url" not in key, f"{path}.{key} should be a *link"
            _no_camel_or_url_keys(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _no_camel_or_url_keys(value, f"{path}[{i}]")


def _no_empty_strings(obj, path="$"):
    if isinstance(obj, dict):
        for key, value in obj.items():
            _no_empty_strings(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _no_empty_strings(value, f"{path}[{i}]")
    else:
        assert obj != "", f"{path} is an empty string (should be null)"


def _clean(obj):
    _no_camel_or_url_keys(obj)
    _no_empty_strings(obj)
    return obj


# ---- refs -----------------------------------------------------------------------------

def test_uuid_link_id_round_trip():
    assert refs.encode_uuid(FIVE_GUYS) == "ZWhjmPWFQ5uuTNq-BYoKYA"
    assert refs.decode_uuid("ZWhjmPWFQ5uuTNq-BYoKYA") == FIVE_GUYS
    assert refs.decode_uuid("not-an-id") is None
    assert refs.store_link(FIVE_GUYS, "five-guys-253-w-42nd-st-ny-1499") == FIVE_GUYS_LINK
    assert refs.store_link(FIVE_GUYS, "a&b", "gb") == "https://www.ubereats.com/gb/store/a%26b/ZWhjmPWFQ5uuTNq-BYoKYA"


@pytest.mark.parametrize("value", [
    FIVE_GUYS, FIVE_GUYS.upper(), "ZWhjmPWFQ5uuTNq-BYoKYA", FIVE_GUYS_LINK,
    FIVE_GUYS_LINK + "?diningMode=PICKUP&pl=abc",
    "ubereats.com/gb/store/five-guys/ZWhjmPWFQ5uuTNq-BYoKYA",
    "https://www.ubereats.com/en-US/store/five-guys/ZWhjmPWFQ5uuTNq-BYoKYA/a7abc1e5-7f23-5a76-ae26-32b76268deec",
    "/us/store/five-guys/ZWhjmPWFQ5uuTNq-BYoKYA",
])
def test_resolve_store(value):
    assert refs.resolve_store(value) == FIVE_GUYS


@pytest.mark.parametrize("value", ["", "five-guys", "https://www.doordash.com/store/x/ZWhjmPWFQ5uuTNq-BYoKYA",
                                   "https://www.ubereats.com/city/new-york-city", "ZWhjmPWFQ5uuTNq"])
def test_resolve_store_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_store(value)


def test_resolve_item():
    section, subsection, item = ("a7abc1e5-7f23-5a76-ae26-32b76268deec", "7af41ca6-9e28-5cfb-a17f-92a64bf9e588",
                                 "28403ad5-4316-532b-a96e-9a6463e6cad8")
    link = f"{FIVE_GUYS_LINK}/{section}/{subsection}/{item}?mod=quickView"
    assert refs.resolve_item(link) == {"item": item, "store": FIVE_GUYS, "section": section, "subsection": subsection}
    assert refs.resolve_item(item.upper()) == {"item": item, "store": None, "section": None, "subsection": None}
    assert refs.item_link(FIVE_GUYS, section, subsection, item, "five-guys-253-w-42nd-st-ny-1499") == link.split("?")[0]
    for bad in ("burger", FIVE_GUYS_LINK, "https://kick.com/x"):
        with pytest.raises(ValueError):
            refs.resolve_item(bad)


@pytest.mark.parametrize("value, expected", [
    ("40.7484,-73.9857", {"latitude": 40.7484, "longitude": -73.9857}),
    (" 51.5 ; -0.12 ", {"latitude": 51.5, "longitude": -0.12}),
    ("350 5th Ave,  New York", {"query": "350 5th Ave, New York"}),
    ("10001", {"query": "10001"}),
])
def test_resolve_location(value, expected):
    assert refs.resolve_location(value) == expected


@pytest.mark.parametrize("value", ["", "a", "95.0,10.0", "x" * 201])
def test_resolve_location_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_location(value)


def test_resolve_directory_refs():
    assert refs.resolve_city("New-York-City") == {"slug": "new-york-city", "country": None}
    assert refs.resolve_city("https://www.ubereats.com/gb/city/london-eng?page=2") == {"slug": "london-eng", "country": "gb"}
    assert refs.resolve_city("https://www.ubereats.com/fr-en/city/paris-idf")["country"] == "fr"
    assert refs.resolve_city("https://www.ubereats.com/en-US/city/new-york-city")["country"] == "us"
    assert refs.resolve_category("pizza") == {"slug": "pizza", "country": None, "city": None}
    assert refs.resolve_category("https://www.ubereats.com/category/new-york-city/pizza") == \
        {"slug": "pizza", "country": None, "city": "new-york-city"}
    assert refs.resolve_neighborhood("/neighborhood/midtown-west-manhattan-new-york-city")["slug"] == \
        "midtown-west-manhattan-new-york-city"
    assert refs.resolve_region("https://www.ubereats.com/region/ny") == {"slug": "ny", "country": None}
    assert refs.resolve_brand("McDonalds") == {"slug": "mcdonalds", "country": None, "city": None}
    assert refs.resolve_brand("https://www.ubereats.com/gb/brand-city/london-eng/kfc") == \
        {"slug": "kfc", "country": "gb", "city": "london-eng"}
    for bad in ("https://www.ubereats.com/store/x/y", "https://example.com/city/x", "new york"):
        with pytest.raises(ValueError):
            refs.resolve_city(bad)


def test_absolute():
    assert refs.absolute("/us/category/new-york-city/pizza?x=1") == "https://www.ubereats.com/category/new-york-city/pizza"
    assert refs.absolute("/gb/city/london-eng") == "https://www.ubereats.com/gb/city/london-eng"
    assert refs.absolute("ubereats://store/browse?storeUUID=x") is None
    assert refs.absolute(None) is None


# ---- schemas ----------------------------------------------------------------------------

def test_nearby_schema_defaults_and_filters():
    data, error = load_query(S.NearbySchema, {"location": "Times Square, New York"})
    assert error is None
    assert data == {"location": {"query": "Times Square, New York"}, "sort_by": "recommended", "min_rating": None,
                    "price_range": None, "max_delivery_fee": None, "under_30_min": None, "has_offers": None,
                    "top_rated": None, "dining_mode": "delivery", "cursor": None}
    data, error = load_query(S.NearbySchema, {"location": "40.75,-73.98", "sort_by": "RATING", "min_rating": "4.5",
                                              "price_range": "$,2,2", "max_delivery_fee": "3", "under_30_min": "true",
                                              "dining_mode": "Pickup", "cursor": "80"})
    assert error is None
    assert data["sort_by"] == "rating" and data["min_rating"] == 4.5 and data["price_range"] == [1, 2]
    assert data["max_delivery_fee"] == 3 and data["under_30_min"] is True and data["dining_mode"] == "pickup"
    assert data["cursor"] == 80 and data["location"] == {"latitude": 40.75, "longitude": -73.98}


@pytest.mark.parametrize("schema, query", [
    (S.NearbySchema, {}),
    (S.NearbySchema, {"location": "NYC", "min_rating": "4.2"}),
    (S.NearbySchema, {"location": "NYC", "price_range": "5"}),
    (S.NearbySchema, {"location": "NYC", "cursor": "abc"}),
    (S.NearbySchema, {"location": "NYC", "lat": "1"}),
    (S.SearchSchema, {"location": "NYC"}),
    (S.StoreSchema, {"store": "five-guys"}),
    (S.MenuItemSchema, {"item": "28403ad5-4316-532b-a96e-9a6463e6cad8"}),
    (S.MenuSectionSchema, {"store": FIVE_GUYS, "section": "burgers"}),
    (S.CityStoresSchema, {"city": "new-york-city", "page": "0"}),
    (S.CityStoresSchema, {"city": "new-york-city", "country": "USA"}),
    (S.BrandStoresSchema, {"brand": "mcdonalds"}),
])
def test_schema_rejects(schema, query):
    data, error = load_query(schema, query)
    assert data is None and error["error"].startswith("Invalid parameters")


def test_schema_accepts_links():
    data, error = load_query(S.MenuItemSchema, {"item": f"{FIVE_GUYS_LINK}/a7abc1e5-7f23-5a76-ae26-32b76268deec/"
                                                        "7af41ca6-9e28-5cfb-a17f-92a64bf9e588/"
                                                        "28403ad5-4316-532b-a96e-9a6463e6cad8"})
    assert error is None and data["item"]["store"] == FIVE_GUYS and data["store"] is None
    data, error = load_query(S.BrandStoresSchema, {"brand": "https://www.ubereats.com/brand-city/chicago-il/starbucks"})
    assert error is None and data["brand"]["city"] == "chicago-il" and data["country"] == "us"
    data, error = load_query(S.CityStoresSchema, {"city": "london-eng", "country": "GB", "category": "pizza", "page": "3"})
    assert error is None and data["country"] == "gb" and data["category"]["slug"] == "pizza" and data["page"] == 3


# ---- value helpers ----------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("$8.95 Delivery Fee", 8.95), ("2,49 € Liefergebühr", 2.49), ("11,748.2 km", 11748.2), ("￥13,200", 13200.0),
    ("£0 Delivery Fee", 0.0), ("1.234,50 €", 1234.5), ("Free", None), (None, None), (3, 3.0),
])
def test_parse_number(value, expected):
    assert P.parse_number(value) == expected


def test_small_helpers():
    assert P.money(1775) == 17.75 and P.money(1320000) == 13200.0 and P.money(None) is None and P.money("x") is None
    assert P.parse_count("8,000+") == 8000 and P.parse_count("3000+") == 3000 and P.parse_count("") is None
    assert P.clock(390) == "06:30" and P.clock(1439) == "23:59" and P.clock(None) is None
    assert P.minutes_range("10–22 Min") == (10, 22) and P.minutes_range("17 min") == (17, 17)
    assert P.minutes_range("39～64 分") == (39, 64) and P.minutes_range("6:01AM") == (None, None)
    assert P.distance({"text": "0.2 mi"}) == {"value": 0.2, "unit": "mi"} and P.distance(None) is None
    assert P.iso_datetime("2021-11-11T00:00:00Z") == "2021-11-11T00:00:00Z"
    assert P.iso_datetime("2026-10-05T10:30:00.000Z") == "2026-10-05T10:30:00Z" and P.iso_datetime(0) is None
    assert P.strip_html("<h3>Is it &amp; open?</h3><p>Yes.</p>") == "Is it & open?\nYes."
    assert P._snake("buyXGetY") == "buy_x_get_y" and P._snake("priceRangeFilter") == "price_range_filter"


# ---- locations --------------------------------------------------------------------------

def test_locations():
    places = [P.place_suggestion(r) for r in fx("autocomplete")]
    assert places and places[0]["id"] and places[0]["name"] == "350 5th Ave" and places[0]["provider"] == "google_places"
    point = P.delivery_location(fx("deliveryloc"), query="times square")
    assert point["city"] == "New York" and point["postal_code"] == "10036" and point["country"] == "US"
    assert abs(point["latitude"] - 40.758) < 0.01 and point["query"] == "times square"
    reverse = P.delivery_location(fx("reverse"))
    assert reverse["address"] and reverse["city"] == "New York" and reverse["latitude"] and reverse["query"] is None
    assert P.delivery_location(None)["latitude"] is None
    _clean([places, point, reverse])


# ---- feed / search ----------------------------------------------------------------------

def test_feed_stores_and_collections():
    feed = fx("feed")
    stores = P.feed_stores(feed)
    assert len(stores) >= 10 and len({s["id"] for s in stores}) == len(stores)
    card = stores[0]
    assert set(card) == {"id", "name", "link", "image", "rating", "review_count", "is_new", "is_orderable",
                         "availability", "status", "delivery_time", "delivery_fee", "is_surge_pricing", "distance",
                         "offers", "badges", "location"}
    for store in stores:
        assert store["name"] and store["link"].startswith("https://www.ubereats.com/store/")
        assert refs.resolve_store(store["link"]) == store["id"]
        assert store["image"] is None or store["image"].startswith("https://")
        assert store["rating"] is None or 1 <= store["rating"] <= 5
    assert any(s["rating"] and s["review_count"] for s in stores)
    assert any(s["delivery_time"]["min_minutes"] for s in stores)
    assert any(s["location"] and s["location"]["latitude"] for s in stores)
    shelves = P.feed_collections(feed)
    kinds = {s["type"] for s in shelves}
    assert "stores" in kinds and all(s["title"] for s in shelves)
    for shelf in shelves:
        rows = shelf["stores"] if shelf["type"] == "stores" else shelf["items"]
        assert rows and all(r["id"] and r["name"] for r in rows)
    _clean([stores, shelves])


def test_search_stores_carry_matched_items():
    stores = P.feed_stores(fx("search"))
    assert len(stores) >= 8
    assert all("matched_items" in s for s in stores)
    matched = [i for s in stores for i in s["matched_items"]]
    for item in matched:
        assert item["id"] and item["name"]
        assert item["link"] is None or refs.resolve_item(item["link"])["item"] == item["id"]
    assert any(s["rating"] for s in stores)
    _clean(stores)


def test_feed_parsers_survive_garbage():
    assert P.feed_stores(None) == [] and P.feed_stores({"feedItems": [None, {}, {"store": {}}, 5]}) == []
    assert P.feed_collections({"feedItems": [{"type": "REGULAR_CAROUSEL"}, {"type": "X"}]}) == []
    card = P.store_card({"storeUuid": "x", "meta": [None, {"badgeType": "FARE"}], "image": {"items": [None]}})
    assert card["id"] == "x" and card["link"] is None and card["delivery_fee"] is None


# ---- store ------------------------------------------------------------------------------

def test_store_details():
    store = P.store_details(fx("store"))
    assert store["id"] == FIVE_GUYS and store["link"] == FIVE_GUYS_LINK
    assert store["name"].startswith("Five Guys") and store["phone"] == "+12123982600"
    assert store["price_range"] == "$" and "Burgers" in store["cuisines"] and store["currency"] == "USD"
    assert store["rating"] == 4.6 and store["review_count"] == 8000 and 4.5 < store["rating_exact"] < 4.7
    assert store["merchant_type"] == "restaurant" and store["chain"]["name"] == "Five Guys"
    location = store["location"]
    assert location["city"] == "New York" and location["postal_code"] == "10036" and location["country"] == "US"
    assert abs(location["latitude"] - 40.757) < 0.01 and location["city_slug"] == "new-york-city"
    period = store["hours"][0]["periods"][0]
    assert period["opens_at"] == "06:30" and period["closes_at"] == "03:53" and period["closes_next_day"] is True
    assert store["delivery"]["min_minutes"] and store["delivery"]["distance"]["unit"] == "mi"
    assert [m["mode"] for m in store["dining_modes"]] == ["delivery", "pickup"]
    assert store["menus"] and all(m["id"] and m["title"] for m in store["menus"])
    assert store["categories"][0] == {"name": "American", "link": "https://www.ubereats.com/category/new-york-city/american"}
    assert store["health_inspection"]["link"].startswith("https://")
    assert store["joined_at"] == "2020-02-04T01:22:17Z" and store["image"].startswith("https://")
    _clean(store)


def test_store_details_without_a_delivery_point():
    store = P.store_details(fx("store"), has_point=False)
    assert store["delivery"] is None and store["availability"] is None
    assert store["dining_modes"] == [{"mode": "delivery", "is_available": True}, {"mode": "pickup", "is_available": True}]
    assert P.store_details({})["id"] is None and P.store_details(None)["hours"] == []


def test_store_reviews_and_rating():
    raw = fx("store")
    rows = P.store_reviews(raw)
    assert rows and rows[0]["is_featured"] is True and len({r["id"] for r in rows}) == len(rows)
    for row in rows:
        assert row["text"] and row["reviewer_name"] and row["created_at"].endswith("Z")
    assert P.store_rating(raw)["review_count"] == 8000
    assert P.store_reviews({}) == [] and P.store_rating(None) == {"rating": None, "rating_exact": None, "review_count": None}
    _clean(rows)


def test_menu_sections():
    raw = fx("store")
    sections = P.menu_sections(raw)
    assert len(sections) == 2 and {s["title"] for s in sections} == {"Menu", "Breakfast Menu"}
    items = [i for s in sections for c in s["categories"] for i in c["items"]]
    assert items and all(s["item_count"] == sum(c["item_count"] for c in s["categories"]) for s in sections)
    for item in items:
        assert item["id"] and item["name"] and isinstance(item["price"], float)
        ref = refs.resolve_item(item["link"])
        assert ref["store"] == FIVE_GUYS and ref["item"] == item["id"] and ref["section"] == item["section_id"]
    liked = [i for i in items if i["liked_percent"] is not None]
    assert liked and all(0 <= i["liked_percent"] <= 100 and i["rating_count"] > 0 for i in liked)
    assert any(i["labels"] for i in items) and not any("%" in label for i in items for label in i["labels"])
    _clean(sections)


def test_grocery_storefront():
    raw = fx("store_grocery")
    sections = P.menu_sections(raw)
    assert len(sections) == 1 and sections[0]["id"] is None and sections[0]["categories"]
    product = sections[0]["categories"][0]["items"][0]
    assert product["purchase"]["sold_by"] == "count" and product["purchase"]["min_quantity"] == 1
    assert product["product_id"] and product["price"] > 0
    tiles = [t for v in raw["catalogSectionsMap"].values() for t in P.aisle_shortcuts(v)]
    assert tiles and all(t["id"] and t["title"] for t in tiles)
    assert P.store_details(raw)["merchant_type"] == "convenience"
    _clean([sections, tiles])


def test_prices_divide_by_100_in_every_currency():
    raw = fx("store_jp")
    assert raw["currencyCode"] == "JPY"
    items = [i for s in P.menu_sections(raw) for c in s["categories"] for i in c["items"]]
    source = [r for v in raw["catalogSectionsMap"].values() for sec in v
              for r in ((sec.get("payload") or {}).get("standardItemsPayload") or {}).get("catalogItems") or []]
    shown = P.parse_number(source[0]["priceTagline"]["text"])
    assert items[0]["price"] == shown == source[0]["price"] / 100


def test_catalog_section_and_instore_search():
    groups = P.catalog_groups(fx("catalog_section")["catalog"], "dda45db5-2c4c-408f-ab05-b3c59fa9a235", "duane-reade")
    assert len(groups) >= 5 and all(g["title"] and g["items"] for g in groups)
    found = []
    for section_id, sections in fx("instore_search")["catalogSectionsMap"].items():
        found.extend(P.catalog_groups(sections, FIVE_GUYS, "five-guys", None, section_id))
    names = [i["name"] for g in found for i in g["items"]]
    assert names and any("Fries" in n for n in names)
    assert P.catalog_groups(None) == [] and P.catalog_groups([{"type": "EMPTY_STATE", "payload": {}}]) == []
    _clean([groups, found])


def test_menu_item_details():
    item = P.menu_item_details(fx("menu_item"), FIVE_GUYS, "five-guys-253-w-42nd-st-ny-1499", None, "USD")
    assert item["name"] == "Bacon Cheeseburger" and item["price"] == 17.75 and item["currency"] == "USD"
    assert item["link"].startswith(FIVE_GUYS_LINK + "/") and item["images"] and item["has_customizations"] is True
    assert item["customization_count"] == len(item["customizations"]) >= 2
    toppings = next(g for g in item["customizations"] if g["title"] == "Unlimited Toppings")
    assert toppings["is_required"] is True and toppings["min_selections"] == 1 and toppings["option_count"] >= 10
    option = toppings["options"][0]
    assert set(option) == {"id", "name", "description", "price", "is_sold_out", "default_quantity", "min_quantity",
                           "max_quantity", "dietary_labels", "customizations"}
    assert option["id"] and option["name"] and option["price"] == 0.0
    assert not any("%" in label for label in item["labels"])
    assert P.menu_item_details({})["customizations"] == []
    _clean(item)


def test_customizations_nest():
    groups = P.customization_groups([{"uuid": "g", "title": "Size", "minPermitted": 1, "maxPermitted": 1, "options": [
        {"uuid": "o", "title": "Large", "price": 250, "childCustomizationList": [
            {"uuid": "c", "title": "Extra", "minPermitted": 0, "maxPermitted": 2, "options": [{"uuid": "x", "title": "Cheese", "price": 100}]}]}]}])
    assert groups[0]["is_required"] and groups[0]["options"][0]["price"] == 2.5
    child = groups[0]["options"][0]["customizations"][0]
    assert child["title"] == "Extra" and child["is_required"] is False and child["options"][0]["price"] == 1.0


# ---- search box -------------------------------------------------------------------------

def test_suggestions():
    rows = [s for s in (P.suggestion(r) for r in fx("suggestions")) if s]
    kinds = {r["type"] for r in rows}
    assert kinds == {"store", "query"} and all(r["text"] for r in rows)
    store = next(r for r in rows if r["type"] == "store")["store"]
    assert store["id"] and refs.resolve_store(store["link"]) == store["id"] and None not in store["categories"]
    assert P.suggestion({"type": "searchTextV2", "title": 'Search for "piz"'}) is None
    _clean(rows)


# ---- directory --------------------------------------------------------------------------

def test_city_page():
    elements = P.elements_by_id(fx("seo_city"))
    stores = P.seo_stores(elements["cityPaginatedStores"])
    assert stores and all(s["id"] and s["name"] and s["location"]["address"] for s in stores)
    card = stores[0]
    assert refs.resolve_store(card["link"]) == card["id"] and card["price_range"] and card["cuisines"]
    assert card["location"]["latitude"] is None and card["delivery_time"]["min_minutes"]
    assert any(s["description"] for s in stores)
    assert P.faqs(elements["faqs"])[0]["question"].endswith("?") and "<" not in P.page_text(elements)
    assert P.seo_stores(None) == [] and P.faqs(None) == []
    _clean(stores)


def test_paginated_and_international_city_pages():
    stores = P.seo_stores(fx("paginated_city"))
    assert stores and all(s["id"] and s["name"] for s in stores)
    gb = P.seo_stores(P.elements_by_id(fx("seo_city_gb"))["cityPaginatedStores"], "gb")
    assert gb and all(s["link"].startswith("https://www.ubereats.com/gb/store/") for s in gb)
    hood = P.seo_stores(P.elements_by_id(fx("seo_hood"))["cityStores"])
    assert hood and all(s["id"] for s in hood)
    _clean([stores, gb, hood])
