"""/uber-eats/countries, /cities/*, /neighborhoods/*, /brands/* — the site's
public directory (its SEO pages): where Uber Eats operates, the stores of a
city / cuisine category / neighborhood and the locations of a chain. None
of it needs a delivery address.

A country is the site's URL prefix (`us` has none, `gb` -> /gb/...); the
RPCs take it as localeCode AND as the pathname prefix."""
import re

from uber_eats import parsers as P
from uber_eats import refs
from uber_eats.fetch import UberEatsNotFound, rpc

STORES_PER_PAGE = 20


def _country(country, ref=None):
    """The link's own country wins over the `country` param."""
    return ((ref or {}).get("country") or country or "us").lower()


def _prefix(country):
    return "" if country == "us" else f"/{country}"


def _seo(path, country, label):
    try:
        data = rpc("getSeoFeedV1", {"pathname": _prefix(country) + path}, locale=country, label=label)
    except UberEatsNotFound:
        raise UberEatsNotFound(f"{label} not found on Uber Eats ({country.upper()})")
    if not isinstance(data, dict) or not data.get("elements"):
        raise UberEatsNotFound(f"{label} not found on Uber Eats ({country.upper()})")
    return data


def _slug_after(path, marker, position=0):
    try:
        _, segments = refs.split_path(path or "")
    except ValueError:
        return None
    for index, segment in enumerate(segments):
        if segment == marker and len(segments) > index + 1 + position:
            return segments[index + 1 + position]
    return None


def _links(element, marker, country, builder, position=0):
    """A linkBlock -> [{name, slug, link}] for entries of one page kind."""
    out = []
    for row in P.as_list(P.as_dict(element).get("links")):
        row = P.link_row(row)
        slug = _slug_after(row["path"], marker, position)
        if row["name"] and slug:
            out.append({"name": row["name"], "slug": slug, "link": builder(slug, country)})
    return out


def _breadcrumbs(elements, country):
    """Breadcrumb trail -> (country name, region {name, slug, link} | None,
    page name)."""
    rows = [P.as_dict(r) for r in P.as_list(P.as_dict(elements.get("breadcrumbs")).get("value"))]
    country_name = P.text(rows[0].get("title")) if rows else None
    region = None
    for row in rows:
        slug = _slug_after(P.text(row.get("href")), "region")
        if slug:
            region = {"name": P.text(row.get("title")), "slug": slug, "link": refs.region_link(slug, country)}
    return country_name, region, (P.text(rows[-1].get("title")) if rows else None)


def _top_categories(element, city, country):
    out = []
    for item in P.as_list(P.as_dict(element).get("feedItems")):
        for row in P.as_list(P.as_dict(item).get("items")):
            row = P.as_dict(row)
            slug = P.text(row.get("slug"))
            name = P.text(row.get("title")) or P.text(row.get("categoryName"))
            if name and slug:
                out.append({"name": name, "slug": slug, "link": refs.category_link(city, slug, country),
                            "image": P.text(row.get("imageUrl")) or P.text(row.get("iconUrl"))})
    return out


# ---- countries / cities -----------------------------------------------------------

def countries():
    """Every country Uber Eats operates in."""
    data = rpc("getCountriesWithCitiesV1", {}, locale="us", label="countries") or {}
    rows = []
    for row in P.as_list(P.as_dict(data.get("countryLinks")).get("links")):
        row = P.as_dict(row)
        match = re.match(r"^/([a-z]{2})(?:[-/]|$)", P.text(row.get("href")) or "")
        if not P.text(row.get("title")):
            continue
        code = match.group(1) if match else "us"
        rows.append({"name": P.text(row.get("title")), "code": code.upper(),
                     "link": f"{refs.SITE}{'' if code == 'us' else '/' + code}/location"})
    return {"count": len(rows), "countries": rows}


