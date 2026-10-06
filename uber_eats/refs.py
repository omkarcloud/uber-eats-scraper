"""Uber Eats reference parsing: ONE param per input that auto-detects its
forms (tripadvisor QueryOrIdField convention — never a sibling `url`/`id`
pair).

  store         65686398-f585-439b-ae4c-dabe058a0a60            (store uuid)
                | ZWhjmPWFQ5uuTNq-BYoKYA                         (the id in store links)
                | https://www.ubereats.com/store/five-guys-253-w-42nd-st/ZWhjmPWFQ5uuTNq-BYoKYA
                | https://www.ubereats.com/gb/store/<slug>/<id>?diningMode=PICKUP
  item          2556d497-2d8a-5010-8aba-dc31a397ceff            (item uuid; needs `store`)
                | https://www.ubereats.com/store/<slug>/<id>/<section>/<subsection>/<item>
  section       a menu section uuid
  location      "350 5th Ave, New York"  (any address / place text)
                | "40.7484,-73.9857"     (latitude,longitude)
  city          new-york-city | https://www.ubereats.com/city/new-york-city
                | https://www.ubereats.com/gb/city/london-eng   (carries its country)
  category      pizza | https://www.ubereats.com/category/new-york-city/pizza
  neighborhood  midtown-west-manhattan-new-york-city | .../neighborhood/<slug>
  region        ny | https://www.ubereats.com/region/ny
  brand         mcdonalds | https://www.ubereats.com/brand/mcdonalds
                | https://www.ubereats.com/brand-city/new-york-city/mcdonalds

The id in a store link is the store uuid's 16 bytes in url-safe base64, so
the two convert offline. Site links may carry a locale prefix (/gb, /fr-en,
/en-US ...): the resolvers return it as `country` when it names one.
"""
import base64
import re
import uuid as _uuid
from urllib.parse import quote, unquote, urlparse

SITE = "https://www.ubereats.com"

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_B64_RE = re.compile(r"^[A-Za-z0-9_\-]{22}$")
_SLUG_RE = re.compile(r"^[^\s/?#]{1,120}$")
_LOCALE_RE = re.compile(r"^[a-z]{2}(-[a-z]{2})?$", re.I)
_LATLNG_RE = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")
_PAGES = {"store", "city", "category", "neighborhood", "region", "brand", "brand-city",
          "near-me", "feed", "search", "location", "marketing", "closest"}


# ---- id <-> link conversions -----------------------------------------------------

def encode_uuid(value):
    """Store uuid -> the 22-char id used in store links (None if not a uuid)."""
    try:
        return base64.urlsafe_b64encode(_uuid.UUID(str(value)).bytes).decode().rstrip("=")
    except (ValueError, AttributeError, TypeError):
        return None


def decode_uuid(value):
    """The 22-char id of a store link -> the store uuid (None if invalid)."""
    try:
        raw = base64.urlsafe_b64decode(str(value) + "==")
        return str(_uuid.UUID(bytes=raw)) if len(raw) == 16 else None
    except (ValueError, TypeError):
        return None


def _prefix(country):
    country = (country or "").lower()
    return f"/{country}" if country and country != "us" else ""


def absolute(path):
    """Site-relative path -> absolute link (query string dropped); passes
    absolute links through; app deep links (ubereats://) -> None."""
    if not path or not isinstance(path, str):
        return None
    if path.startswith("//"):
        path = "https:" + path
    if path.startswith("http"):
        return path.split("?")[0]
    if not path.startswith("/"):
        return None
    path = path.split("?")[0]
    if path.startswith("/us/"):        # the US has no prefix on canonical links
        path = path[3:]
    return SITE + path


def store_link(store_id, slug=None, country=None):
    encoded = encode_uuid(store_id)
    if not encoded:
        return None
    return f"{SITE}{_prefix(country)}/store/{quote(slug, safe='') if slug else 'store'}/{encoded}"


def item_link(store_id, section_id, subsection_id, item_id, slug=None, country=None):
    base = store_link(store_id, slug, country)
    if not (base and section_id and subsection_id and item_id):
        return None
    return f"{base}/{section_id}/{subsection_id}/{item_id}"


