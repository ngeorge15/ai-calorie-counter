"""Barcode lookup proxy.

The phone never calls USDA or Open Food Facts directly. Centralizing here is
what makes rate-limit compliance possible at all: one deployed backend is one
IP with one budget, whereas N phones scanning independently cannot coordinate
and would get the project blocked.
"""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from .. import product_service
from ..db import get_db
from ..timeutil import utcnow

bp = Blueprint("products", __name__, url_prefix="/api/products")


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
