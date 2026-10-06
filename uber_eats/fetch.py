"""Uber Eats transport: plain curl_cffi with browser-impersonated TLS. No
browser, no login, no token (validated 2026-10-05 from direct Indian egress
and through residential US exits).

Everything the site shows is served by ONE JSON RPC layer:

    POST https://www.ubereats.com/_p/api/<rpc>?localeCode=<cc>
    headers  x-csrf-token: x        (any value; absent -> 403 "Missing csrf token")
    body     JSON args
    answer   {"status": "success", "data": ...}
             {"status": "failure", "data": {"message", "code"}}   (HTTP 200!)

  * localeCode is the site's URL prefix: `us`, `gb`, `fr`, `jp` ... The
    directory RPCs (getSeoFeedV1, getCountriesWithCitiesV1,
    getPaginatedStoresV1) only know a country through it; `en-US` style
    values answer "geo_not_configured" outside the US.
  * The delivery point is the `uev2.loc` cookie: url-quoted JSON, of which
    latitude + longitude are all the feed / search RPCs read. Pickup is the
    `uev2.diningMode=PICKUP` cookie (the body field of that name is ignored).
  * The site pins filters and the dining mode to the session, so the jar is
    cleared before every call and the cookies are sent per request.
  * getPaginatedStoresV1 derives its geo from the REFERER page
    (.../city/<slug>?page=N); without it -> "geo_not_configured".

Blocks: Uber's own bot defense, per IP. After a few hundred store / feed /
search calls from one address those RPCs answer HTTP 403
{"status":"failure","metadata":{"botdefense":{"state":"challenge",
"provider":"RECAPTCHA"}}} (seen 2026-10-05; the directory RPCs and the
address box kept answering 200, and no TLS profile or cookie set clears it).
A fresh residential exit passes. So on a 403/429 or an HTML page a worker
moves its session to a sticky residential exit
(config.uber_eats_fallback_proxy()) for config.UBER_EATS_BLOCK_COOLDOWN
seconds, the same shape as the kick transport.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  UberEatsUpstreamError  transport failure / 5xx / RPC failure   — retryable
  UberEatsBlocked        403 / 429 / HTML where JSON expected    — retryable on a new exit
  UberEatsBadRequest     RPC failure code 400 / 422              — never retried
  UberEatsNotFound       RPC failure code 404 / unknown uuid     — never retried
"""
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

SITE = "https://www.ubereats.com"
API = SITE + "/_p/api/"
IMPERSONATE = "chrome"
DEFAULT_LOCALE = "us"

TIMEOUT = 45
FANOUT_WORKERS = 6

HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/json",
    "origin": SITE,
    "x-csrf-token": "x",
}

# RPC failure messages that mean "this entity does not exist" whatever code
# rides along (the site answers some of them with code 500).
_NOT_FOUND_MESSAGES = ("invalid_uuid", "geo_not_configured", "slug_not_configured",
                       "store not found", "not_found", "invalid store uuid")


class UberEatsUpstreamError(UpstreamError):
    """Transport failure, 5xx or an RPC-level failure — retryable."""


class UberEatsBlocked(UberEatsUpstreamError, Blocked):
    """403 / 429 or an HTML body where JSON was expected — retryable."""


class UberEatsBadRequest(BadRequest):
    """The RPC rejected the args (code 400 / 422). Never retried."""


class UberEatsNotFound(NotFound):
    """Store / item / city does not exist — never retried."""


# ---- sessions ------------------------------------------------------------------
# One curl session per worker thread. Direct egress by default; after a block
# the thread's sessions go through a sticky residential exit for a cooldown.
_local = threading.local()
_fallback_until = 0.0
_fallback_lock = threading.Lock()


def _proxy_for_new_session():
    forced = config.uber_eats_proxy()
    if forced:
        return forced
    if time.time() < _fallback_until:
        return config.uber_eats_fallback_proxy()
    return None