def cities(country="us", region=None):
    """Every city Uber Eats serves in a country, grouped by region / state.
    `region` (slug or name) narrows the answer to one region."""
    country = _country(country, region if isinstance(region, dict) else None)
    try:
        data = rpc("getCountriesWithCitiesV1", {}, locale=country, label="cities") or {}
    except UberEatsNotFound:
        raise UberEatsNotFound(f"Uber Eats has no city directory for {country.upper()}")
    block = P.as_dict(data.get("regionCityLinks"))
    wanted = (region or {}).get("slug") if isinstance(region, dict) else None
    regions, total = [], 0
    for row in P.as_list(block.get("links")):
        row = P.as_dict(row)
        slug = _slug_after(P.text(row.get("href")), "region")
        name = P.text(row.get("title"))
        if wanted and wanted not in ((slug or "").lower(), (name or "").lower().replace(" ", "-")):
            continue
        rows = []
        for city in P.as_list(row.get("links")):
            city = P.as_dict(city)
            city_slug = _slug_after(P.text(city.get("href")), "city")
            if P.text(city.get("title")) and city_slug:
                rows.append({"name": P.text(city.get("title")), "slug": city_slug,
                             "link": refs.city_link(city_slug, country)})
        total += len(rows)
        regions.append({"name": name, "slug": slug, "link": refs.region_link(slug, country),
                        "city_count": len(rows), "cities": rows})
    if not regions:
        if wanted:
            raise UberEatsNotFound(f"region '{wanted}' not found in {country.upper()}")
        raise UberEatsNotFound(f"Uber Eats has no city directory for {country.upper()}")
    return {"country": country.upper(), "region_count": len(regions), "city_count": total, "regions": regions}


def city_details(city, country="us"):
    """A city's directory page: region, description, top cuisine categories,
    FAQ and nearby cities."""
    country = _country(country, city)
    slug = city["slug"]
    elements = P.elements_by_id(_seo(f"/city/{slug}", country, f"city '{slug}'"))
    meta = P.as_dict(elements.get("metadata"))
    country_name, region, name = _breadcrumbs(elements, country)
    stores = P.as_dict(elements.get("cityPaginatedStores") or elements.get("cityStores"))
    categories = _top_categories(elements.get("topCategories"), slug, country)
    faqs = P.faqs(elements.get("faqs"))
    nearby = _links(elements.get("cityNearMe"), "city", country, refs.city_link)
    return {
        "city": {
            "slug": slug,
            "name": name,
            "link": refs.city_link(slug, country),
            "title": P.text(meta.get("title")),
            "description": P.text(meta.get("description")),
            "about": P.page_text(elements),
            "region": region,
            "country": {"code": country.upper(), "name": country_name},
            "store_page_count": P.to_int(stores.get("totalPages")),
        },
        "category_count": len(categories),
        "categories": categories,
        "faqs": faqs,
        "nearby_cities": nearby,
    }


def city_stores(city, category=None, country="us", page=1):
    """Stores of a city, optionally of one cuisine category, 20 per page."""
    country = _country(country, city)
    slug = city["slug"]
    category_slug = (category or {}).get("slug")
    path = f"/category/{slug}/{category_slug}" if category_slug else f"/city/{slug}"
    label = f"category '{category_slug}' in city '{slug}'" if category_slug else f"city '{slug}'"
    if page == 1:
        elements = P.elements_by_id(_seo(path, country, label))
        block = P.as_dict(elements.get("categoryPaginatedStores") or elements.get("cityPaginatedStores")
                          or elements.get("categoryStores") or elements.get("cityStores"))
    else:
        try:
            block = rpc("getPaginatedStoresV1", {"citySlug": slug, "category": category_slug or "",
                                                 "pageNumber": page},
                        locale=country, referer=f"{_prefix(country)}{path}?page={page}", label=label) or {}
        except UberEatsNotFound:
            raise UberEatsNotFound(f"{label} not found on Uber Eats ({country.upper()})")
    stores = P.seo_stores(block, country)
    total_pages = P.to_int(P.as_dict(block).get("totalPages")) or (page if stores else 0)
    return {
        "city": {"slug": slug, "link": refs.city_link(slug, country)},
        "category": {"slug": category_slug, "link": refs.category_link(slug, category_slug, country)}
        if category_slug else None,
        "country": country.upper(),
        "pagination": {"page": page, "items_per_page": STORES_PER_PAGE, "total_pages": total_pages,
                       "total_count": None},
        "stores": stores,
    }


