"""Meal CRUD and offline sync.

THE CLOCK RULE, because getting this wrong fails silently:

  updated_at         client's edit clock. Used ONLY to decide which of two
                     competing edits is newer (last-write-wins).
  server_updated_at  our clock. Used ONLY as the pull cursor.

They must never be swapped. If the pull cursor came from the client's clock, a
phone running fast would push a meal stamped in the future, save that as its
cursor, and then never receive any server change written in the gap — silently,
forever. One monotonic authority for the cursor: us.
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

from ..db import get_db
from ..schemas import MealIn, SyncRequest
from ..timeutil import floor_ms, parse_iso, to_iso, utcnow

bp = Blueprint("meals", __name__, url_prefix="/api/meals")

MAX_SYNC_BATCH = 500
TOMBSTONE_RETENTION_DAYS = 30


def _serialize(doc):
    doc = dict(doc)
    doc.pop("_id", None)
    doc.pop("user_id", None)
    for field in ("updated_at", "server_updated_at", "created_at"):
        if field in doc:
            doc[field] = to_iso(doc[field])
    return doc


def _apply_change(user_id, meal: MealIn):
    """Upsert one validated change under last-write-wins.

    Returns (status, doc) where status is 'applied' or 'conflict'. A conflict
    means the server already holds a newer edit; we hand it back so the client
    can overwrite its local copy rather than silently diverging.
    """
    client_id = meal.client_id
    edited_at = meal.updated_at or utcnow()
    meals = get_db().meals

    fields = meal.model_dump(exclude={"client_id", "updated_at"})
    fields["updated_at"] = edited_at
    fields["server_updated_at"] = utcnow()

    # Guard on updated_at so a slow retry can't clobber a newer edit. If no
    # document matched, either it doesn't exist yet or ours is stale.
    result = meals.update_one(
        {"user_id": user_id, "client_id": client_id,
         "updated_at": {"$lt": edited_at}},
        {"$set": fields},
    )
    if result.matched_count:
        return "applied", None

    try:
        meals.insert_one({
            "user_id": user_id,
            "client_id": client_id,
            "created_at": utcnow(),
            **fields,
        })
        return "applied", None
    except DuplicateKeyError:
        # It exists and its updated_at is >= ours: the server's copy wins.
        existing = meals.find_one({"user_id": user_id, "client_id": client_id})
        return "conflict", _serialize(existing)


@bp.post("/sync")
@jwt_required()
def sync():
    """Push local changes and pull everything since the last cursor."""
    try:
        payload = SyncRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "validation failed",
                        "detail": exc.errors()}), 422

    user_id = get_jwt_identity()

    # Snapshot our clock BEFORE writing, floored to Mongo's millisecond
    # storage granularity. Anything written during this request gets a
    # server_updated_at >= this value even after BSON truncation, so returning
    # it as the next cursor can never skip a change — at worst the client
    # re-receives one, which its upsert makes free. See timeutil.floor_ms.
    cursor_now = floor_ms(utcnow())

    applied, conflicts = [], []
    for meal in payload.changes:
        status, doc = _apply_change(user_id, meal)
        if status == "applied":
            applied.append(meal.client_id)
        else:
            conflicts.append(doc)

    query = {"user_id": user_id}
    since = payload.since
    if since:
        # $gte, not $gt: the boundary must overlap rather than gap.
        query["server_updated_at"] = {"$gte": floor_ms(since)}

    pulled = [
        _serialize(doc)
        for doc in get_db().meals.find(query).sort("server_updated_at", 1)
    ]

    return jsonify({
        "server_time": to_iso(cursor_now),
        "applied": applied,
        "conflicts": conflicts,
        "changes": pulled,
    })


@bp.get("")
@jwt_required()
def list_meals():
    """List meals for a day, or everything since a cursor."""
    query = {"user_id": get_jwt_identity(), "deleted": {"$ne": True}}

    day = request.args.get("date")  # YYYY-MM-DD, matched on the client's local day
    if day:
        query["eaten_at"] = {"$regex": f"^{day}"}

    since = parse_iso(request.args.get("since"))
    if since:
        query["server_updated_at"] = {"$gte": floor_ms(since)}

    docs = get_db().meals.find(query).sort("eaten_at", -1).limit(500)
    return jsonify({"meals": [_serialize(d) for d in docs]})


@bp.delete("/<client_id>")
@jwt_required()
def delete_meal(client_id):
    """Tombstone, never a hard delete — a removed row can't propagate."""
    result = get_db().meals.update_one(
        {"user_id": get_jwt_identity(), "client_id": client_id},
        {"$set": {"deleted": True, "updated_at": utcnow(),
                  "server_updated_at": utcnow()}},
    )
    if not result.matched_count:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@bp.get("/export.csv")
@jwt_required()
def export_csv():
    """Escape hatch: your history should never be trapped in this app."""
    import csv, io

    columns = ["eaten_at", "meal_type", "name", "brand", "barcode", "serving_g",
               "calories", "protein_g", "carbs_g", "fat_g", "fiber_g",
               "sugar_g", "sodium_mg", "source", "user_edited"]

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    docs = get_db().meals.find(
        {"user_id": get_jwt_identity(), "deleted": {"$ne": True}}
    ).sort("eaten_at", 1)
    for doc in docs:
        writer.writerow({c: doc.get(c, "") for c in columns})

    return buffer.getvalue(), 200, {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": 'attachment; filename="meals.csv"',
    }
