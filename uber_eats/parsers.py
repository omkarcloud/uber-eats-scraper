"""Uber Eats normalizers: the site's RPC payloads -> one clean snake_case
shape per entity.

Output conventions (shared with the other scrapers here): `link` for page
URLs (always absolute), `image` / `logo` / `banner` for pictures, `*_count`
for counters, `is_*` / `has_*` for booleans, ISO-8601 UTC for timestamps,
numbers as numbers, prices as a numeric amount in major units next to a
`currency` code, null for missing. Entity vocabulary:

  store card     {id, name, link, image, rating, review_count, ...,
                  delivery_time, delivery_fee, distance, offers, location}
  menu item      {id, name, description, price, image, link, ...}
  customization  {id, title, min_selections, max_selections, options[]}

Uber sends every price as an integer of 1/100 major units whatever the
currency (JPY 13,200 arrives as 1320000), so `money()` always divides by 100.

Deliberately dropped as noise:
  * `tracking`, `trackingCode`, `analyticsLabel`, `*AnalyticsData`,
    `promoTrackings`, `storeSessionUuid`, `predictionUUID`, `timing` and
    every other analytics / session id;
  * presentation: `textFormat` HTML twins of `text`, rich-text font / colour
    trees (flattened to their text), `spanCount`, `displayType`,
    `quickAddConfig`, `itemThumbnailElements`, `imageOverlayElements`
    (its tag text is kept as a label), `layout`, map marker colours,
    bottom-sheet copy (`moreInfoSheet` buttons, `orderForLaterInfo` /
    `exploreMoreStoresInfo` dialog strings), `seoMeta` boilerplate;
  * viewer state that is meaningless for an anonymous reader: `favorite`,
    `isFavorite`, `eaterConsent`, `isLost`, group-order config, cart /
    checkout flags (`disableOrderInstruction`, `fulfillmentIssueOptions`,
    `specialInstructionHintText`), membership upsells;
  * duplicates: `sanitizedTitle` (= title), `meta.sectionHoursInfo`
    (= hours), `metaJson` schema.org twin of the same fields, the smaller
    renditions of each image (the largest is kept), `titleBadge` /
    `itemDescriptionBadge` / `headingPrimary` (= title / description),
    `priceTagline` (= price; its calorie suffix is kept as `calories`),
    review `timeSinceReview` / `formattedDate` (= created_at) and the
    generic `avatarUrl` placeholder;
  * scheduling grids (`adaptedDeliveryHoursInfos`, `timeWindowPicker`):
    hundreds of 30-minute slots per store, only useful while ordering.
"""
import html as _html
import re
from datetime import datetime, timezone

from uber_eats import refs

_TAG_RE = re.compile(r"<[^>]+>")
_NUM_RE = re.compile(r"\d[\d.,   ]*\d|\d")
_LIKED_RE = re.compile(r"(\d{1,3})\s*%\s*\(\s*(\d[\d,.]*)\s*\)")
_CAL_RE = re.compile(r"(\d[\d,]*)(?:\s*[-–]\s*(\d[\d,]*))?\s*(?:k?cal)", re.I)
_COUNT_IN_TEXT_RE = re.compile(r"(\d[\d,]*)")


# ---- value helpers ------------------------------------------------------------
# (kept local so the package stands alone, like the other site packages)

def to_int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def to_float(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def text(value):
    """Trimmed single-line string or None."""
    if isinstance(value, dict):
        value = value.get("text")
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value or None


def lower(value):
    value = text(value)
    return value.lower() if value else None


def as_list(value):
    return value if isinstance(value, list) else []


def as_dict(value):
    return value if isinstance(value, dict) else {}


def money(cents):
    """Uber's integer price (1/100 major units) -> float amount, or None."""
    cents = to_float(cents)
    if cents is None:
        return None
    return round(cents / 100.0, 2)


def parse_number(value):
    """First number in a display string -> float ('$8.95 Delivery Fee' ->
    8.95, '2,49 €' -> 2.49, '11,748.2 km' -> 11748.2, '￥13,200' -> 13200)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        return None
    match = _NUM_RE.search(value)
    if not match:
        return None
    token = re.sub(r"[   ]", "", match.group(0))
    if "," in token and "." in token:
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "," in token:
        head, _, tail = token.rpartition(",")
        token = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else token.replace(",", "")
    try:
        return float(token)
    except ValueError:
        return None


def parse_count(value):
    """'8,000+' / '3000+' / 8000 -> 8000 (the site's rounded-down count)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if not isinstance(value, str):
        return None
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else None


def iso_datetime(value):
    """ISO string / epoch -> 'YYYY-MM-DDTHH:MM:SSZ' (UTC) or None."""
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, (int, float)):
            stamp = float(value)
            if stamp > 1e12:
                stamp /= 1000.0
            moment = datetime.fromtimestamp(stamp, tz=timezone.utc)
        else:
            moment = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError, OSError):
        return None