def _session():
    sess = getattr(_local, "session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        proxy = _proxy_for_new_session()
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        _local.session = sess
    return sess


def _drop_session():
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _note_block():
    """A 403/429 on direct egress: send new sessions through a residential
    exit for a while (no-op when no fallback country is configured)."""
    global _fallback_until
    if config.uber_eats_fallback_proxy() is not None:
        with _fallback_lock:
            _fallback_until = time.time() + config.UBER_EATS_BLOCK_COOLDOWN


def dump_debug(name, text):
    dbg = os.environ.get("UBER_EATS_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass


# ---- cookies -------------------------------------------------------------------

def location_cookie(point):
    """{latitude, longitude[, address ...]} -> the uev2.loc cookie value."""
    payload = {"latitude": point["latitude"], "longitude": point["longitude"]}
    for key in ("address", "reference", "referenceType", "type", "addressComponents"):
        if point.get(key):
            payload[key] = point[key]
    return quote(json.dumps(payload, separators=(",", ":")))


def _cookie_header(point, dining_mode):
    parts = []
    if point:
        parts.append("uev2.loc=" + location_cookie(point))
    if dining_mode:
        parts.append("uev2.diningMode=" + dining_mode)
    return "; ".join(parts) or None


# ---- requests ------------------------------------------------------------------

def _raise_failure(body, label):
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    message = str(data.get("message") or "").strip()
    code = str(data.get("code") or "")
    lowered = message.lower()
    if code == "404" or any(m in lowered for m in _NOT_FOUND_MESSAGES):
        raise UberEatsNotFound(f"{label} not found" + (f" ({message})" if message and len(message) < 80 else ""))
    if code in ("400", "422"):
        raise UberEatsBadRequest(message or f"upstream rejected {label}")
    raise UberEatsUpstreamError(f"{label} failed upstream: {message[:200] or code or 'unknown error'}")


def _retrying(fn):
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except UberEatsUpstreamError as e:      # includes UberEatsBlocked
            last = e
            _drop_session()
        if attempt < config.MAX_RETRIES:
            time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def rpc(name, body=None, *, locale=None, point=None, dining_mode=None, referer=None, label=None):
    """POST one RPC -> its `data` member.

    locale       site prefix / country code (`us`, `gb` ...); default us
    point        {latitude, longitude, ...} delivery point (uev2.loc cookie)
    dining_mode  "PICKUP" to switch the feed / search / store to pickup
    referer      page path the call pretends to come from (needed by
                 getPaginatedStoresV1)
    """
    label = label or name
    url = f"{API}{name}?localeCode={locale or DEFAULT_LOCALE}"
    headers = dict(HEADERS)
    headers["referer"] = SITE + (referer or "/")
    cookie = _cookie_header(point, dining_mode)
    if cookie:
        headers["cookie"] = cookie

    def once():
        sess = _session()
        try:
            sess.cookies.clear()
        except Exception:
            pass
        try:
            resp = sess.post(url, json=body or {}, headers=headers, timeout=TIMEOUT)
        except Exception as e:
            raise UberEatsUpstreamError(f"request failed: {type(e).__name__}: {e}")
        status = resp.status_code
        text = resp.text or ""
        if status in (403, 429):
            dump_debug("blocked", text)
            _note_block()
            raise UberEatsBlocked(f"HTTP {status} on {label}")
        if not text.lstrip().startswith("{"):
            if status >= 500:
                raise UberEatsUpstreamError(f"HTTP {status} on {label}")
            dump_debug("nonjson", text)
            _note_block()
            raise UberEatsBlocked(f"{label} returned HTML, not JSON")
        try:
            payload = resp.json()
        except Exception:
            dump_debug("badjson", text)
            raise UberEatsUpstreamError(f"could not parse JSON from {label}")
        if not isinstance(payload, dict):
            raise UberEatsUpstreamError(f"unexpected body from {label}")
        if payload.get("status") != "success":
            if status == 404 and "ERR_MISSING_HANDLER" in text:
                raise UberEatsUpstreamError(f"{label} is no longer served by the site")
            _raise_failure(payload, label)
        return payload.get("data")

    return _retrying(once)


def rpc_optional(name, body=None, **kwargs):
    """Like rpc but a NotFound / BadRequest yields None (optional parts)."""
    try:
        return rpc(name, body, **kwargs)
    except (UberEatsNotFound, UberEatsBadRequest):
        return None


# ---- fan-out -------------------------------------------------------------------

def run_parallel(fns):
    if not fns:
        return []
    if len(fns) == 1:
        return [fns[0]()]
    with ThreadPoolExecutor(max_workers=min(FANOUT_WORKERS, len(fns))) as ex:
        futures = [ex.submit(fn) for fn in fns]
        return [f.result() for f in futures]


if __name__ == "__main__":
    # Smoke test: python uber_eats/fetch.py
    hits = rpc("mapsSearchV1", {"query": "Times Square New York"})
    print("autocomplete:", [(h.get("addressLine1"), h.get("addressLine2")) for h in hits[:3]])
    store = rpc("getStoreV1", {"storeUuid": "65686398-f585-439b-ae4c-dabe058a0a60"})
    print("store:", store.get("title"), store.get("phoneNumber"), (store.get("rating") or {}).get("ratingValue"))
    feed = rpc("getSearchFeedV1", {"userQuery": "pizza"}, point={"latitude": 40.758, "longitude": -73.9855})
    print("search:", len(feed.get("feedItems") or []), feed.get("meta"))
