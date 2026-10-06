"""/uber-eats/search/* — the search box: typeahead suggestions and the
"top categories / top searches" lists it shows before typing."""
from uber_eats import parsers as P
from uber_eats import shared
from uber_eats.fetch import rpc

_VERTICALS = {"ALL": "all", "RESTAURANTS": "restaurants", "SHOP": "grocery", "ALCOHOL": "alcohol"}


def suggestions(query, location):
    """Typeahead for a partial query near an address: query completions and
    matching stores."""
    point, public = shared.resolve_point(location)
    rows = rpc("getSearchSuggestionsV1", {"userQuery": query, "date": "", "startTime": 0, "endTime": 0,
                                          "vertical": "ALL"}, point=point, label="search suggestions") or []
    out = [s for s in (P.suggestion(r) for r in rows if isinstance(r, dict)) if s and s["text"]]
    return {"query": query, "location": public, "count": len(out), "suggestions": out}


def popular(location):
    """What the empty search box offers at an address: top cuisine
    categories and the top searches per vertical (grocery, alcohol)."""
    point, public = shared.resolve_point(location)
    data = rpc("getSearchHomeV2", {"dropPastOrders": True}, point=point, label="popular searches") or {}
    results = P.as_dict(data.get("verticalSearchHomeResults"))
    categories, seen = [], set()
    searches = {}
    for vertical, rows in results.items():
        name = _VERTICALS.get(vertical, str(vertical).lower())
        for row in P.as_list(rows):
            row = P.as_dict(row)
            title = P.text(row.get("title"))
            if not title:
                continue
            if row.get("type") == "topCategory":
                if title not in seen:
                    seen.add(title)
                    categories.append({"name": title, "query": P.text(row.get("titleTerm")) or title,
                                       "image": P.text(row.get("iconUrl"))})
            elif row.get("type") == "searchHistoryV2":
                searches.setdefault(name, [])
                if title not in searches[name]:
                    searches[name].append(title)
    return {
        "location": public,
        "category_count": len(categories),
        "categories": categories,
        "top_searches": [{"vertical": k, "queries": v} for k, v in searches.items()],
    }
