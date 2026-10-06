"""The 20 Uber Eats endpoints. Every path is served with and without the
`/uber-eats` prefix, so code generated against the hosted API on RapidAPI
(paths like /stores/details) runs unchanged against this server.

Query params are validated by the marshmallow schemas in uber_eats/schemas.py
(one param per input: `store` takes a link or an id, `location` an address or
"latitude,longitude" ...); each schema's output is exactly the keyword
arguments its endpoint function takes."""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from schema_fields import load_query
from scraper_errors import BadRequest, NotFound
from uber_eats import directory, locations, schemas, search, stores

PREFIX = "/uber-eats"


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "Café" would arrive as "CafÃ©")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def paginate(result, path, raw):
    """Lift the scraper's `pagination` block into the flat shape the hosted
    API returns: count / per_page / current_page / total_pages / next / previous."""
    pagination = result.pop("pagination", None) or {}
    page = int(pagination.get("page") or raw.get("page") or 1)
    total_pages = int(pagination.get("total_pages") or 0)
    base = f"{request.urlparts.scheme}://{request.urlparts.netloc}{path}"

    def link(number):
        if not number:
            return None
        params = {k: v for k, v in raw.items() if v not in (None, "")}
        params["page"] = number
        return f"{base}?{urlencode(params)}"

    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": link(page + 1 if page < total_pages else None),
        "previous": link(page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def call(path, schema, fn, paginated=False):
    """Shared handler body: bad params -> 400, missing entity -> 404,
    transport / blocks -> 500."""
    raw = query_dict()
    data, error = load_query(schema, raw)
    if error:
        return json_response(error, 400)
    try:
        result = fn(**data)
    except ValueError as e:                # bad id / params
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:                # upstream rejected the request
        return json_response({"error": f"uber-eats rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:                 # retries exhausted / blocked
        return json_response({"error": f"uber-eats {path.strip('/')} failed: {e}"}, 500)
    if paginated:
        result = paginate(result, request.path, raw)
    return json_response(result)


def mount(path, schema, fn, paginated=False):
    """Serve an endpoint at /path and /uber-eats/path."""
    def handler():
        return call(path, schema, fn, paginated)
    handler.__name__ = "uber_eats_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route(PREFIX + path, method="GET")(handler)


ENDPOINTS = [
    ("/stores/details", schemas.StoreSchema, stores.details, False),
    ("/stores/menu", schemas.StoreSchema, stores.menu, False),
    ("/stores/menu/item", schemas.MenuItemSchema, stores.menu_item, False),
    ("/stores/reviews", schemas.StoreOnlySchema, stores.reviews, False),
    ("/locations/autocomplete", schemas.AutocompleteSchema, locations.autocomplete, False),
    ("/locations/details", schemas.LocationSchema, locations.details, False),
    ("/stores/search", schemas.SearchSchema, stores.search, False),
    ("/stores/nearby", schemas.NearbySchema, stores.nearby, False),
    ("/stores/collections", schemas.CollectionsSchema, stores.collections, False),
    ("/stores/menu/search", schemas.MenuSearchSchema, stores.menu_search, False),
    ("/stores/menu/section", schemas.MenuSectionSchema, stores.menu_section, False),
    ("/search/suggestions", schemas.SuggestionsSchema, search.suggestions, False),
    ("/search/popular", schemas.LocationSchema, search.popular, False),
    ("/cities/stores", schemas.CityStoresSchema, directory.city_stores, True),
    ("/cities/details", schemas.CitySchema, directory.city_details, False),
    ("/cities", schemas.CitiesSchema, directory.cities, False),
    ("/countries", schemas.EmptySchema, directory.countries, False),
    ("/neighborhoods/stores", schemas.NeighborhoodSchema, directory.neighborhood_stores, False),
    ("/brands/stores", schemas.BrandStoresSchema, directory.brand_stores, False),
    ("/brands/details", schemas.BrandSchema, directory.brand_details, False),
]

for _path, _schema, _fn, _paginated in ENDPOINTS:
    mount(_path, _schema, _fn, _paginated)


@route("/", method="GET")
@route("/health", method="GET")
@route(PREFIX + "/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [e[0] for e in ENDPOINTS]})
