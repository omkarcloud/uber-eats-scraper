"""/uber-eats/stores/* — stores around a delivery address (home feed, search,
feed shelves) and one store's profile, menu, grocery aisles, in-store
search, item customizations and reviews.

Every address-based function takes the schema's resolved `location`
({"query"} or {"latitude", "longitude"}); shared.resolve_point turns it into
the delivery point the site reads from its uev2.loc cookie."""
from uber_eats import parsers as P
from uber_eats import shared
from uber_eats.fetch import UberEatsNotFound, rpc, run_parallel

PAGE_SIZE = 80

# The site's filter ids (the `sortAndFilters` block of every feed / search
# answer lists them; identical in every market checked: US, GB, JP).
_SORT = "1c7cf7ef-730f-431f-9072-26bc39f7c021"
_SORT_OPTIONS = {"rating": "5991d63c-4d42-46bc-8301-ce224557e615",
                 "delivery_time": "5c7cf7ef-730f-431f-9072-26bc39f7c024"}
_RATING = "b19c8978-203c-4a89-a23e-e4842febe4ff"
_RATING_OPTIONS = {3.0: "80635370-646d-11ee-9e1f-9dde45bcea83", 3.5: "334823d0-646e-11ee-a308-016b4994ba14",
                   4.0: "2c7cf7ef-730f-431f-9072-26bc39f7c042", 4.5: "2c7cf7ef-730f-431f-9072-26bc39f7c043",
                   5.0: "5ac23040-646e-11ee-b477-a9228312172d"}
_PRICE = "2c7cf7ef-730f-431f-9072-46bc39f7c021"
_PRICE_OPTIONS = {1: "2c7cf7ef-730f-431f-9072-26bc39f7c032", 2: "2c7cf7ef-730f-431f-9072-26bc39f7c033",
                  3: "2c7cf7ef-730f-431f-9072-26bc39f7c034", 4: "2c7cf7ef-730f-431f-9072-26bc39f7c035"}
_FEE = "2c7cf7ef-730f-431f-9072-27bc39f7c021"
_FEE_OPTIONS = {2: "2c7cf7ef-730f-431f-9072-26bc39f7c022", 3: "2c7cf7ef-730f-431f-9072-26bc39f7c023",
                4: "2c7cf7ef-730f-431f-9072-26bc39f7c024"}
_TIME = ("cc5cdb95-a6e6-4371-8d10-a07c2175e509", "cc5cdb95-a6e6-4371-8d10-a07c2175e510")
_DEALS = ("33e0f7cc-8927-4dac-a92e-19a296aab097", "g996476c-2b1b-4db2-b40a-13d43cb117dc")
_TOP = ("f844706c-2b1b-4db2-b40a-13d43cb338da", "12ce1932-1878-4e2e-80d0-5760c095c641")


def _filters(sort_by, min_rating, price_range, max_delivery_fee, under_30_min, has_offers, top_rated):
    out = []

    def add(uuid, *options):
        out.append({"uuid": uuid, "options": [{"uuid": o} for o in options]})

    if sort_by in _SORT_OPTIONS:
        add(_SORT, _SORT_OPTIONS[sort_by])
    if min_rating is not None:
        add(_RATING, _RATING_OPTIONS[float(min_rating)])
    if price_range:
        add(_PRICE, *[_PRICE_OPTIONS[p] for p in price_range])
    if max_delivery_fee is not None:
        add(_FEE, _FEE_OPTIONS[int(max_delivery_fee)])
    if under_30_min:
        add(*_TIME)
    if has_offers:
        add(*_DEALS)
    if top_rated:
        add(*_TOP)
    return out


def _mode(dining_mode):
    return "PICKUP" if dining_mode == "pickup" else None


def _feed_page(name, body, location, dining_mode, cursor):
    point, public = shared.resolve_point(location)
    body = dict(body)
    body["pageInfo"] = {"offset": cursor or 0, "pageSize": PAGE_SIZE}
    feed = rpc(name, body, point=point, dining_mode=_mode(dining_mode)) or {}
    stores = P.feed_stores(feed)
    meta = P.as_dict(feed.get("meta"))
    has_more = bool(meta.get("hasMore")) and bool(stores)
    return feed, public, {
        "location": public,
        "dining_mode": dining_mode,
        "currency": P.text(feed.get("currencyCode")),
        "is_in_service_area": feed.get("isInServiceArea") if isinstance(feed.get("isInServiceArea"), bool) else None,
        "count": len(stores),
        "has_more": has_more,
        "next_cursor": str(meta.get("offset")) if has_more and meta.get("offset") is not None else None,
        "stores": stores,
    }