def city_link(slug, country=None):
    return f"{SITE}{_prefix(country)}/city/{slug}" if slug else None


def category_link(city, category, country=None):
    return f"{SITE}{_prefix(country)}/category/{city}/{category}" if city and category else None


def neighborhood_link(slug, country=None):
    return f"{SITE}{_prefix(country)}/neighborhood/{slug}" if slug else None


def region_link(slug, country=None):
    return f"{SITE}{_prefix(country)}/region/{slug}" if slug else None


def brand_link(slug, city=None, country=None):
    if not slug:
        return None
    if city:
        return f"{SITE}{_prefix(country)}/brand-city/{city}/{slug}"
    return f"{SITE}{_prefix(country)}/brand/{slug}"


# ---- link parsing ----------------------------------------------------------------

def _is_url(value):
    lowered = value.lower()
    return lowered.startswith(("http://", "https://", "//", "ubereats.com/", "www.ubereats.com/"))


def split_path(value):
    """An ubereats.com link or site path -> (country | None, [segments]).
    The leading locale prefix (/gb, /fr-en, /en-US) is stripped and returned
    as a lower-case ISO country code. Raises ValueError for another site."""
    value = str(value or "").strip()
    if value.startswith("/") and not value.startswith("//"):
        path = value
    else:
        url = value
        if url.startswith("//"):
            url = "https:" + url
        elif not url.startswith("http"):
            url = "https://" + url
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not (host == "ubereats.com" or host.endswith(".ubereats.com")):
            raise ValueError("not an ubereats.com link")
        path = parsed.path
    segments = [unquote(s) for s in path.split("?")[0].split("#")[0].split("/") if s]
    country = None
    if segments and segments[0].lower() not in _PAGES and _LOCALE_RE.match(segments[0]):
        first, _, second = segments[0].lower().partition("-")
        # /gb -> gb, /fr-en -> fr (country-language), /en-US -> us (language-COUNTRY)
        country = second if segments[0][-2:].isupper() and second else first
        segments = segments[1:]
    return country, segments


def _after(segments, marker):
    for index, segment in enumerate(segments):
        if segment.lower() == marker:
            return segments[index + 1:]
    return None


def resolve_store(value):
    """Store uuid, link id or any store link -> the store uuid."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("store is required")
    if _is_url(value) or value.startswith("/"):
        try:
            _, segments = split_path(value)
        except ValueError:
            raise ValueError("store must be an ubereats.com store link or a store id")
        tail = _after(segments, "store")
        if not tail or len(tail) < 2:
            raise ValueError("store link must look like https://www.ubereats.com/store/<name>/<id>")
        value = tail[1]
    if _UUID_RE.match(value):
        return value.lower()
    if _B64_RE.match(value):
        decoded = decode_uuid(value)
        if decoded:
            return decoded
    raise ValueError("store must be a store uuid, the id from a store link (ZWhjmPWFQ5uuTNq-BYoKYA) "
                     "or an ubereats.com store link")


def resolve_item(value):
    """Item uuid or a full item link -> {"item", "store", "section",
    "subsection"} (the last three are None for a bare uuid)."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("item is required")
    out = {"item": None, "store": None, "section": None, "subsection": None}
    if _is_url(value) or value.startswith("/"):
        try:
            _, segments = split_path(value)
        except ValueError:
            raise ValueError("item must be an ubereats.com item link or an item id")
        tail = _after(segments, "store")
        if not tail or len(tail) < 5 or not all(_UUID_RE.match(s) for s in tail[2:5]):
            raise ValueError("item link must look like "
                             "https://www.ubereats.com/store/<name>/<id>/<section>/<subsection>/<item>")
        store = decode_uuid(tail[1]) if _B64_RE.match(tail[1]) else (tail[1].lower() if _UUID_RE.match(tail[1]) else None)
        if not store:
            raise ValueError("item link carries an invalid store id")
        out.update(store=store, section=tail[2].lower(), subsection=tail[3].lower(), item=tail[4].lower())
        return out
    if not _UUID_RE.match(value):
        raise ValueError("item must be an item uuid or an ubereats.com item link")
    out["item"] = value.lower()
    return out


