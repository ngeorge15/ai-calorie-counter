import datetime as dt
import uuid

from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import get_db
from ..schemas import Credentials

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _parse():
    return Credentials.model_validate(request.get_json(silent=True) or {})


@bp.post("/register")
def register():
    try:
        creds = _parse()
    except ValidationError as exc:
        return jsonify({"error": "validation failed", "detail": exc.errors()}), 422

    user_id = str(uuid.uuid4())
    try:
        get_db().users.insert_one({
            "_id": user_id,
            "email": creds.email,
            "password_hash": generate_password_hash(creds.password),
            "created_at": dt.datetime.now(dt.timezone.utc),
        })
    except DuplicateKeyError:
        return jsonify({"error": "email already registered"}), 409

    return jsonify({"token": create_access_token(identity=user_id),
                    "user_id": user_id}), 201


@bp.post("/login")
def login():
    try:
        creds = _parse()
    except ValidationError as exc:
        return jsonify({"error": "validation failed", "detail": exc.errors()}), 422

    user = get_db().users.find_one({"email": creds.email})
    if not user or not check_password_hash(user["password_hash"], creds.password):
        # Identical response either way — don't leak which emails are registered.
        return jsonify({"error": "invalid credentials"}), 401

    return jsonify({"token": create_access_token(identity=user["_id"]),
                    "user_id": user["_id"]})
