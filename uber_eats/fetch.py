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
A fresh residential exit passes, and so does the gateway
(exit_gateway.py: a fresh gateway address on nearly every request, so a per-IP
count never builds up). So on a 403/429 or an HTML page the sessions move
one fallback step down for config.UBER_EATS_BLOCK_COOLDOWN seconds: since
2026-11-11 first to the gateway (config.UBER_EATS_FALLBACK_EXIT = "gateway";
the numbers are in config.py's Uber Eats block), and only when that is
refused too to a sticky residential exit
(config.UBER_EATS_FALLBACK_PROXY_COUNTRY). A call the gateway keeps failing
makes its LAST retry on the residential exit, for that call only. When the
cooldown ends the next call is back on the server's own IP. The same shape
as the reed / soundcloud / woolworths transports. Every step is a US
address on purpose: the address box (mapsSearchV1) answers a US caller from
Uber's own place index ("uber_places") and an Indian one from Google's
("google_places"), with different place ids and slightly different points.

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
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait as wait_futures
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from scraper_utils import debug, fanout, ladder, retry, sessions

SITE = "https://www.ubereats.com"
API = SITE + "/_p/api/"
IMPERSONATE = "chrome"
DEFAULT_LOCALE = "us"

TIMEOUT = 45
FANOUT_WORKERS = 6

HEADERS = {
    "accept": "*/*",
    "accept-language": egress.site_accept_language("uber-eats"),
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
# One session per worker thread (egress.new_session: curl_cffi, or the gateway
# exit's look-alike). Direct egress by default; after a block the sessions
# move down the fallback steps (config.uber_eats_fallback_exits(): the gateway
# exit, then a sticky residential exit) until `_fallback_until`, then go
# back to direct.
_local = threading.local()
_fallback_until = 0.0
_fallback_step = 1              # which fallback exit serves while the cooldown runs (1 = the first)
_fallback_lock = threading.Lock()


def _gateway_step(step):
    """True when fallback step `step` is the gateway exit with another exit
    configured behind it."""
    exits = config.uber_eats_fallback_exits()
    return 0 < step < len(exits) and bool(config.gateway_exit(exits[step - 1]))


def _step():
    """The fallback step a session built NOW rides: 0 = the configured exit
    (the server's own IP), 1, 2 = config.uber_eats_fallback_proxy(step)
    while the cooldown runs; one step past the gateway for the last retry of
    a call (_retrying)."""
    return ladder.current_step(_fallback_step, _fallback_until, _local, _gateway_step)


def _proxy_for_new_session(step=None):
    forced = config.uber_eats_proxy()
    if forced:
        return forced
    step = _step() if step is None else step
    return config.uber_eats_fallback_proxy(step) if step else None


def _session():
    sess = getattr(_local, "session", None)
    step = _step()
    if sess is not None and getattr(sess, "_uber_eats_step", 0) != step:
        # 2026-11-11: a session follows its step. Before, a thread that took
        # the fallback exit during a cooldown stayed on it until that failed.
        _drop_session()
        sess = None
    if sess is None:
        # None (direct), a proxy URL, or the gateway exit ("gateway")
        sess = egress.new_session(_proxy_for_new_session(step), impersonate=IMPERSONATE)
        sess._uber_eats_step = step
        _local.session = sess
    return sess


def _drop_session():
    sessions.drop(_local)


def _note_block():
    """The exit this thread's session rides was refused: new sessions move
    one fallback step down for a cooldown (own IP -> the gateway exit ->
    residential; on the last step they stay there, each on a fresh exit).
    No-op when no fallback is configured."""
    global _fallback_until, _fallback_step
    exits = config.uber_eats_fallback_exits()
    if not exits:
        return
    held = getattr(getattr(_local, "session", None), "_uber_eats_step", _step())
    if getattr(_local, "past_gateway", False) and held > (_fallback_step if time.time() < _fallback_until else 0):
        # the last retry of a call the gateway kept failing rides the step past
        # it for that call only: a refusal there is no verdict on the gateway,
        # so it must not move every session onto the residential exit
        return
    step = min(held + 1, len(exits))
    with _fallback_lock:
        if time.time() >= _fallback_until or step > _fallback_step:
            _fallback_step = step
        _fallback_until = time.time() + config.UBER_EATS_BLOCK_COOLDOWN
    if len(exits) > 1:      # how often each step is refused is the number to watch
        print(f"uber-eats: exit refused, sessions on fallback step {_fallback_step} "
              f"({exits[_fallback_step - 1]}) for {config.UBER_EATS_BLOCK_COOLDOWN} s")


def dump_debug(name, text):
    debug.dump("UBER_EATS_DEBUG_DIR", name, text, encoding="utf-8")


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
    """Run fn() under the shared retry policy, each retry on a fresh session
    / exit. While the sessions are on the gateway exit step the LAST retry of
    a call rides the next step (the residential exit), for that call only:
    a gateway failure then costs latency, not the call."""
    return retry.run_flagged(fn, config, UberEatsUpstreamError, lambda e: _drop_session(), _local)


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

# Long-lived pools (2026-10-23): their threads keep their thread-local curl
# sessions — and the sticky exits behind them — between requests. The
# per-call executor they replace opened fresh sessions/exits for every
# fan-out and threw them away when the call returned. Two levels: a fan-out
# running inside a fan-out goes to the second pool, so it neither waits on
# the workers it occupies (deadlock) nor loses its parallelism; a third
# level runs inline.
_pools = (ThreadPoolExecutor(max_workers=FANOUT_WORKERS * 4, thread_name_prefix="uber_eats-fanout-0"),
          ThreadPoolExecutor(max_workers=FANOUT_WORKERS * 4, thread_name_prefix="uber_eats-fanout-1"))


def _windowed(fns, workers):
    """Run `fns` on the pool for this nesting level, at most `workers` at a
    time; results align with `fns`. The first failure (in `fns` order)
    propagates once the callables already started have finished."""
    return fanout.windowed(_pools, "uber_eats-fanout", fns, workers)


def run_parallel(fns):
    if not fns:
        return []
    if len(fns) == 1:
        return [fns[0]()]
    return _windowed(fns, FANOUT_WORKERS)


if __name__ == "__main__":
    # Smoke test: python uber_eats/fetch.py
    hits = rpc("mapsSearchV1", {"query": "Times Square New York"})
    print("autocomplete:", [(h.get("addressLine1"), h.get("addressLine2")) for h in hits[:3]])
    store = rpc("getStoreV1", {"storeUuid": "65686398-f585-439b-ae4c-dabe058a0a60"})
    print("store:", store.get("title"), store.get("phoneNumber"), (store.get("rating") or {}).get("ratingValue"))
    feed = rpc("getSearchFeedV1", {"userQuery": "pizza"}, point={"latitude": 40.758, "longitude": -73.9855})
    print("search:", len(feed.get("feedItems") or []), feed.get("meta"))
