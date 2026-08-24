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
