"""/uber-eats/locations/* — the address box: place autocomplete and the
delivery point an address / coordinate pair resolves to."""
from uber_eats import parsers as P
from uber_eats import shared
from uber_eats.fetch import rpc, rpc_optional


def autocomplete(query, country="us"):
    """Address / place suggestions as the site's address box returns them."""
    rows = rpc("mapsSearchV1", {"query": query}, locale=country, label="address autocomplete") or []
    places = [P.place_suggestion(r) for r in rows if isinstance(r, dict)]
    return {"query": query, "count": len(places), "places": places}


def details(location):
    """Resolve an address (or 'latitude,longitude') to the delivery point the
    other endpoints use: formatted address, city, postal code, coordinates."""
    if location.get("query"):
        return {"location": shared.resolve_point(location)[1]}
    data = rpc_optional("getOriginsLocationDetailsFromCoordinateV1",
                        {"latitude": location["latitude"], "longitude": location["longitude"],
                         "language": "en-US"}, label="reverse geocode")
    public = P.delivery_location(data or {})
    public["latitude"], public["longitude"] = location["latitude"], location["longitude"]
    return {"location": public}
