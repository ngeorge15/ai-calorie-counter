"""USDA FoodData Central — primary barcode source.

Chosen over Open Food Facts as the first hop: 2M+ US branded products against
OFF's much thinner US coverage, and 1000 req/hour on a free data.gov key
(no card) against OFF's 15/min per IP.

The awkward part: FDC has no barcode endpoint. The UPC goes in as a free-text
search query, so it will cheerfully return near-matches for a barcode that
doesn't exist. Every result is verified against gtinUpc before we trust it —
without that check you will log someone else's cereal.
"""
import os

from .net import usda_session, TIMEOUT_SECONDS

SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"


def is_configured() -> bool:
    return bool(os.environ.get("USDA_API_KEY"))


class NotConfigured(RuntimeError):
    """USDA_API_KEY is unset.

    fetch_by_barcode() quietly returns None when unkeyed, because a barcode
    scan has a silent fallback (Open Food Facts) sitting right behind it in
    product_service.lookup() -- the caller never needs to know which hop
    answered. GET /api/products/search has no such fallback (OFF's search is
    not wired up here -- see routes/products.py), so silently returning an
    empty list would look identical to "no matches for that name", which is a
    lie. Callers must catch this and tell the phone honestly that search is
    unavailable rather than that nothing was found.
    """


def search_by_name(query: str, page_size: int = 10) -> list[dict]:
    """Free-text search against the same FDC endpoint fetch_by_barcode uses.

    Deliberately NOT restricted to dataType=Branded the way fetch_by_barcode
    is. That restriction exists there because a barcode can only belong to a
    packaged/branded product in the first place. A food *name* like "chicken
    curry" is just as likely to live in FDC's Foundation, SR Legacy, or
    Survey (FNDDS) data as in a branded product, and narrowing to Branded
    here would silently prefer a random packaged match over the better
    generic one.

    Mirrors model-training/usda_search.py's search_food() (same endpoint,
    same trimmed-result spirit) -- that script lives in a separate venv for
    the eval harness and is not imported from here, but the params below are
    kept consistent with it on purpose.
    """
    if not is_configured():
        raise NotConfigured("USDA_API_KEY is not set")

    response = usda_session.get(
        SEARCH_URL,
        params={
            "query": query,
            "pageSize": page_size,
            "api_key": os.environ["USDA_API_KEY"],
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json().get("foods", [])


def _upc_variants(barcode: str) -> set[str]:
    """UPC-A and EAN-13 are the same number with different zero padding.

    A 12-digit US UPC-A often scans back as 13 digits with a leading zero,
    while FDC may store either form. Raw string comparison would miss the
    match, so compare across the padded variants.
    """
    digits = "".join(c for c in str(barcode) if c.isdigit()).lstrip("0")
    if not digits:
        return set()
    return {digits, digits.zfill(12), digits.zfill(13), digits.zfill(14)}


def fetch_by_barcode(barcode: str) -> dict | None:
    """Return the FDC food whose gtinUpc matches, or None."""
    if not is_configured():
        return None

    wanted = _upc_variants(barcode)
    if not wanted:
        return None

    response = usda_session.get(
        SEARCH_URL,
        params={
            "query": barcode,
            "dataType": "Branded",
            "pageSize": 10,
            "api_key": os.environ["USDA_API_KEY"],
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    for food in response.json().get("foods", []):
        gtin = food.get("gtinUpc")
        if gtin and _upc_variants(gtin) & wanted:
            return food
    return None
