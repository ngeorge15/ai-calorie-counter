"""Barcode lookup proxy, plus text search for turning a food name into
candidate products.

The phone never calls USDA or Open Food Facts directly. Centralizing here is
what makes rate-limit compliance possible at all: one deployed backend is one
IP with one budget, whereas N phones scanning independently cannot coordinate
and would get the project blocked.
"""
import requests
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from .. import product_service, usda_client
from ..db import get_db
from ..limiter import limiter
from ..models import normalize_usda_product
from ..timeutil import utcnow

bp = Blueprint("products", __name__, url_prefix="/api/products")

# A phone picker sheet, not a paginated results page -- 8 candidates is
# enough to cover FDC's genuinely different top matches (a couple of
# datasets/brands deep) without making the user scroll a wall of
# near-duplicate "CHICKEN CURRY, UPC 0001" / "...UPC 0002" branded entries.
# Requested directly as FDC's pageSize so we never pay to transfer results
# we'd throw away.
MAX_SEARCH_RESULTS = 8

# Query length: real food names/dishes ("grilled chicken caesar salad") sit
# well under 50 characters. 100 is generous headroom for a wordy dish name
# while still rejecting a pathologically long string before it goes out over
# the network.
MAX_QUERY_LENGTH = 100


@bp.get("/search")
@jwt_required()
# net.py's usda_session already caps the whole process at USDA's 1000/hour
# free-key budget, shared with every barcode lookup this endpoint's sibling
# makes. That session-level limiter is what protects USDA's actual quota; this
# decorator is a second, independent guard against a single misbehaving phone
# client (e.g. a retry loop, or firing a request per keystroke instead of on
# submit) burning through that shared hourly budget by itself. 10/minute caps
# this route's own worst case at 600/hour -- well under the 1000/hour total --
# leaving headroom for concurrent barcode scans, while still being far more
# than an interactive "type a food name, hit search" flow ever needs.
@limiter.limit("10 per minute")
def search_products():
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"error": "missing search query"}), 400
    if len(query) > MAX_QUERY_LENGTH:
        return jsonify({"error": "search query too long",
                        "max_length": MAX_QUERY_LENGTH}), 400

    if not usda_client.is_configured():
        # Distinct from "no matches" -- see usda_client.NotConfigured.
        return jsonify({"error": "product search unavailable",
                        "detail": "USDA_API_KEY is not configured"}), 503

    try:
        foods = usda_client.search_by_name(query, page_size=MAX_SEARCH_RESULTS)
    except usda_client.NotConfigured:
        return jsonify({"error": "product search unavailable",
                        "detail": "USDA_API_KEY is not configured"}), 503
    except requests.RequestException as exc:
        # Transport failure or a non-2xx from FDC (raise_for_status). Unlike
        # the barcode chain, there is no second source to fall back to here,
        # so this must surface as a real error -- an empty "products": []
        # would look exactly like a genuine zero-result search.
        return jsonify({"error": "product search failed",
                        "detail": str(exc)}), 502

    # No Mongo caching here, unlike barcode lookups. product_service's cache
    # works because a barcode is a stable 1:1 key -> one product forever. A
    # free-text query is not: "chicken curry" has no single correct answer,
    # FDC's ranking for it can legitimately change between calls, and two
    # different users (or the same user later) typing the same words are
    # picking from a list, not fetching a fixed record. Caching the query
    # would mean inventing a staleness/invalidation policy for a mapping that
    # was never 1:1 in the first place, to save calls against a budget
    # (1000/hour) this single-user app is nowhere close to exhausting.
    products = []
    for food in foods[:MAX_SEARCH_RESULTS]:
        product = normalize_usda_product(food)
        # Superset of the barcode-lookup Product shape: fdc_id has no
        # equivalent in that shape (a barcode result IS the match; a search
        # result is one of several candidates), but it's cheap provenance for
        # the client to log or use to dedupe, so it rides along as an extra
        # field rather than being dropped.
        product["fdc_id"] = food.get("fdcId")
        products.append(product)

    return jsonify({"products": products, "count": len(products)})


@bp.get("/<barcode>")
@jwt_required()
def get_product(barcode):
    product, origin = product_service.lookup(barcode)

    if product is None:
        # 404 with a shape the client can still act on: it shows the manual
        # entry form pre-filled with the barcode. A miss is never a dead end.
        return jsonify({"error": "not found", "barcode": barcode,
                        "origin": origin}), 404

    # `origin` feeds the Phase 4 cache-latency benchmark — the client records
    # it alongside its own timing so hit vs miss can be separated honestly.
    return jsonify({"product": product, "origin": origin})


@bp.post("/<barcode>")
@jwt_required()
def contribute_product(barcode):
    """Cache a product the user typed in after a lookup miss.

    Turns every miss into a permanent hit for next time. Deliberately stored
    with source='user' so it is never confused with authoritative data, and
    never overwrites a USDA or OFF record.
    """
    body = request.get_json(silent=True) or {}
    barcode = "".join(c for c in str(barcode) if c.isdigit())
    if not barcode:
        return jsonify({"error": "invalid barcode"}), 400

    existing = get_db().products.find_one({"barcode": barcode})
    if existing and existing.get("source") in ("usda", "off"):
        return jsonify({"product": {k: v for k, v in existing.items()
                                    if k not in ("_id", "cached_at")},
                        "origin": "cache"}), 200

    product = {
        "barcode": barcode,
        "name": (body.get("name") or "").strip() or None,
        "brand": (body.get("brand") or "").strip() or None,
        "serving_size": body.get("serving_size"),
        "serving_g": body.get("serving_g"),
        "image_url": None,
        "per_100g": body.get("per_100g") or {},
        "source": "user",
    }
    get_db().products.update_one(
        {"barcode": barcode},
        {"$set": {**product, "cached_at": utcnow()}},
        upsert=True,
    )
    return jsonify({"product": product, "origin": "user"}), 201
