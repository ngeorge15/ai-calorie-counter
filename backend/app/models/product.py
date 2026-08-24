"""Open Food Facts product -> our nutrition shape.

OFF is crowd-sourced, so fields are frequently missing, occasionally absurd,
and inconsistently named. Everything here is best-effort and nullable: a
partial product the user can correct beats a hard failure at the shelf.
"""

# OFF reports sodium in grams per 100g; we store mg to match nutrition labels.
_PER_100G = {
    "calories": ("energy-kcal_100g",),
    "protein_g": ("proteins_100g",),
    "carbs_g": ("carbohydrates_100g",),
    "fat_g": ("fat_100g",),
    "fiber_g": ("fiber_100g",),
    "sugar_g": ("sugars_100g",),
}


def _num(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    # OFF has entries with 900000 kcal/100g from typos. 900 is already above
    # pure fat (884), so anything past it is bad data, not a real food.
    return n if 0 <= n <= 900 else None


def normalize_off_product(off: dict) -> dict:
    nutriments = off.get("nutriments") or {}

    per_100g = {}
    for our_key, off_keys in _PER_100G.items():
        for key in off_keys:
            value = _num(nutriments.get(key))
            if value is not None:
                per_100g[our_key] = value
                break
        else:
            per_100g[our_key] = None

    sodium_g = _num(nutriments.get("sodium_100g"))
    per_100g["sodium_mg"] = round(sodium_g * 1000, 1) if sodium_g is not None else None

    return {
        "barcode": off.get("code"),
        "name": (off.get("product_name") or "").strip() or None,
        "brand": (off.get("brands") or "").split(",")[0].strip() or None,
        "serving_size": off.get("serving_size"),
        "serving_g": _num(off.get("serving_quantity")),
        "image_url": off.get("image_front_small_url") or off.get("image_url"),
        "per_100g": per_100g,
        "source": "off",
    }


# USDA nutrient numbers are stable identifiers; nutrientName spelling is not
# ("Total lipid (fat)" vs "Fat"), so we match on the number.
_USDA_NUTRIENTS = {
    "208": "calories",
    "203": "protein_g",
    "205": "carbs_g",
    "204": "fat_g",
    "291": "fiber_g",
    "269": "sugar_g",
    "307": "sodium_mg",  # already mg in FDC
}


def normalize_usda_product(food: dict) -> dict:
    """FDC Branded food -> the same shape as normalize_off_product().

    Both sources must produce an identical shape, because the client cannot be
    made to care which hop in the chain answered.
    """
    per_100g = {key: None for key in
                ("calories", "protein_g", "carbs_g", "fat_g",
                 "fiber_g", "sugar_g", "sodium_mg")}

    # Branded foodNutrients are reported per 100g/100ml.
    for nutrient in food.get("foodNutrients") or []:
        number = str(nutrient.get("nutrientNumber") or "")
        key = _USDA_NUTRIENTS.get(number)
        if not key:
            continue
        value = _num(nutrient.get("value"))
        if value is None and key == "sodium_mg":
            continue
        # _num caps at 900 for per-100g macros; sodium in mg legitimately
        # exceeds that, so it gets validated separately.
        if key == "sodium_mg":
            raw = nutrient.get("value")
            try:
                per_100g[key] = round(float(raw), 1)
            except (TypeError, ValueError):
                pass
        elif value is not None:
            per_100g[key] = value

    serving_g = _num(food.get("servingSize"))
    if serving_g is not None and str(food.get("servingSizeUnit", "")).lower() not in ("g", "ml", ""):
        serving_g = None  # oz/cup servings need conversion we don't do here

    return {
        "barcode": str(food.get("gtinUpc") or "").lstrip("0") or None,
        "name": (food.get("description") or "").strip().title() or None,
        "brand": (food.get("brandName") or food.get("brandOwner") or "").strip() or None,
        "serving_size": food.get("householdServingFullText"),
        "serving_g": serving_g,
        "image_url": None,  # FDC carries no product imagery
        "per_100g": per_100g,
        "source": "usda",
    }
