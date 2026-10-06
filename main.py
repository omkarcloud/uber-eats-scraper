"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. Inputs are the resolved forms the API builds from its query
params: a store is its uuid (refs.resolve_store turns any store link into
one) and a location is {"query": address} or {"latitude", "longitude"}.
"""
import json
import os

from uber_eats import refs, stores

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    five_guys = refs.resolve_store(
        "https://www.ubereats.com/store/five-guys-253-w-42nd-st-ny-1499/ZWhjmPWFQ5uuTNq-BYoKYA")
    times_square = refs.resolve_location("Times Square, New York")

    # phone, address, hours, rating — plus delivery time and distance for the address
    save("store_five_guys.json", stores.details(five_guys, location=times_square))

    # every menu section, category and item with prices
    save("menu_five_guys.json", stores.menu(five_guys))

    # 80 stores per page, with the site's sort and filters
    save("search_sushi_times_square.json", stores.search("sushi", times_square, sort_by="rating", min_rating=4.5))
