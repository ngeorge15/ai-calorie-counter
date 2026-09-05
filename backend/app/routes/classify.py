"""Food-photo classification.

The phone uploads a photo; we return the model's top-3 label guesses --
classifier output (a Food-101 label + our own confidence from softmaxing the
model's raw logits), not USDA/OFF nutrition data. This deliberately does NOT
call product_service.py: coupling a CPU-bound, purely-local-model endpoint to
one that depends on outbound USDA/OFF calls would coordinate two concerns
that have nothing to do with each other. The client takes the `query` string
we hand back and hits the existing product-search path itself.
"""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from .. import classifier
from ..limiter import limiter

bp = Blueprint("classify", __name__, url_prefix="/api/classify")


# Inference is the single most CPU-expensive thing this server does, on a
# free-tier box with one shared vCPU and exactly one gunicorn worker (see
# render.yaml) -- a burst of classify calls serializes behind each other on
# that one worker and would starve every other request (health checks, meal
# sync) until it drains. This is a single-user app: photographing several
# meals in one sitting, or retrying after a bad crop, is normal use; dozens
# of calls a minute is not. 20/minute comfortably covers the former while
# bounding the worst-case inference load the free tier ever has to absorb
# in a burst.
@bp.post("")
@jwt_required()
@limiter.limit("20 per minute")
def classify():
    upload = request.files.get("image")
    if upload is None or upload.filename == "":
        return jsonify({"error": "missing image"}), 400

    file_bytes = upload.read()

    try:
        predictions = classifier.predict_top3(file_bytes)
    except classifier.InvalidImage as exc:
        return jsonify({"error": "invalid image", "detail": str(exc)}), 400
    except classifier.ModelUnavailable as exc:
        return jsonify({"error": "classifier unavailable", "detail": str(exc)}), 503

    return jsonify({"predictions": predictions})