def clock(minutes):
    """Minutes after midnight -> 'HH:MM' (1439 -> '23:59')."""
    minutes = to_int(minutes)
    if minutes is None or minutes < 0:
        return None
    minutes %= 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def strip_html(value):
    """HTML fragment -> plain text (block tags become line breaks)."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = re.sub(r"(?i)<\s*(br|/p|/h[1-6]|/li|/ul|/ol)\s*/?>", "\n", value)
    value = _html.unescape(_TAG_RE.sub("", value))
    lines = [" ".join(line.split()) for line in value.split("\n")]
    return "\n".join(line for line in lines if line) or None


def rich_text(node):
    """A richText tree -> its plain text (icons dropped)."""
    node = as_dict(node)
    if isinstance(node.get("richText"), dict):
        node = node["richText"]
    parts = []
    for element in as_list(node.get("richTextElements")):
        inner = as_dict(as_dict(as_dict(element).get("text")).get("text"))
        if isinstance(inner.get("text"), str):
            parts.append(inner["text"])
    joined = " ".join("".join(parts).split())
    return joined or text(node.get("accessibilityText"))


def best_image(node):
    """{items: [{url, width}]} / [{url, width}] / str -> the largest URL."""
    if isinstance(node, str):
        return node.strip() or None
    items = node.get("items") if isinstance(node, dict) else node
    best, best_width = None, -1
    for item in as_list(items):
        if not isinstance(item, dict) or not item.get("url"):
            continue
        width = to_int(item.get("width")) or 0
        if width > best_width:
            best, best_width = item["url"], width
    return best


def _image(value):
    value = text(value)
    if value and value.startswith("/"):
        return refs.SITE + value
    return value


def minutes_range(value):
    """'10–22 Min' / '17 min' / '39～64 分' -> (min, max) minutes; a clock
    time ('6:01AM') or anything else -> (None, None)."""
    if not isinstance(value, str) or re.search(r"\d\s*:\s*\d", value):
        return None, None
    numbers = [int(n) for n in re.findall(r"\d+", value)]
    if not numbers or len(numbers) > 2:
        return None, None
    return numbers[0], numbers[-1]


def distance(node):
    """{text: '0.2 mi'} / '0.2 mi' -> {value, unit}."""
    raw = text(node)
    if not raw:
        return None
    value = parse_number(raw)
    unit = re.sub(r"[\d.,\s]", "", raw).lower() or None
    if value is None:
        return None
    return {"value": value, "unit": unit}


# ---- locations ----------------------------------------------------------------

def place_suggestion(row):
    row = as_dict(row)
    return {
        "id": text(row.get("id")),
        "provider": text(row.get("provider")),
        "name": text(row.get("addressLine1")),
        "address": text(row.get("addressLine2")),
        "categories": [c.lower() for c in as_list(row.get("categories")) if isinstance(c, str)],
    }


def delivery_location(row, query=None):
    """getDeliveryLocationV1 / reverse-geocode data -> one location object."""
    row = as_dict(row)
    address = as_dict(row.get("address"))
    components = as_dict(row.get("addressComponents"))
    coordinate = as_dict(row.get("coordinate"))
    return {
        "query": query,
        "name": text(address.get("title")) or text(row.get("title")) or text(row.get("name")),
        "address": text(address.get("eaterFormattedAddress")) or text(row.get("fullAddress")),
        "city": text(components.get("city")),
        "region": text(components.get("firstLevelSubdivisionCode")),
        "postal_code": text(components.get("postalCode")),
        "country": text(components.get("countryCode")),
        "latitude": to_float(row.get("latitude") if row.get("latitude") is not None else coordinate.get("latitude")),
        "longitude": to_float(row.get("longitude") if row.get("longitude") is not None else coordinate.get("longitude")),
        "place_id": text(row.get("reference")) or text(row.get("id")),
        "provider": text(row.get("referenceType")) or text(row.get("provider")),
    }


# ---- store cards (feed / search) ------------------------------------------------

def _badge_texts(rows):
    return [t for t in (text(as_dict(r).get("text")) for r in as_list(rows)) if t]


def store_card(store, country=None):
    """One feed / search / carousel store card."""
    store = as_dict(store)
    payload = as_dict(as_dict(store.get("tracking")).get("storePayload"))
    rating_info = as_dict(payload.get("ratingInfo"))
    eta = as_dict(as_dict(payload.get("etdInfo")).get("dropoffETARange"))
    store_id = text(store.get("storeUuid")) or text(payload.get("storeUUID")) or text(store.get("uuid"))

    is_new, fee, is_surge, dist, status, eta_text = False, None, None, None, [], None
    for badge in as_list(store.get("meta")) + as_list(store.get("meta3")) + as_list(store.get("meta4")):
        badge = as_dict(badge)
        kind = badge.get("badgeType")
        label = text(badge.get("text"))
        if kind == "NEW_STORE":
            is_new = True
        elif kind == "FARE":
            fare = as_dict(as_dict(badge.get("badgeData")).get("fare"))
            fee = parse_number(fare.get("deliveryFee") or label)
            is_surge = fare.get("isSurge") if isinstance(fare.get("isSurge"), bool) else None
        elif kind == "DISTANCE":
            dist = distance(label)
        elif kind == "ETD":
            eta_text = label
        elif label and label not in status:
            status.append(label)

    offers = _badge_texts(store.get("signposts"))
    for label in _badge_texts(store.get("meta2")):
        if label not in offers:
            offers.append(label)
    badges = [t for t in (text(as_dict(e).get("accessibilityText")) or rich_text(as_dict(e).get("content"))
                          for e in as_list(store.get("endorsements"))) if t]

    eta_min, eta_max = to_int(eta.get("min")), to_int(eta.get("max"))
    if eta_min is None and eta_text:
        eta_min, eta_max = minutes_range(eta_text)
    rating = to_float(text(as_dict(store.get("rating")).get("text")))
    if rating is None and rating_info.get("storeRatingScore"):
        rating = round(to_float(rating_info.get("storeRatingScore")), 1)
    marker = as_dict(store.get("mapMarker"))
    latitude, longitude = to_float(marker.get("latitude")), to_float(marker.get("longitude"))
    action = text(store.get("actionUrl")) or ""
    slug = None
    try:
        link_country, segments = refs.split_path(action) if action.startswith("/") else (None, [])
        if len(segments) >= 2 and segments[0] == "store":
            slug = segments[1]
    except ValueError:
        link_country = None
    return {
        "id": store_id,
        "name": text(store.get("title")),
        "link": refs.store_link(store_id, slug, link_country or country),
        "image": best_image(store.get("image")) or _image(store.get("heroImageUrl")),
        "rating": rating,
        "review_count": parse_count(rating_info.get("ratingCount")),
        "is_new": is_new,
        "is_orderable": payload.get("isOrderable") if isinstance(payload.get("isOrderable"), bool) else None,
        "availability": lower(payload.get("storeAvailablityState")),
        "status": " · ".join(status) or None,
        "delivery_time": {"min_minutes": eta_min, "max_minutes": eta_max, "text": eta_text},
        "delivery_fee": fee,
        "is_surge_pricing": is_surge,
        "distance": dist,
        "offers": offers,
        "badges": badges,
        "location": {"latitude": latitude, "longitude": longitude} if latitude or longitude else None,
    }


def search_item(row, store_id=None, slug=None, country=None):
    """A dish / product a search result matched inside a store."""
    row = as_dict(row)
    item_id = text(row.get("uuid"))
    section, subsection = text(row.get("sectionUuid")), text(row.get("subsectionUuid"))
    price_text = next(iter(_badge_texts(row.get("subtitles"))), None)
    images = as_list(row.get("images"))
    return {
        "id": item_id,
        "name": text(row.get("title")),
        "link": refs.item_link(store_id, section, subsection, item_id, slug, country),
        "price": parse_number(price_text),
        "image": best_image(images[0]) if images else None,
        "section_id": section,
        "subsection_id": subsection,
    }


def feed_stores(feed, country=None):
    """getFeedV1 / getSearchFeedV1 data -> flat, deduped store cards (search
    cards carry the items the query matched as `matched_items`)."""
    out, seen = [], set()
    for item in as_list(as_dict(feed).get("feedItems")):
        item = as_dict(item)
        mini = as_dict(item.get("miniStoreWithItems"))
        store = item.get("store") if isinstance(item.get("store"), dict) else mini.get("store")
        if not isinstance(store, dict):
            continue
        card = store_card(store, country)
        if not card["id"] or card["id"] in seen:
            continue
        seen.add(card["id"])
        if mini:
            link_country, segments = refs.split_path(card["link"]) if card["link"] else (None, [])
            slug = segments[1] if len(segments) >= 3 else None
            card["matched_items"] = [search_item(r, card["id"], slug, link_country or country)
                                     for r in as_list(mini.get("items"))
                                     if isinstance(r, dict) and r.get("uuid")]   # skips the "View store" button
        out.append(card)
    return out


def feed_collections(feed, country=None):
    """The carousels of the home feed: store shelves ('National favorites',
    'Today's offers' ...) and item shelves from one store."""
    out = []
    for item in as_list(as_dict(feed).get("feedItems")):
        item = as_dict(item)
        kind = item.get("type")
        if kind in ("REGULAR_CAROUSEL", "FEATURED_STORES"):
            body = as_dict(item.get("carousel") or item.get("payload"))
            stores = [store_card(s, country) for s in as_list(body.get("stores")) if isinstance(s, dict)]
            stores = [s for s in stores if s["id"]]
            if not stores:
                continue
            out.append({
                "id": text(item.get("uuid")),
                "type": "stores",
                "title": text(as_dict(as_dict(body.get("header")).get("title")).get("text")),
                "subtitle": text(as_dict(as_dict(body.get("header")).get("subtitle")).get("text")),
                "store_count": len(stores),
                "stores": stores,
            })
        elif kind == "CATALOG_ITEMS_CAROUSEL_PAYLOAD":
            body = as_dict(item.get("payload"))
            header = as_dict(body.get("header"))
            store_id = text(body.get("storeUuid"))
            items = [menu_item(as_dict(r).get("catalogItem"), store_id=text(as_dict(r).get("storeUUID")) or store_id,
                               country=country)
                     for r in as_list(body.get("items")) if isinstance(as_dict(r).get("catalogItem"), dict)]
            if not items:
                continue
            out.append({
                "id": text(item.get("uuid")),
                "type": "items",
                "title": text(as_dict(header.get("title")).get("text")),
                "subtitle": text(as_dict(header.get("subtitle")).get("text")),
                "store_id": store_id,
                "store_link": refs.store_link(store_id, None, country),
                "item_count": len(items),
                "items": items,
            })
    return out


def _snake(name):
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", str(name))
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# ---- directory (SEO) store cards --------------------------------------------------

def seo_store_card(row, description=None, country=None):
    """A store card of the city / category / neighborhood directory pages."""
    row = as_dict(row)
    store_id = text(row.get("uuid"))
    meta = as_dict(row.get("meta"))
    location = as_dict(row.get("location"))
    promotion = as_dict(row.get("promotion"))
    eta_text = text(as_dict(row.get("etaRange")).get("text"))
    eta_min, eta_max = minutes_range(eta_text)
    latitude, longitude = to_float(location.get("latitude")), to_float(location.get("longitude"))
    fee = meta.get("deliveryFee")
    fee = parse_number(as_dict(fee).get("text") if isinstance(fee, dict) else fee) \
        if fee is not None else parse_number(text(as_dict(row.get("fareBadge")).get("text")))
    offers = [t for t in (text(promotion.get("text")),) if t]
    return {
        "id": store_id,
        "name": text(row.get("title")),
        "link": refs.store_link(store_id, text(row.get("slug")), country),
        "slug": text(row.get("slug")),
        "image": best_image(row.get("heroImage")) or _image(row.get("heroImageUrl")),
        "description": description,
        "price_range": text(meta.get("priceBucket")),
        "cuisines": [c for c in (text(c) for c in as_list(meta.get("categories"))) if c],
        "is_open": row.get("isOpen") if isinstance(row.get("isOpen"), bool) else None,
        "is_chain": row.get("isChain") if isinstance(row.get("isChain"), bool) else None,
        "status": text(row.get("closedMessage")),
        "delivery_time": {"min_minutes": eta_min, "max_minutes": eta_max, "text": eta_text},
        "delivery_fee": fee,
        "offers": offers,
        "offer_description": text(promotion.get("description")),
        "dining_modes": [m.lower() for m in as_list(row.get("modalities")) if isinstance(m, str)],
        "badges": [t for t in (text(as_dict(b).get("text")) for b in as_list(row.get("attributeBadgeList"))) if t]
                  + ([text(as_dict(row.get("endorsement")).get("text"))]
                     if text(as_dict(row.get("endorsement")).get("text")) else []),
        "location": {
            "address": text(location.get("formattedAddress")),
            "latitude": latitude if latitude or longitude else None,
            "longitude": longitude if latitude or longitude else None,
        },
    }


def seo_stores(element, country=None):
    """A `stores` element / getPaginatedStoresV1 answer -> ordered cards."""
    element = as_dict(element)
    stores_map = as_dict(element.get("storesMap"))
    content = as_dict(element.get("seoContent"))
    order = []
    for item in as_list(element.get("feedItems")):
        item = as_dict(item)
        rows = as_list(item.get("stores")) if item.get("type") == "STORES" else [item]
        for row in rows:
            uuid = text(as_dict(row).get("uuid"))
            if uuid and uuid not in order:
                order.append(uuid)
    for uuid in stores_map:
        if uuid not in order:
            order.append(uuid)
    out = []
    for uuid in order:
        row = stores_map.get(uuid)
        if not isinstance(row, dict):
            continue
        blurb = " ".join(t for t in (text(as_dict(c).get("text"))
                                     for c in as_list(as_dict(content.get(uuid)).get("content"))) if t) or None
        out.append(seo_store_card(row, blurb, country))
    return out


def link_row(row):
    """A linkBlock entry -> {name, link, label} with its site path kept for
    slug extraction by the caller."""
    row = as_dict(row)
    return {"name": text(row.get("text")) or text(row.get("title")),
            "path": text(row.get("href")),
            "label": text(row.get("label"))}


def faqs(element):
    out = []
    for row in as_list(as_dict(element).get("qa")):
        row = as_dict(row)
        question = strip_html(row.get("questionFormat")) or text(row.get("question"))
        answer = strip_html(row.get("answerFormat")) or text(row.get("answer"))
        if question:
            out.append({"question": question, "answer": answer})
    return out


def elements_by_id(feed):
    """getSeoFeedV1 data -> {element id: element}."""
    return {as_dict(e).get("id"): e for e in as_list(as_dict(feed).get("elements"))
            if isinstance(e, dict) and e.get("id")}


def page_text(elements):
    """The page's prose blocks (content.N.text) as one plain-text string."""
    blocks = [strip_html(as_dict(e).get("value")) for key, e in sorted(elements.items())
              if isinstance(key, str) and key.startswith("content.")]
    return "\n\n".join(b for b in blocks if b) or None


# ---- menu ---------------------------------------------------------------------

def _promotion(node):
    node = as_dict(node)
    kind = node.get("type")
    if not kind:
        return None
    body = as_dict(node.get(kind))
    out = {"type": _snake(re.sub(r"ItemPromotion$|Promotion$", "", kind) or kind)}
    for src, dst in (("buyQuantity", "buy_quantity"), ("getQuantity", "get_quantity"),
                     ("maxRedemptionCount", "max_redemptions")):
        out[dst] = to_int(body.get(src))
    return out


def _quantity(node, key):
    node = as_dict(node)
    direct = to_float(node.get(key + "Number"))
    if direct is not None:
        return direct
    scaled = as_dict(node.get(key))
    base, exponent = to_float(scaled.get("base")), to_int(scaled.get("exponent"))
    if base is None or exponent is None:
        return None
    return round(base * (10 ** exponent), 5)


def _unit(name):
    name = text(name)
    return name.replace("MEASUREMENT_TYPE_", "").lower() if name else None


def _purchase(info):
    """purchaseInfo -> how a grocery product is sold (None for dishes)."""
    info = as_dict(info)
    options = as_list(info.get("purchaseOptions"))
    if not options:
        return None
    option = as_dict(options[0])
    constraints = option.get("quantityConstraintsV2")
    return {
        "sold_by": _unit(as_dict(option.get("soldByUnit")).get("measurementType")),
        "priced_by": _unit(as_dict(as_dict(info.get("pricingInfo")).get("pricedByUnit")).get("measurementType")),
        "min_quantity": _quantity(constraints, "minPermitted"),
        "max_quantity": _quantity(constraints, "maxPermitted"),
        "quantity_step": _quantity(constraints, "increment"),
    }


def _item_labels(row):
    labels = []
    for overlay in as_list(row.get("imageOverlayElements")):
        payload = as_dict(as_dict(as_dict(overlay).get("element")).get("payload"))
        for tag in as_list(as_dict(payload.get("tagsPayload")).get("tags")):
            label = text(as_dict(tag).get("text"))
            if label and label not in labels:
                labels.append(label)
    for source in (row.get("endorsement"), row.get("endorsementV2")):
        label = text(as_dict(source).get("text"))
        if label and label not in labels:
            labels.append(label)
    for tag in as_list(row.get("endorsementTags")):
        label = text(as_dict(tag).get("text"))
        if label and label not in labels:
            labels.append(label)
    return [label for label in labels if not _LIKED_RE.search(label)]


def _liked(row):
    """(liked percent, number of ratings) from the item's thumbs-up label
    ('$16.02 • 86% (1209)' on menus, an '82% (46)' tag on the item page)."""
    label = as_dict(row.get("labelPrimary"))
    candidates = [rich_text(label), text(label.get("accessibilityText"))]
    candidates += [text(as_dict(t).get("text")) for t in as_list(row.get("endorsementTags"))]
    for candidate in candidates:
        match = _LIKED_RE.search(candidate or "")
        if match:
            return to_int(match.group(1)), parse_count(match.group(2))
    match = re.search(r"(\d{1,3})\s*%.*?(\d[\d,]*)\s+\w+", candidates[1] or "")
    if match:
        return to_int(match.group(1)), parse_count(match.group(2))
    return None, None


def menu_item(row, store_id=None, slug=None, country=None, section_id=None, currency=None):
    """A catalog item (dish / grocery product) as listed on a menu."""
    row = as_dict(row)
    item_id = text(row.get("uuid"))
    section = text(row.get("sectionUuid")) or section_id
    subsection = text(row.get("subsectionUuid"))
    liked_percent, rating_count = _liked(row)
    tagline = text(as_dict(row.get("priceTagline")).get("text")) or ""
    calories = _CAL_RE.search(tagline)
    promo_badge = rich_text(as_dict(as_dict(as_dict(row.get("promoInfo")).get("promoBadge")).get("content")))
    out = {
        "id": item_id,
        "name": text(row.get("title")),
        "link": refs.item_link(store_id, section, subsection, item_id, slug, country),
        "description": text(row.get("itemDescription")),
        "price": money(row.get("price")),
        "image": text(row.get("imageUrl")),
        "is_sold_out": bool(row.get("isSoldOut")) if row.get("isSoldOut") is not None else None,
        "is_available": row.get("isAvailable") if isinstance(row.get("isAvailable"), bool) else None,
        "has_customizations": bool(row.get("hasCustomizations")) if row.get("hasCustomizations") is not None else None,
        "labels": _item_labels(row),
        "liked_percent": liked_percent,
        "rating_count": rating_count,
        "calories": parse_count(calories.group(1)) if calories else None,
        "max_calories": parse_count(calories.group(2)) if calories and calories.group(2) else None,
        "promotion": _promotion(row.get("itemPromotion")),
        "promotion_text": promo_badge,
        "purchase": _purchase(row.get("purchaseInfo")),
        "product_id": text(as_dict(row.get("productInfo")).get("productUuid")),
        "section_id": section,
        "subsection_id": subsection,
    }
    if currency:
        out["currency"] = currency
    return out


def catalog_groups(sections, store_id=None, slug=None, country=None, section_id=None):
    """A list of catalog sections (one menu's categories / one aisle's
    shelves) -> [{id, title, item_count, items}]; non-item widgets (aisle
    shortcuts, banners, empty states) are skipped."""
    out = []
    for section in as_list(sections):
        section = as_dict(section)
        payload = as_dict(as_dict(section.get("payload")).get("standardItemsPayload"))
        rows = as_list(payload.get("catalogItems"))
        if not rows:
            continue
        parent = text(payload.get("sectionUUID")) or section_id
        items = [menu_item(r, store_id, slug, country, parent) for r in rows if isinstance(r, dict)]
        out.append({
            "id": text(section.get("catalogSectionUUID")),
            "title": text(as_dict(payload.get("title")).get("text")),
            "item_count": len(items),
            "items": items,
        })
    return out


def aisle_shortcuts(sections, store_id=None):
    """The aisle tiles of a grocery storefront -> [{id, title, image}]."""
    out = []
    for section in as_list(sections):
        payload = as_dict(as_dict(as_dict(section).get("payload")).get("aisleShortcutItems"))
        for row in as_list(payload.get("aisleShortcutItems")):
            row = as_dict(row)
            match = re.search(r"sectionUUID=([0-9a-f\-]{36})", text(row.get("ctaUri")) or "")
            if not match:
                continue
            out.append({"id": match.group(1), "title": rich_text(row.get("title")),
                        "image": text(row.get("imageUrl"))})
    return out


def menu_sections(store, country=None):
    """getStoreV1 data -> the store's menus: [{id, title, hours_text,
    is_on_sale, category_count, item_count, categories: [{id, title, items}]}].
    A restaurant has one section per menu (Breakfast, Lunch ...); a grocery
    store has one per aisle and only ships the first aisles here."""
    store = as_dict(store)
    store_id, slug = text(store.get("uuid")), text(store.get("slug"))
    catalog = as_dict(store.get("catalogSectionsMap"))
    known = {text(as_dict(s).get("uuid")): as_dict(s) for s in as_list(store.get("sections"))}
    out = []
    for section_id, sections in catalog.items():
        groups = catalog_groups(sections, store_id, slug, country, section_id)
        meta = known.get(section_id, {})
        out.append({
            # a grocery storefront is keyed by the store id, not a section
            "id": section_id if section_id in known else None,
            "title": text(meta.get("title")),
            "hours_text": text(meta.get("subtitle")),
            "is_on_sale": meta.get("isOnSale") if isinstance(meta.get("isOnSale"), bool) else None,
            "category_count": len(groups),
            "item_count": sum(g["item_count"] for g in groups),
            "categories": groups,
        })
    return out


def customization_groups(rows):
    """customizationsList -> modifier groups, nested as deep as the site
    nests them (an option can open its own groups)."""
    out = []
    for row in as_list(rows):
        row = as_dict(row)
        minimum, maximum = to_int(row.get("minPermitted")), to_int(row.get("maxPermitted"))
        options = []
        for option in as_list(row.get("options")):
            option = as_dict(option)
            options.append({
                "id": text(option.get("uuid")),
                "name": text(option.get("title")),
                "description": text(option.get("subtitle")) or rich_text(option.get("subtitle")),
                "price": money(option.get("price")),
                "is_sold_out": bool(option.get("isSoldOut")) if option.get("isSoldOut") is not None else None,
                "default_quantity": to_int(option.get("defaultQuantity")),
                "min_quantity": to_int(option.get("minPermitted")),
                "max_quantity": to_int(option.get("maxPermitted")),
                "dietary_labels": _dietary(option.get("itemAttributeInfo")),
                "customizations": customization_groups(option.get("childCustomizationList")),
            })
        out.append({
            "id": text(row.get("uuid")),
            "title": text(row.get("title")),
            "is_required": bool(minimum and minimum > 0),
            "min_selections": minimum,
            "max_selections": maximum,
            "option_count": len(options),
            "options": options,
        })
    return out


def _dietary(info):
    labels = []
    for label in as_list(as_dict(info).get("dietaryLabels")):
        value = text(label) or text(as_dict(label).get("label")) or text(as_dict(label).get("type"))
        if value:
            labels.append(value.lower())
    return labels


def _classifications(rows):
    out = []
    for row in as_list(rows):
        value = text(row) or text(as_dict(row).get("name")) or text(as_dict(row).get("type"))
        if value:
            out.append(value.lower())
    return out


def menu_item_details(row, store_id=None, slug=None, country=None, currency=None):
    """getMenuItemV1 data -> the full item with its customizations."""
    row = as_dict(row)
    out = menu_item(row, store_id, slug, country)
    images = [u for u in (text(as_dict(i).get("imageUrl")) or text(as_dict(i).get("url"))
                          for i in as_list(row.get("images"))) if u]
    if out["image"] and out["image"] not in images:
        images.insert(0, out["image"])
    details = []
    for part in as_list(row.get("productDetailsItems")):
        part = as_dict(part)
        if part.get("type") in ("PRICING", "QUANTITY_SELECTOR", "REMOVE_ITEM_BUTTON", "CATALOG_SECTION",
                                "PRESELECTED_CUSTOMIZATIONS"):
            continue
        payload = as_dict(part.get("payload"))
        body = as_dict(payload.get(payload.get("type"))) if payload.get("type") else {}
        title = rich_text(body.get("title")) or text(body.get("title"))
        value = (rich_text(body.get("body")) or rich_text(body.get("description")) or rich_text(body.get("text"))
                 or text(body.get("body")) or text(body.get("description")) or text(body.get("text")))
        if title or value:
            details.append({"type": lower(part.get("type")), "title": title, "text": value})
    groups = customization_groups(row.get("customizationsList"))
    suspended_until = iso_datetime(row.get("suspendUntil"))
    out.update({
        "currency": currency,
        "images": images,
        "dietary_labels": _dietary(row.get("itemAttributeInfo")),
        "classifications": _classifications(row.get("classifications")),
        "details": details,
        "low_availability_label": text(row.get("lowAvailabilityLabel")) or rich_text(row.get("lowAvailabilityLabel")),
        "unavailable_reason": text(row.get("suspendReason")) if (row.get("isSoldOut") or suspended_until) else None,
        "unavailable_until": suspended_until,
        "disclaimer": text(row.get("adaptedDisclaimer")) or rich_text(row.get("adaptedDisclaimer")),
        "customization_count": len(groups),
        "customizations": groups,
    })
    order = ["id", "name", "link", "description", "price", "currency", "image", "images", "is_sold_out",
             "is_available", "has_customizations", "labels", "liked_percent", "rating_count", "calories",
             "max_calories", "dietary_labels", "classifications", "promotion", "promotion_text", "purchase",
             "details", "low_availability_label", "unavailable_reason", "unavailable_until", "disclaimer",
             "product_id", "section_id", "subsection_id", "customization_count", "customizations"]
    return {key: out.get(key) for key in order}


# ---- store details ----------------------------------------------------------------

def store_hours(rows):
    out = []
    for row in as_list(rows):
        row = as_dict(row)
        periods = []
        for period in as_list(row.get("sectionHours")):
            period = as_dict(period)
            start, end = to_int(period.get("startTime")), to_int(period.get("endTime"))
            periods.append({
                "menu": text(period.get("sectionTitle")) or text(period.get("title")),
                "opens_at": clock(start),
                "closes_at": clock(end),
                "closes_next_day": bool(start is not None and end is not None and end < start),
            })
        out.append({"days": text(row.get("dayRange")), "periods": periods})
    return out


def _dining_modes(rows):
    return [{"mode": lower(as_dict(r).get("mode")),
             "is_available": bool(as_dict(r).get("isAvailable")),
             "is_selected": bool(as_dict(r).get("isSelected"))}
            for r in as_list(rows) if as_dict(r).get("mode")]


def merchant_type(info):
    kind = text(as_dict(as_dict(info).get("uberMerchantType")).get("type"))
    return kind.replace("MERCHANT_TYPE_", "").lower() if kind else None


def review(row, is_featured=False):
    row = as_dict(row)
    return {
        "id": text(row.get("contentUUID")),
        "reviewer_name": text(as_dict(row.get("eaterName")).get("text")),
        "text": text(as_dict(row.get("reviewText")).get("text")),
        "is_featured": is_featured,
        "created_at": iso_datetime(row.get("createdAt")),
    }


def store_reviews(store):
    """Featured reviews first, then the rest, deduped by id."""
    store = as_dict(store)
    out, seen = [], set()
    for rows, featured in ((store.get("featuredReviews"), True), (store.get("storeReviews"), False)):
        for row in as_list(rows):
            item = review(row, featured)
            key = item["id"] or (item["reviewer_name"], item["text"])
            if not item["text"] or key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


def store_rating(store):
    store = as_dict(store)
    rating = as_dict(store.get("rating"))
    raw = as_dict(as_dict(store.get("storeInfoMetadata")).get("rawRatingStats"))
    score = to_float(raw.get("storeRatingScore"))
    return {
        "rating": to_float(rating.get("ratingValue")) if rating.get("ratingValue") is not None
        else (round(score, 1) if score else None),
        "rating_exact": round(score, 4) if score else None,
        "review_count": parse_count(rating.get("reviewCount")) or parse_count(raw.get("ratingCount")),
    }


def store_details(store, country=None, has_point=True):
    """getStoreV1 data -> the store profile (menu and reviews are separate
    endpoints; their sizes are summarised here). `has_point=False` nulls the
    fields that depend on a delivery address (the site otherwise computes
    them from the caller's IP)."""
    store = as_dict(store)
    store_id, slug = text(store.get("uuid")), text(store.get("slug"))
    location = as_dict(store.get("location"))
    geo = as_dict(location.get("geo"))
    info = as_dict(store.get("storeInfoMetadata"))
    branding = as_dict(store.get("headerBrandingInfo"))
    chain = as_dict(store.get("parentChain"))
    later = as_dict(store.get("orderForLaterInfo"))
    eta_text = text(as_dict(store.get("etaRange")).get("text"))
    eta_min, eta_max = minutes_range(eta_text)
    fare = text(as_dict(store.get("fareBadge")).get("text"))
    service_fee = money(as_dict(store.get("fareInfo")).get("serviceFeeCents"))
    ratings = store_rating(store)
    state = lower(as_dict(info.get("storeAvailablityStatus")).get("state"))
    next_open = iso_datetime(later.get("nextOpenTime"))
    is_open = store.get("isOpen") if isinstance(store.get("isOpen"), bool) else None
    if is_open and (state == "store_closed"
                    or (next_open and next_open > datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))):
        # `isOpen` stays true for a store that only takes scheduled orders
        is_open = False

    health = None
    for icon in as_list(store.get("indicatorIcons")):
        icon = as_dict(icon)
        if text(icon.get("title")) and (icon.get("typeV2") == "HEALTH_GRADE"
                                         or text(as_dict(icon.get("moreInfoSheet")).get("url"))):
            health = {"title": text(icon.get("title")),
                      "description": text(icon.get("legalDisclaimerText")),
                      "link": text(as_dict(icon.get("moreInfoSheet")).get("url"))}
            break
    hygiene = text(as_dict(store.get("hygieneRatingBadge")).get("iconUrl"))
    if hygiene and "missing_rating" in hygiene:
        hygiene = None

    menus = []
    catalog = as_dict(store.get("catalogSectionsMap"))
    for section in as_list(store.get("sections")):
        section = as_dict(section)
        section_id = text(section.get("uuid"))
        groups = catalog_groups(catalog.get(section_id), store_id, slug, country, section_id) \
            if section_id in catalog else None
        menus.append({
            "id": section_id,
            "title": text(section.get("title")),
            "hours_text": text(section.get("subtitle")),
            "is_on_sale": section.get("isOnSale") if isinstance(section.get("isOnSale"), bool) else None,
            "item_count": sum(g["item_count"] for g in groups) if groups is not None else None,
        })

    categories = []
    for row in as_list(store.get("categoryLinks")):
        row = as_dict(row)
        if text(row.get("text")):
            categories.append({"name": text(row.get("text")), "link": refs.absolute(row.get("link"))})

    promotion = as_dict(store.get("promotion"))
    delivery = {
        "min_minutes": eta_min, "max_minutes": eta_max, "text": eta_text,
        "fee": parse_number(fare), "fee_text": fare, "service_fee": service_fee,
        "distance": distance(store.get("distanceBadge")),
        "is_within_range": store.get("isWithinDeliveryRange")
        if isinstance(store.get("isWithinDeliveryRange"), bool) else None,
    } if has_point else None

    return {
        "id": store_id,
        "name": text(store.get("title")),
        "link": refs.store_link(store_id, slug, country),
        "slug": slug,
        "phone": text(store.get("phoneNumber")),
        "merchant_type": merchant_type(store.get("storeMerchantTypeInfo")),
        "price_range": text(store.get("priceBucket")),
        "cuisines": [c for c in (text(c) for c in as_list(store.get("cuisineList"))) if c],
        "tags": [t for t in (text(t) for t in as_list(store.get("tags"))) if t],
        "image": best_image(store.get("heroImageUrls")),
        "logo": text(branding.get("logoImageURL")),
        "rating": ratings["rating"],
        "rating_exact": ratings["rating_exact"],
        "review_count": ratings["review_count"],
        "is_open": is_open,
        "is_orderable": store.get("isOrderable") if isinstance(store.get("isOrderable"), bool) else None,
        "is_schedulable": as_dict(store.get("scheduledOrderInfo")).get("isSchedulable")
        if isinstance(as_dict(store.get("scheduledOrderInfo")).get("isSchedulable"), bool) else None,
        "is_third_party_delivery": store.get("isDeliveryThirdParty")
        if isinstance(store.get("isDeliveryThirdParty"), bool) else None,
        "availability": state if has_point else None,
        "status": text(info.get("workingHoursTagline")) or text(store.get("workingHoursTagline")),
        "next_open_at": next_open,
        "currency": text(store.get("currencyCode")),
        "location": {
            "address": text(location.get("address")),
            "street_address": text(location.get("streetAddress")),
            "city": text(location.get("city")),
            "region": text(location.get("region")),
            "postal_code": text(location.get("postalCode")),
            "country": text(location.get("country")),
            "latitude": to_float(location.get("latitude")),
            "longitude": to_float(location.get("longitude")),
            "city_slug": text(geo.get("city")),
            "neighborhood_slug": text(geo.get("neighborhood")),
            "region_slug": text(geo.get("region")),
        },
        "delivery": delivery,
        "dining_modes": _dining_modes(store.get("supportedDiningModes")) if has_point else
        [{"mode": m["mode"], "is_available": m["is_available"]}
         for m in _dining_modes(store.get("supportedDiningModes"))],
        "hours": store_hours(store.get("hours")),
        "chain": {"id": text(chain.get("uuid")), "name": text(chain.get("name"))} if chain.get("uuid") else None,
        "categories": categories,
        "promotion": text(promotion.get("text")) or rich_text(promotion) or None,
        "health_inspection": health,
        "hygiene_rating_image": hygiene,
        "disclaimer": text(strip_html(text(as_dict(store.get("disclaimerBadge")).get("text")))),
        "menus": menus,
        "featured_review_count": len(as_list(store.get("featuredReviews"))),
        "loaded_review_count": len(as_list(store.get("storeReviews"))),
        "joined_at": iso_datetime(store.get("onboardingStatusUpdatedAt")),
    }


# ---- search suggestions -----------------------------------------------------------

def suggestion(row, country=None):
    row = as_dict(row)
    kind = row.get("type")
    if kind == "store" and isinstance(row.get("store"), dict):
        store = row["store"]
        store_id = text(store.get("uuid"))
        return {
            "type": "store",
            "text": text(row.get("title")) or text(store.get("title")),
            "store": {
                "id": store_id,
                "name": text(store.get("title")),
                "link": refs.store_link(store_id, text(store.get("slug")), country),
                "image": _image(store.get("heroImageUrl")),
                "categories": [c for c in (text(c) for c in as_list(store.get("categories"))) if c],
                "caption": rich_text(store.get("meta1")),
                "is_orderable": store.get("isOrderable") if isinstance(store.get("isOrderable"), bool) else None,
            },
        }
    if kind in ("textV2", "text", "searchHistoryV2"):
        return {"type": "query", "text": text(row.get("title")), "store": None}
    return None
