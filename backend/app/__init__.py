"""Flask application factory."""
import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_jwt_extended import JWTManager
from pydantic import ValidationError

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)
    logging.basicConfig(level=logging.INFO)

    app.config["JWT_SECRET_KEY"] = os.environ["JWT_SECRET"]
    # Long-lived: this is a single-user personal tracker, not a bank. Re-auth
    # on a sideloaded app you re-sign weekly would be pure friction.
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = False
    JWTManager(app)

    from .routes import auth_bp, meals_bp, products_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(meals_bp)
    app.register_blueprint(products_bp)

    @app.errorhandler(ValidationError)
    def on_validation_error(exc: ValidationError):
        # Tell the client exactly which field failed. The whole point of
        # adopting pydantic over the hand-rolled whitelist that used to live
        # in models/meal.py was to stop silently dropping bad input.
        return jsonify({"error": "validation failed", "detail": exc.errors()}), 422

    @app.get("/api/health")
    def health():
        # Render's free tier sleeps after inactivity; this is what the phone
        # pings to wake it before a sync rather than eating the delay mid-save.
        return jsonify({"ok": True})

    return app
