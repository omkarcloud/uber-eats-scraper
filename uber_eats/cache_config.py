"""Cache TTL per /uber-eats/* endpoint (cache.py, keyed on the validated
params).

Tiers follow how fast Uber Eats moves each surface: delivery times and
open / closed state change by the minute, a menu changes a few times a day,
an address never moves and the city directory changes a few times a year.
"""
from datetime import timedelta

# --- address box -------------------------------------------------------------
AUTOCOMPLETE_CACHE = timedelta(days=1)
LOCATION_CACHE = timedelta(days=7)

# --- live surfaces (ETAs, fees, open state, offers) --------------------------
FEED_CACHE = timedelta(minutes=5)
SEARCH_CACHE = timedelta(minutes=5)
COLLECTIONS_CACHE = timedelta(minutes=10)
SUGGESTIONS_CACHE = timedelta(hours=1)
POPULAR_CACHE = timedelta(hours=6)

# --- one store ---------------------------------------------------------------
# Profile carries open / closed state and the delivery estimate.
STORE_CACHE = timedelta(minutes=10)
# Prices and sold-out flags.
MENU_CACHE = timedelta(minutes=30)
MENU_SEARCH_CACHE = timedelta(minutes=30)
ITEM_CACHE = timedelta(hours=1)
REVIEWS_CACHE = timedelta(hours=6)

# --- directory ---------------------------------------------------------------
COUNTRIES_CACHE = timedelta(days=7)
CITIES_CACHE = timedelta(days=7)
CITY_CACHE = timedelta(days=1)
# Listing pages reorder with opening hours.
CITY_STORES_CACHE = timedelta(hours=1)
NEIGHBORHOOD_CACHE = timedelta(hours=1)
BRAND_CACHE = timedelta(days=1)
BRAND_STORES_CACHE = timedelta(hours=6)
