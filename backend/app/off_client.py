"""Open Food Facts — fallback barcode source, via the official SDK.

Using the SDK rather than raw requests because it handles User-Agent
compliance (OFF blocks unidentified clients) and absorbs API drift. It builds
its own session and exposes no hook for one, so the rate limit is enforced at
the call site — see net.acquire_off_slot().
"""
from functools import lru_cache

from openfoodfacts import API, APIVersion, Country, Environment

from .net import acquire_off_slot, off_user_agent, TIMEOUT_SECONDS

# Only the fields we actually map, so OFF isn't shipping us a 200KB document
# per scan on a phone connection.
FIELDS = [
    "code", "product_name", "brands", "serving_size", "serving_quantity",
    "image_front_small_url", "image_url", "nutriments",
]


@lru_cache(maxsize=1)
def _api() -> API:
    return API(
        user_agent=off_user_agent(),
        country=Country.world,
        version=APIVersion.v2,
        environment=Environment.org,
        timeout=TIMEOUT_SECONDS,
    )


def fetch_by_barcode(barcode: str) -> dict | None:
    """Return the OFF product dict, or None if OFF doesn't know this barcode."""
    acquire_off_slot()
    return _api().product.get(barcode, fields=FIELDS)
