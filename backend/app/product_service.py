"""Barcode -> nutrition, in priority order.

    Mongo cache  ->  USDA FoodData Central  ->  Open Food Facts  ->  miss

Ordering is coverage-driven: FDC carries far more US branded products, so
trying it first means fewer scans fall through to OFF and fewer still fail
outright at the shelf.

The cache has no TTL by design. Product formulations change on the order of
years, and a slightly stale macro is enormously better than a failed scan
while you're standing in a grocery aisle. It also keeps us far inside OFF's
rate limit, which is the whole reason the phone talks to us instead of to OFF.
"""
import logging

import requests

from .db import get_db
from .models import normalize_off_product, normalize_usda_product
from .net import RateLimited
from .timeutil import utcnow
from . import off_client, usda_client

log = logging.getLogger(__name__)


def _cache_get(barcode: str) -> dict | None:
    return get_db().products.find_one({"barcode": barcode}, {"_id": 0})


def _cache_put(barcode: str, product: dict) -> None:
    get_db().products.update_one(
        {"barcode": barcode},
        {"$set": {**product, "barcode": barcode, "cached_at": utcnow()}},
        upsert=True,
    )


def lookup(barcode: str) -> tuple[dict | None, str]:
    """Return (product, origin) where origin is cache | usda | off | miss."""
    barcode = "".join(c for c in str(barcode) if c.isdigit())
    if not barcode:
        return None, "miss"

    cached = _cache_get(barcode)
    if cached:
        cached.pop("cached_at", None)
        return cached, "cache"

    # Hop 1: USDA. A transport failure here must not block the OFF fallback.
    try:
        food = usda_client.fetch_by_barcode(barcode)
        if food:
            product = normalize_usda_product(food)
            _cache_put(barcode, product)
            return product, "usda"
    except requests.RequestException as exc:
        log.warning("USDA lookup failed for %s: %s", barcode, exc)

    # Hop 2: Open Food Facts.
    try:
        off = off_client.fetch_by_barcode(barcode)
        if off:
            product = normalize_off_product(off)
            _cache_put(barcode, product)
            return product, "off"
    except RateLimited:
        log.warning("OFF rate limit hit for %s", barcode)
    except requests.RequestException as exc:
        log.warning("OFF lookup failed for %s: %s", barcode, exc)

    # A miss is a normal outcome, not an error: the user types it in and we
    # cache what they entered. Never block logging on a lookup.
    return None, "miss"
