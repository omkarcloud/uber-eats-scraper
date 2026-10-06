"""Lookups shared by the /uber-eats/* endpoint modules: address -> delivery
point, a short-lived raw store memo (details / menu / reviews all read the
same 600 KB getStoreV1 answer) and store id -> {slug, currency}."""
import threading
import time
from collections import OrderedDict

from uber_eats import parsers as P
from uber_eats.fetch import UberEatsNotFound, rpc

POINT_TTL = 24 * 3600
STORE_TTL = 120
STORE_MEMO_SIZE = 24
META_TTL = 24 * 3600

_lock = threading.Lock()
_memo = {}
_stores = OrderedDict()


def memo(key, ttl, build):
    now = time.time()
    with _lock:
        hit = _memo.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = build()
    with _lock:
        _memo[key] = (now + ttl, value)
        if len(_memo) > 5000:
            for stale in [k for k, v in _memo.items() if v[0] <= now]:
                _memo.pop(stale, None)
    return value


def remember(key, ttl, value):
    with _lock:
        _memo[key] = (time.time() + ttl, value)


def recall(key):
    with _lock:
        hit = _memo.get(key)
        return hit[1] if hit and hit[0] > time.time() else None


# ---- delivery point --------------------------------------------------------------

def _geocode(query):
    hits = rpc("mapsSearchV1", {"query": query}, label="address lookup") or []
    hit = next((h for h in hits if isinstance(h, dict) and h.get("id")), None)
    if hit is None:
        raise UberEatsNotFound(f"no address matched '{query}'")
    data = rpc("getDeliveryLocationV1", {"placeId": hit["id"], "provider": hit.get("provider") or "google_places",
                                         "source": "manual_auto_complete"}, label="address lookup")
    if not isinstance(data, dict) or data.get("latitude") is None or data.get("longitude") is None:
        raise UberEatsNotFound(f"no address matched '{query}'")
    return data


def resolve_point(location):
    """The schema's `location` ({"query"} or {"latitude", "longitude"}) ->
    (point for the uev2.loc cookie, public location object)."""
    if location.get("query"):
        query = location["query"]
        data = memo(("point", query.lower()), POINT_TTL, lambda: _geocode(query))
        point = {key: data.get(key) for key in ("latitude", "longitude", "address", "reference",
                                                "referenceType", "type", "addressComponents")}
        return point, P.delivery_location(data, query=query)
    point = {"latitude": location["latitude"], "longitude": location["longitude"]}
    public = P.delivery_location(point)
    return point, public


# ---- stores ----------------------------------------------------------------------

def _point_key(point):
    if not point:
        return None
    return (round(float(point["latitude"]), 5), round(float(point["longitude"]), 5))


def store_raw(store_id, point=None, dining_mode=None):
    """getStoreV1 data for one store, memoised for STORE_TTL seconds per
    (store, point, dining mode). Also seeds the store meta memo."""
    key = (store_id, _point_key(point), dining_mode)
    now = time.time()
    with _lock:
        hit = _stores.get(key)
        if hit and hit[0] > now:
            _stores.move_to_end(key)
            return hit[1]
    body = {"storeUuid": store_id, "diningMode": dining_mode or "DELIVERY", "time": {"asap": True},
            "cbType": "EATER_ENDORSED"}
    try:
        data = rpc("getStoreV1", body, point=point, dining_mode=dining_mode, label="store")
    except UberEatsNotFound:
        raise UberEatsNotFound(f"store '{store_id}' not found")
    if not isinstance(data, dict) or not data.get("uuid"):
        raise UberEatsNotFound(f"store '{store_id}' not found")
    remember(("store_meta", store_id), META_TTL, {
        "slug": P.text(data.get("slug")),
        "name": P.text(data.get("title")),
        "currency": P.text(data.get("currencyCode")),
        "latitude": P.to_float(P.as_dict(data.get("location")).get("latitude")),
        "longitude": P.to_float(P.as_dict(data.get("location")).get("longitude")),
    })
    with _lock:
        _stores[key] = (now + STORE_TTL, data)
        _stores.move_to_end(key)
        while len(_stores) > STORE_MEMO_SIZE:
            _stores.popitem(last=False)
    return data


def store_meta(store_id):
    """{slug, name, currency} of a store (one getStoreV1 on a miss)."""
    hit = recall(("store_meta", store_id))
    if hit is not None:
        return hit
    store_raw(store_id)
    return recall(("store_meta", store_id)) or {"slug": None, "name": None, "currency": None}


def store_point(store_id):
    """The store's own coordinates as a delivery point (None if unknown)."""
    meta = store_meta(store_id)
    if meta.get("latitude") is None or meta.get("longitude") is None:
        return None
    return {"latitude": meta["latitude"], "longitude": meta["longitude"]}


def store_ref(store_id, raw=None):
    """The small {id, name, link} header list endpoints carry."""
    if isinstance(raw, dict):
        slug, name = P.text(raw.get("slug")), P.text(raw.get("title"))
    else:
        meta = recall(("store_meta", store_id)) or {}
        slug, name = meta.get("slug"), meta.get("name")
    return {"id": store_id, "name": name, "link": P.refs.store_link(store_id, slug)}
