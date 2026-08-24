"""MongoDB Atlas connection and index setup.

Single shared client — PyMongo pools connections internally, and Atlas M0
caps us at 500 connections, so we never build more than one client.
"""
import os
from pymongo import MongoClient, ASCENDING

_client = None
_db = None


def get_db():
    global _client, _db
    if _db is None:
        uri = os.environ["MONGODB_URI"]
        _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        _db = _client[os.environ.get("MONGODB_DB", "calorie_counter")]
        _ensure_indexes(_db)
    return _db


def _ensure_indexes(db):
    db.users.create_index([("email", ASCENDING)], unique=True)

    # Sync queries are always "my meals, changed since T", and client_id is the
    # idempotency key that lets an offline-created meal be pushed twice safely.
    db.meals.create_index([("user_id", ASCENDING), ("updated_at", ASCENDING)])
    db.meals.create_index(
        [("user_id", ASCENDING), ("client_id", ASCENDING)], unique=True
    )

    # OFF product cache. No TTL by design — product data changes slowly and a
    # stale macro is far better than a failed scan at the grocery store.
    db.products.create_index([("barcode", ASCENDING)], unique=True)