def resolve_section(value):
    value = str(value or "").strip()
    if not _UUID_RE.match(value):
        raise ValueError("section must be a menu section id (uuid) from the store's menu")
    return value.lower()


def resolve_location(value):
    """Address text or 'lat,lng' -> {"latitude", "longitude"} | {"query"}."""
    value = " ".join(str(value or "").split())
    if not value:
        raise ValueError("location is required")
    match = _LATLNG_RE.match(value)
    if match:
        lat, lng = float(match.group(1)), float(match.group(2))
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError("location coordinates are out of range (latitude,longitude)")
        return {"latitude": lat, "longitude": lng}
    if len(value) < 3:
        raise ValueError("location must be an address / place name or 'latitude,longitude'")
    if len(value) > 200:
        raise ValueError("location is too long (max 200 characters)")
    return {"query": value}


def _slug_ref(value, marker, name, example, position=0):
    """Bare slug or a site link whose path holds /<marker>/<...> ->
    {"slug", "country"}; `position` picks the segment after the marker."""
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    country = None
    if _is_url(value) or value.startswith("/"):
        try:
            country, segments = split_path(value)
        except ValueError:
            raise ValueError(f"{name} must be an ubereats.com link or a slug ({example})")
        tail = None
        for mark in (marker if isinstance(marker, tuple) else (marker,)):
            tail = _after(segments, mark)
            if tail is not None:
                break
        if not tail or len(tail) <= position:
            raise ValueError(f"{name} link does not point at a {name} page ({example})")
        value = tail[position]
    value = value.strip().lower()
    if not _SLUG_RE.match(value):
        raise ValueError(f"{name} must be a slug ({example}) or an ubereats.com link")
    return {"slug": value, "country": country}


def resolve_city(value):
    """City slug or a city / category / brand-city link -> {"slug", "country"}."""
    return _slug_ref(value, ("city", "category", "brand-city"), "city", "new-york-city")


def resolve_category(value):
    """Category slug or a category link -> {"slug", "country", "city"}."""
    raw = str(value or "").strip()
    if _is_url(raw) or raw.startswith("/"):
        try:
            country, segments = split_path(raw)
        except ValueError:
            raise ValueError("category must be an ubereats.com category link or a slug (pizza)")
        tail = _after(segments, "category")
        if tail and len(tail) >= 2:
            return {"slug": tail[1].lower(), "country": country, "city": tail[0].lower()}
        tail = _after(segments, "near-me")
        if tail:
            return {"slug": tail[0].lower(), "country": country, "city": None}
        raise ValueError("category link must look like https://www.ubereats.com/category/<city>/<category>")
    out = _slug_ref(raw, "category", "category", "pizza")
    out["city"] = None
    return out


def resolve_neighborhood(value):
    return _slug_ref(value, "neighborhood", "neighborhood", "midtown-west-manhattan-new-york-city")


def resolve_region(value):
    value = str(value or "").strip()
    if not (_is_url(value) or value.startswith("/")):
        value = "-".join(value.split())        # a region name: "New York" -> new-york
    return _slug_ref(value, "region", "region", "ny")


def resolve_brand(value):
    """Brand slug or a brand / brand-city link -> {"slug", "country", "city"}."""
    raw = str(value or "").strip()
    if _is_url(raw) or raw.startswith("/"):
        try:
            country, segments = split_path(raw)
        except ValueError:
            raise ValueError("brand must be an ubereats.com brand link or a slug (mcdonalds)")
        tail = _after(segments, "brand-city")
        if tail and len(tail) >= 2:
            return {"slug": tail[1].lower(), "country": country, "city": tail[0].lower()}
        tail = _after(segments, "brand")
        if tail:
            return {"slug": tail[0].lower(), "country": country, "city": None}
        raise ValueError("brand link must look like https://www.ubereats.com/brand/mcdonalds")
    out = _slug_ref(raw, "brand", "brand", "mcdonalds")
    out["city"] = None
    return out