def neighborhood_stores(neighborhood, country="us"):
    """Stores of one neighborhood (up to 80, with the site's blurbs) and
    the neighborhoods around it."""
    country = _country(country, neighborhood)
    slug = neighborhood["slug"]
    elements = P.elements_by_id(_seo(f"/neighborhood/{slug}", country, f"neighborhood '{slug}'"))
    meta = P.as_dict(elements.get("metadata"))
    country_name, region, name = _breadcrumbs(elements, country)
    crumbs = [P.as_dict(r) for r in P.as_list(P.as_dict(elements.get("breadcrumbs")).get("value"))]
    city = None
    for row in crumbs:
        city_slug = _slug_after(P.text(row.get("href")), "city")
        if city_slug:
            city = {"name": P.text(row.get("title")), "slug": city_slug, "link": refs.city_link(city_slug, country)}
    stores = P.seo_stores(elements.get("cityStores") or elements.get("cityPaginatedStores"), country)
    return {
        "neighborhood": {
            "slug": slug,
            "name": name,
            "link": refs.neighborhood_link(slug, country),
            "title": P.text(meta.get("title")),
            "description": P.text(meta.get("description")),
            "about": P.page_text(elements),
            "city": city,
            "region": region,
            "country": {"code": country.upper(), "name": country_name},
        },
        "count": len(stores),
        "stores": stores,
        "nearby_neighborhoods": _links(elements.get("cityNearMe"), "neighborhood", country, refs.neighborhood_link),
    }


# ---- brands -----------------------------------------------------------------------

def _brand_name(elements):
    title = P.text(P.as_dict(elements.get("brandCity")).get("title")) or ""
    match = re.match(r"^(.*?) locations in ", title)
    if match:
        return match.group(1)
    title = P.text(P.as_dict(elements.get("metadata")).get("title")) or ""
    match = re.match(r"^(.*?) (?:Delivery|Takeaway|Livraison)\b", title)
    return match.group(1) if match else None


def _city_brand_name(block):
    """'151 McDonald's locations in New York' -> 'McDonald's'."""
    match = re.match(r"^\s*[\d.,]+\s+(.+?)\s+locations? in ", P.text(P.as_dict(block).get("title")) or "")
    return match.group(1) if match else None


def brand_details(brand, country="us"):
    """A chain's page: logo, the cities it delivers in (with the number of
    locations in each) and the other countries it is listed in."""
    country = _country(country, brand)
    slug = brand["slug"]
    elements = P.elements_by_id(_seo(f"/brand/{slug}", country, f"brand '{slug}'"))
    meta = P.as_dict(elements.get("metadata"))
    hero = P.as_dict(elements.get("customEnterAddress"))
    block = P.as_dict(elements.get("brandCity"))
    cities_out, total = [], 0
    for row in P.as_list(block.get("links")):
        row = P.link_row(row)
        city_slug = _slug_after(row["path"], "brand-city")
        if not (row["name"] and city_slug):
            continue
        count = P.parse_count(row["label"])
        total += count or 0
        cities_out.append({"name": row["name"], "slug": city_slug,
                           "link": refs.brand_link(slug, city_slug, country), "location_count": count})
    others = []
    for row in P.as_list(P.as_dict(elements.get("brand")).get("links")):
        row = P.link_row(row)
        try:
            code, _ = refs.split_path(row["path"] or "")
        except ValueError:
            code = None
        if row["name"]:
            others.append({"name": row["name"], "code": (code or "us").upper(),
                           "link": refs.brand_link(slug, None, code or "us")})
    return {
        "brand": {
            "slug": slug,
            "name": _brand_name(elements),
            "link": refs.brand_link(slug, None, country),
            "title": P.text(meta.get("title")),
            "description": P.text(block.get("subtitle")) or P.text(meta.get("description")),
            "logo": P.text(hero.get("logoUrl")),
            "banner": P.text(hero.get("backgroundUrl")),
            "country": country.upper(),
            "city_count": len(cities_out),
            "location_count": total or None,
        },
        "cities": cities_out,
        "other_countries": others,
        "faqs": P.faqs(elements.get("faqs")),
    }