def nearby(location, sort_by="recommended", min_rating=None, price_range=None, max_delivery_fee=None,
           under_30_min=None, has_offers=None, top_rated=None, dining_mode="delivery", cursor=None):
    """Stores that deliver to (or offer pickup near) an address: the site's
    home feed as one flat list, with its sort and filters."""
    filters = _filters(sort_by, min_rating, price_range, max_delivery_fee, under_30_min, has_offers, top_rated)
    _, _, out = _feed_page("getFeedV1", {"userQuery": "", "sortAndFilters": filters}, location, dining_mode, cursor)
    return out


def search(query, location, sort_by="recommended", min_rating=None, price_range=None, max_delivery_fee=None,
           under_30_min=None, has_offers=None, top_rated=None, dining_mode="delivery", cursor=None):
    """Search stores, dishes and products around an address. Each store
    lists the items the query matched in it (`matched_items`)."""
    filters = _filters(sort_by, min_rating, price_range, max_delivery_fee, under_30_min, has_offers, top_rated)
    body = {"userQuery": query, "sortAndFilters": filters, "vertical": "ALL", "searchSource": "SEARCH_SUGGESTION",
            "displayType": "SEARCH_RESULTS", "searchType": "GLOBAL_SEARCH", "keyName": "", "cacheKey": "",
            "recaptchaToken": "", "date": "", "startTime": 0, "endTime": 0}
    _, _, out = _feed_page("getSearchFeedV1", body, location, dining_mode, cursor)
    out.pop("is_in_service_area", None)
    for card in out["stores"]:
        card.setdefault("matched_items", [])
    return {"query": query, **out}


def collections(location, dining_mode="delivery"):
    """The shelves of the home feed for an address: 'National favorites',
    'Today's offers', 'Popular in your area' ... (stores) and single-store
    product shelves (items)."""
    point, public = shared.resolve_point(location)
    feed = rpc("getFeedV1", {"userQuery": "", "sortAndFilters": [], "pageInfo": {"offset": 0, "pageSize": PAGE_SIZE}},
               point=point, dining_mode=_mode(dining_mode)) or {}
    rows = P.feed_collections(feed)
    return {
        "location": public,
        "dining_mode": dining_mode,
        "currency": P.text(feed.get("currencyCode")),
        "count": len(rows),
        "collections": rows,
    }


# ---- one store -----------------------------------------------------------------

def _store(store, location, dining_mode="delivery"):
    """(raw getStoreV1 data, public location | None)."""
    point, public = shared.resolve_point(location) if location else (None, None)
    return shared.store_raw(store, point, _mode(dining_mode)), public


def details(store, location=None, dining_mode="delivery"):
    """One store's profile: contact, address, hours, rating, cuisines,
    chain, menus summary. Delivery time / fee / distance need `location`."""
    raw, public = _store(store, location, dining_mode)
    return {"location": public, "store": P.store_details(raw, has_point=public is not None)}


def menu(store, location=None, dining_mode="delivery"):
    """The store's full menu. Restaurants: every menu (Breakfast, Lunch ...)
    with its categories and items. Grocery / retail stores ship only their
    storefront shelves here; `aisles` lists the rest for /menu/section."""
    raw, _ = _store(store, location, dining_mode)
    sections = P.menu_sections(raw)
    multi_level = bool(P.as_dict(raw.get("storeMerchantTypeInfo")).get("isMultiLevel"))
    aisles = []
    if multi_level:
        aisles = [{"id": P.text(s.get("uuid")), "title": P.text(s.get("title"))}
                  for s in P.as_list(raw.get("sections")) if isinstance(s, dict) and s.get("uuid")]
        for sections_raw in P.as_dict(raw.get("catalogSectionsMap")).values():
            for tile in P.aisle_shortcuts(sections_raw):
                if tile["id"] not in [a["id"] for a in aisles]:
                    aisles.append({"id": tile["id"], "title": tile["title"]})
    return {
        "store": shared.store_ref(store, raw),
        "currency": P.text(raw.get("currencyCode")),
        "merchant_type": P.merchant_type(raw.get("storeMerchantTypeInfo")),
        "is_partial": multi_level,
        "section_count": len(sections),
        "item_count": sum(s["item_count"] for s in sections),
        "sections": sections,
        "aisles": aisles,
    }


