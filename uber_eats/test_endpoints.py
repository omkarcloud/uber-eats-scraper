"""Live endpoint smoke tests: one call per /uber-eats/* route against a
running service, with example values proven to return data (2026-10-05).
The listing tooling reads each route's FIRST call from this file's AST as
its working example, so the values stay literals.

Skipped unless UBER_EATS_BASE points at a running service:

    ONLY_SCRAPER=uber-eats python run.py
    UBER_EATS_BASE=http://127.0.0.1:6002 python -m pytest uber_eats/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("UBER_EATS_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set UBER_EATS_BASE to run live endpoint tests")


def call(path, status=200, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=180)
    assert resp.status_code == status, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def test_locations():
    places = call("/uber-eats/locations/autocomplete", query="350 5th Ave New York")["places"]
    assert places and places[0]["id"]
    point = call("/uber-eats/locations/details", location="Times Square, New York")["location"]
    assert point["city"] == "New York" and 40 < point["latitude"] < 41
    assert call("/uber-eats/locations/details", location="40.7484,-73.9857")["location"]["address"]
    assert call("/uber-eats/locations/autocomplete", query="Oxford Street", country="GB")["places"]


def test_nearby():
    page = call("/uber-eats/stores/nearby", location="Times Square, New York")
    assert page["currency"] == "USD" and len(page["stores"]) > 20 and page["next_cursor"]
    assert all(s["id"] and s["name"] and s["link"] for s in page["stores"])
    more = call("/uber-eats/stores/nearby", location="Times Square, New York", cursor=page["next_cursor"])
    assert more["stores"] and more["stores"][0]["id"] != page["stores"][0]["id"]
    rated = call("/uber-eats/stores/nearby", location="40.7580,-73.9855", sort_by="rating", min_rating="4.5",
                 under_30_min="true")["stores"]
    assert rated and min(s["rating"] for s in rated if s["rating"]) >= 4.5
    assert max(s["delivery_time"]["min_minutes"] for s in rated if s["delivery_time"]["min_minutes"]) <= 30
    pickup = call("/uber-eats/stores/nearby", location="Times Square, New York", dining_mode="pickup")
    assert pickup["dining_mode"] == "pickup" and any(s["distance"] for s in pickup["stores"])


def test_search():
    page = call("/uber-eats/stores/search", query="sushi", location="Times Square, New York")
    assert len(page["stores"]) > 10 and any(s["matched_items"] for s in page["stores"])
    assert call("/uber-eats/stores/search", query="sushi", location="Times Square, New York",
                cursor=page["next_cursor"])["stores"]
    cheap = call("/uber-eats/stores/search", query="pizza", location="Times Square, New York", price_range="1",
                 sort_by="delivery_time")
    assert cheap["stores"]
    assert call("/uber-eats/stores/search", query="ramen", location="35.6580,139.7016")["currency"] == "JPY"


def test_collections():
    shelves = call("/uber-eats/stores/collections", location="Times Square, New York")["collections"]
    assert len(shelves) > 3 and any(s["type"] == "stores" and s["stores"] for s in shelves)


def test_store():
    link = "https://www.ubereats.com/store/five-guys-253-w-42nd-st-ny-1499/ZWhjmPWFQ5uuTNq-BYoKYA"
    store = call("/uber-eats/stores/details", store=link, location="Times Square, New York")["store"]
    assert store["phone"] and store["location"]["latitude"] and store["hours"] and store["delivery"]["distance"]
    bare = call("/uber-eats/stores/details", store="ZWhjmPWFQ5uuTNq-BYoKYA")
    assert bare["store"]["id"] == "65686398-f585-439b-ae4c-dabe058a0a60" and bare["store"]["delivery"] is None
    call("/uber-eats/stores/details", status=404, store="65686398-f585-439b-ae4c-dabe058a0a61")
    call("/uber-eats/stores/details", status=400, store="five-guys")
    reviews = call("/uber-eats/stores/reviews", store="65686398-f585-439b-ae4c-dabe058a0a60")
    assert reviews["rating"] and len(reviews["reviews"]) > 10


def test_menu_examples():
    call("/uber-eats/stores/menu/section", store="65686398-f585-439b-ae4c-dabe058a0a60",
         section="a7abc1e5-7f23-5a76-ae26-32b76268deec")
    call("/uber-eats/stores/menu/item",
         item="https://www.ubereats.com/store/five-guys-253-w-42nd-st-ny-1499/ZWhjmPWFQ5uuTNq-BYoKYA/"
              "a7abc1e5-7f23-5a76-ae26-32b76268deec/7af41ca6-9e28-5cfb-a17f-92a64bf9e588/"
              "28403ad5-4316-532b-a96e-9a6463e6cad8")


def test_menu():
    menu = call("/uber-eats/stores/menu", store="65686398-f585-439b-ae4c-dabe058a0a60")
    assert menu["currency"] == "USD" and menu["item_count"] > 20 and not menu["is_partial"]
    section = menu["sections"][0]
    item = next(i for c in section["categories"] for i in c["items"] if i["has_customizations"])
    assert call("/uber-eats/stores/menu/section", store="65686398-f585-439b-ae4c-dabe058a0a60",
                section=section["id"])["item_count"] > 5
    found = call("/uber-eats/stores/menu/search", store="65686398-f585-439b-ae4c-dabe058a0a60", query="fries")
    assert found["item_count"] > 0
    by_link = call("/uber-eats/stores/menu/item", item=item["link"])["item"]
    assert by_link["id"] == item["id"] and by_link["customizations"] and by_link["currency"] == "USD"
    by_id = call("/uber-eats/stores/menu/item", item=item["id"], store="ZWhjmPWFQ5uuTNq-BYoKYA")["item"]
    assert by_id["name"] == by_link["name"]
    call("/uber-eats/stores/menu/item", status=400, item=item["id"])


def test_grocery_aisles():
    store = "dda45db5-2c4c-408f-ab05-b3c59fa9a235"
    menu = call("/uber-eats/stores/menu", store=store, location="Times Square, New York")
    assert menu["is_partial"] and menu["aisles"]
    aisle = call("/uber-eats/stores/menu/section", store=store, section=menu["aisles"][1]["id"],
                 location="Times Square, New York")
    assert aisle["item_count"] > 20
    if aisle["next_cursor"]:
        assert call("/uber-eats/stores/menu/section", store=store, section=menu["aisles"][1]["id"],
                    location="Times Square, New York", cursor=aisle["next_cursor"])["categories"]


def test_search_box():
    rows = call("/uber-eats/search/suggestions", query="piz", location="Times Square, New York")["suggestions"]
    assert rows and {r["type"] for r in rows} <= {"query", "store"}
    popular = call("/uber-eats/search/popular", location="Times Square, New York")
    assert popular["categories"] and popular["top_searches"]


def test_directory():
    countries = call("/uber-eats/countries")["countries"]
    assert len(countries) > 20 and any(c["code"] == "GB" for c in countries)
    region = call("/uber-eats/cities", country="US", region="ny")
    assert region["region_count"] == 1 and region["city_count"] > 100
    assert call("/uber-eats/cities", country="GB")["city_count"] > 1000
    city = call("/uber-eats/cities/details", city="new-york-city")
    assert city["city"]["name"] == "New York" and city["categories"] and city["nearby_cities"]
    assert call("/uber-eats/cities/details", city="https://www.ubereats.com/gb/city/london-eng")["city"]["country"]["code"] == "GB"
    call("/uber-eats/cities/details", status=404, city="zzzz-notacity")


def test_city_stores():
    page = call("/uber-eats/cities/stores", city="new-york-city")
    assert page["current_page"] == 1 and len(page["stores"]) == 20 and "page=2" in page["next"]
    assert call("/uber-eats/cities/stores", city="new-york-city", page=2)["previous"]
    pizza = call("/uber-eats/cities/stores", city="new-york-city", category="pizza", page=2)
    assert pizza["category"]["slug"] == "pizza" and pizza["stores"]
    assert call("/uber-eats/cities/stores", city="london-eng", country="GB")["stores"][0]["link"].startswith(
        "https://www.ubereats.com/gb/store/")
    hood = call("/uber-eats/neighborhoods/stores", neighborhood="midtown-west-manhattan-new-york-city")
    assert hood["count"] > 20 and hood["nearby_neighborhoods"]


def test_brands():
    brand = call("/uber-eats/brands/details", brand="mcdonalds")
    assert brand["brand"]["name"] == "McDonald's" and len(brand["cities"]) > 1000 and brand["other_countries"]
    stores = call("/uber-eats/brands/stores", brand="mcdonalds", city="new-york-city")
    assert stores["count"] > 50 and stores["stores"][0]["location"]["latitude"] and stores["featured_items"]
    linked = call("/uber-eats/brands/stores", brand="https://www.ubereats.com/brand-city/chicago-il/starbucks")
    assert linked["city"]["slug"] == "chicago-il" and linked["stores"]
    call("/uber-eats/brands/stores", status=400, brand="mcdonalds")
    call("/uber-eats/brands/details", status=404, brand="zzzznotabrand")
