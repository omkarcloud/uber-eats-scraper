"""Marshmallow request schemas for every /uber-eats/* route. Generic fields
come from the shared schema_fields.py; this module adds the Uber Eats
resolvers. Every schema's load() output is the kwargs dict its endpoint
function takes.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    location      an address / place name OR "latitude,longitude"
    store         a store uuid, the id from a store link OR a store link
    item          an item uuid (with `store`) OR a full item link
    section       a menu section / aisle id from the store's menu
    city          a city slug (new-york-city) OR a city link
    category      a cuisine category slug (pizza) OR a category link
    neighborhood  a neighborhood slug OR a neighborhood link
    region        a region slug (ny) / name OR a region link
    brand         a brand slug (mcdonalds) OR a brand / brand-city link
"""
from marshmallow import ValidationError, validates_schema

from schema_fields import (BaseSchema, ChoiceField, CommaListField, CountryCodeField, Flag,
                           PageField, QueryField, RefField, StrippedString)
from uber_eats import refs

SORTS = ["recommended", "rating", "delivery_time"]
DINING_MODES = ["delivery", "pickup"]
MIN_RATINGS = {"3": 3.0, "3.0": 3.0, "3.5": 3.5, "4": 4.0, "4.0": 4.0, "4.5": 4.5, "5": 5.0, "5.0": 5.0}
PRICE_RANGES = {"1": 1, "2": 2, "3": 3, "4": 4, "$": 1, "$$": 2, "$$$": 3, "$$$$": 4}
MAX_FEES = {"2": 2, "3": 3, "4": 4}


# ---- id-or-link fields -------------------------------------------------------------

class LocationField(RefField):
    resolver = staticmethod(refs.resolve_location)


class StoreField(RefField):
    resolver = staticmethod(refs.resolve_store)


class ItemField(RefField):
    resolver = staticmethod(refs.resolve_item)


class SectionField(RefField):
    resolver = staticmethod(refs.resolve_section)


class CityField(RefField):
    resolver = staticmethod(refs.resolve_city)


class CategoryField(RefField):
    resolver = staticmethod(refs.resolve_category)


class NeighborhoodField(RefField):
    resolver = staticmethod(refs.resolve_neighborhood)


class RegionField(RefField):
    resolver = staticmethod(refs.resolve_region)


class BrandField(RefField):
    resolver = staticmethod(refs.resolve_brand)


class CountryField(CountryCodeField):
    """ISO country code of the Uber Eats market, lower-cased (default us).
    A link passed as city / brand / ... carries its own country and wins."""

    def __init__(self, **kwargs):
        kwargs.setdefault("load_default", "us")
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        return value.lower() if value else "us"


class CursorField(StrippedString):
    """`next_cursor` of the previous page (absent = first page)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        if not value.isdigit() or len(value) > 6:
            raise ValidationError("Must be the next_cursor value of the previous page.")
        return int(value)


def _optional(field_cls, **kwargs):
    kwargs.setdefault("required", False)
    kwargs.setdefault("load_default", None)
    return field_cls(**kwargs)


# ---- schemas -----------------------------------------------------------------------

class EmptySchema(BaseSchema):
    pass


class AutocompleteSchema(BaseSchema):
    query = QueryField()
    country = CountryField()


class LocationSchema(BaseSchema):
    location = LocationField()


class _StoreFilters(BaseSchema):
    location = LocationField()
    sort_by = ChoiceField(SORTS, load_default="recommended")
    min_rating = ChoiceField(MIN_RATINGS)
    price_range = CommaListField(value_map=PRICE_RANGES, upper=False, max_items=4)
    max_delivery_fee = ChoiceField(MAX_FEES)
    under_30_min = Flag()
    has_offers = Flag()
    top_rated = Flag()
    dining_mode = ChoiceField(DINING_MODES, load_default="delivery")
    cursor = CursorField()


class NearbySchema(_StoreFilters):
    pass


class SearchSchema(_StoreFilters):
    query = QueryField()


class CollectionsSchema(BaseSchema):
    location = LocationField()
    dining_mode = ChoiceField(DINING_MODES, load_default="delivery")


class StoreSchema(BaseSchema):
    store = StoreField()
    location = _optional(LocationField)
    dining_mode = ChoiceField(DINING_MODES, load_default="delivery")


class StoreOnlySchema(BaseSchema):
    store = StoreField()


class MenuSectionSchema(BaseSchema):
    store = StoreField()
    section = SectionField()
    cursor = CursorField()
    location = _optional(LocationField)


class MenuSearchSchema(BaseSchema):
    store = StoreField()
    query = QueryField()
    location = _optional(LocationField)
    dining_mode = ChoiceField(DINING_MODES, load_default="delivery")


class MenuItemSchema(BaseSchema):
    item = ItemField()
    store = _optional(StoreField)
    location = _optional(LocationField)

    @validates_schema
    def _needs_store(self, data, **kwargs):
        item = data.get("item") or {}
        if not item.get("store") and not data.get("store"):
            raise ValidationError("store is required when item is an item id "
                                  "(or pass the full item link as item).", "store")


class SuggestionsSchema(BaseSchema):
    query = QueryField(max_length=100)
    location = LocationField()


class CitiesSchema(BaseSchema):
    country = CountryField()
    region = _optional(RegionField)


class CitySchema(BaseSchema):
    city = CityField()
    country = CountryField()


class CityStoresSchema(BaseSchema):
    city = CityField()
    category = _optional(CategoryField)
    country = CountryField()
    page = PageField(max_page=50)


class NeighborhoodSchema(BaseSchema):
    neighborhood = NeighborhoodField()
    country = CountryField()


class BrandSchema(BaseSchema):
    brand = BrandField()
    country = CountryField()


class BrandStoresSchema(BaseSchema):
    brand = BrandField()
    city = _optional(CityField)
    country = CountryField()

    @validates_schema
    def _needs_city(self, data, **kwargs):
        if not (data.get("brand") or {}).get("city") and not data.get("city"):
            raise ValidationError("city is required (or pass a brand-city link as brand).", "city")