def menu_section(store, section, cursor=None, location=None):
    """One menu section / grocery aisle with all its shelves, paged (the
    only way to walk a supermarket's catalogue)."""
    point = shared.resolve_point(location)[0] if location else None

    def call(section_types):
        filters = {"storeUuid": store, "sectionUuids": [section], "subsectionUuids": None,
                   "shouldReturnSegmentedControlData": True}
        if section_types:
            filters["sectionTypes"] = section_types
        return rpc("getCatalogPresentationV2", {"storeFilters": filters,
                                                "pagingInfo": {"enabled": True, "offset": cursor},
                                                "sortAndFilters": None, "source": "NV_L2_CATALOG"},
                   point=point, label="menu section") or {}

    meta, data = run_parallel([lambda: shared.store_meta(store), lambda: call(["COLLECTION"])])
    groups = P.catalog_groups(data.get("catalog"), store, meta.get("slug"), None, section)
    if not groups and not cursor:
        data = call(None)
        groups = P.catalog_groups(data.get("catalog"), store, meta.get("slug"), None, section)
    if not groups and not cursor:
        raise UberEatsNotFound(f"section '{section}' has no items in store '{store}'")
    paging = P.as_dict(data.get("pagingInfo"))
    has_more = bool(paging.get("hasMore")) and bool(groups)
    return {
        "store": shared.store_ref(store),
        "section_id": section,
        "currency": meta.get("currency"),
        "category_count": len(groups),
        "item_count": sum(g["item_count"] for g in groups),
        "has_more": has_more,
        "next_cursor": str(paging.get("offset")) if has_more and paging.get("offset") is not None else None,
        "categories": groups,
    }


def menu_search(store, query, location=None, dining_mode="delivery"):
    """Search inside one store's menu / catalogue."""
    # the RPC refuses to run without a delivery point: default to the store itself
    point = shared.resolve_point(location)[0] if location else shared.store_point(store)
    mode = _mode(dining_mode)
    body = {"diningMode": mode or "DELIVERY", "sectionUUIDs": None, "storeUUIDs": [store], "userQuery": query,
            "isGrocery": False, "entrypointContext": "IN_STORE_SEARCH"}
    meta, data = run_parallel([
        lambda: shared.store_meta(store),
        lambda: rpc("getInStoreSearchV1", body, point=point, dining_mode=mode, label="menu search") or {},
    ])
    groups = []
    for section_id, sections in P.as_dict(data.get("catalogSectionsMap")).items():
        groups.extend(P.catalog_groups(sections, store, meta.get("slug"), None, section_id))
    return {
        "store": shared.store_ref(store),
        "query": query,
        "currency": meta.get("currency"),
        "item_count": sum(g["item_count"] for g in groups),
        "categories": groups,
    }


def _locate_item(raw, item_id):
    """(section, subsection) of an item inside a raw store menu, or None."""
    for section_id, sections in P.as_dict(raw.get("catalogSectionsMap")).items():
        for section in P.as_list(sections):
            payload = P.as_dict(P.as_dict(P.as_dict(section).get("payload")).get("standardItemsPayload"))
            for row in P.as_list(payload.get("catalogItems")):
                if isinstance(row, dict) and str(row.get("uuid") or "").lower() == item_id \
                        and row.get("subsectionUuid"):
                    return (P.text(row.get("sectionUuid")) or P.text(payload.get("sectionUUID")) or section_id,
                            P.text(row.get("subsectionUuid")))
    return None


def menu_item(item, store=None, location=None):
    """One menu item with every customization group and option (sizes,
    toppings, sides ...), nested as the site nests them."""
    store_id = item.get("store") or store
    if not store_id:
        raise ValueError("store is required when item is an item id (or pass the full item link)")
    if item.get("store") and store and store != item["store"]:
        raise ValueError("store does not match the store in the item link")
    point = shared.resolve_point(location)[0] if location else None
    section, subsection = item.get("section"), item.get("subsection")
    if not (section and subsection):
        raw = shared.store_raw(store_id, point)
        found = _locate_item(raw, item["item"])
        if not found:
            raise UberEatsNotFound(f"item '{item['item']}' is not on the menu of store '{store_id}' "
                                   "(for grocery products pass the full item link)")
        section, subsection = found
    body = {"itemRequestType": "ITEM", "storeUuid": store_id, "sectionUuid": section,
            "subsectionUuid": subsection, "menuItemUuid": item["item"], "cbType": "EATER_ENDORSED",
            "contextReferences": []}

    def fetch_item():
        try:
            return rpc("getMenuItemV1", body, point=point, label="menu item")
        except UberEatsNotFound:
            raise UberEatsNotFound(f"item '{item['item']}' not found in store '{store_id}'")

    meta, data = run_parallel([lambda: shared.store_meta(store_id), fetch_item])
    if not isinstance(data, dict) or not data.get("uuid"):
        raise UberEatsNotFound(f"item '{item['item']}' not found in store '{store_id}'")
    data.setdefault("sectionUuid", section)
    data.setdefault("subsectionUuid", subsection)
    return {
        "store": shared.store_ref(store_id),
        "item": P.menu_item_details(data, store_id, meta.get("slug"), None, meta.get("currency")),
    }


def reviews(store):
    """The reviews the store page carries (featured first; the site ships
    its latest ~100, there is no deeper paging) with the rating summary."""
    raw = shared.store_raw(store)
    rows = P.store_reviews(raw)
    return {
        "store": shared.store_ref(store, raw),
        **P.store_rating(raw),
        "count": len(rows),
        "reviews": rows,
    }