def brand_stores(brand, city=None, country="us"):
    """A chain's locations in one city: each store with its address, price
    range and coordinates, plus the featured items of the first locations."""
    country = _country(country, brand if brand.get("country") else city)
    slug = brand["slug"]
    city_slug = brand.get("city") or (city or {}).get("slug")
    if not city_slug:
        raise ValueError("city is required (or pass a brand-city link as brand)")
    elements = P.elements_by_id(_seo(f"/brand-city/{city_slug}/{slug}", country,
                                     f"brand '{slug}' in city '{city_slug}'"))
    meta = P.as_dict(elements.get("metadata"))
    hero = P.as_dict(elements.get("customEnterAddress"))
    markers = {}
    for marker in P.as_list(P.as_dict(elements.get("map")).get("markers")):
        marker = P.as_dict(marker)
        try:
            store_id = refs.resolve_store(P.text(marker.get("href")) or "")
        except ValueError:
            continue
        markers[store_id] = marker
    block = P.as_dict(elements.get("brandCityStores"))
    stores, seen = [], set()

    def add(store_id, name, label, path):
        if store_id in seen:
            return
        seen.add(store_id)
        marker = P.as_dict(markers.get(store_id))
        price, _, address = (label or "").partition("•")
        if not address:
            price, address = "", label or ""
        _, segments = refs.split_path(path) if path else (None, [])
        store_slug = segments[1] if len(segments) >= 3 and segments[0] == "store" else None
        stores.append({
            "id": store_id,
            "name": name or P.text(marker.get("label")),
            "link": refs.store_link(store_id, store_slug, country),
            "price_range": P.text(price),
            "location": {"address": P.text(address), "latitude": P.to_float(marker.get("latitude")),
                         "longitude": P.to_float(marker.get("longitude"))},
        })

    for row in P.as_list(block.get("links")):
        row = P.link_row(row)
        try:
            add(refs.resolve_store(row["path"] or ""), row["name"], row["label"], row["path"])
        except ValueError:
            continue
    for store_id, marker in markers.items():
        add(store_id, P.text(marker.get("label")), None, P.text(marker.get("href")))

    shelves = []
    for shelf in P.as_list(P.as_dict(elements.get("dishCarouselList")).get("dishCarousels")):
        shelf = P.as_dict(shelf)
        # a shelf names its store only in the subtitle ("From <store name>")
        subtitle = P.text(shelf.get("subtitle")) or ""
        owner = next((row for row in stores if row["name"] and subtitle.endswith(row["name"])), None)
        store_id = owner["id"] if owner else None
        store_slug = owner["link"].rstrip("/").split("/")[-2] if owner and owner["link"] else None
        if store_slug:
            store_slug = refs.unquote(store_slug)
        items = [P.menu_item(P.as_dict(dish).get("catalogItem"), store_id, store_slug, country)
                 for dish in P.as_list(shelf.get("dishes")) if isinstance(P.as_dict(dish).get("catalogItem"), dict)]
        if items:
            shelves.append({"title": P.text(shelf.get("title")), "subtitle": P.text(shelf.get("subtitle")),
                            "store_id": store_id, "store_link": refs.store_link(store_id, store_slug, country),
                            "item_count": len(items), "items": items})
    total = P.parse_count((re.match(r"^\s*([\d.,]+)", P.text(block.get("title")) or "") or [None, None])[1])
    center = P.as_dict(P.as_dict(elements.get("map")).get("centerLocation"))
    return {
        "brand": {
            "slug": slug,
            "name": _city_brand_name(block) or _brand_name(elements),
            "link": refs.brand_link(slug, None, country),
            "logo": P.text(hero.get("logoUrl")),
            "banner": P.text(hero.get("backgroundUrl")),
        },
        "city": {"slug": city_slug, "link": refs.brand_link(slug, city_slug, country),
                 "latitude": P.to_float(center.get("latitude")), "longitude": P.to_float(center.get("longitude"))},
        "country": country.upper(),
        "title": P.text(meta.get("title")),
        "about": P.page_text(elements),
        "location_count": total or len(stores),
        "count": len(stores),
        "stores": stores,
        "featured_items": shelves,
        "faqs": P.faqs(elements.get("faqs")),
    }
