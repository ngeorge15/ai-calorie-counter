"""POST /api/classify: auth, input validation, and the happy path.

Uses a synthetic solid-color JPEG rather than a real food photo -- these
tests aren't about model accuracy (see benchmarks/classifier/ for that),
just that the endpoint decodes, preprocesses, runs the ONNX graph, and
shapes its response correctly.
"""
import io

import numpy as np
import pytest
from PIL import Image

from app import classifier


def _jpeg_bytes(size=(300, 400), color=(120, 60, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="JPEG")
    return buf.getvalue()


def _png_bytes(size=(200, 200), color=(10, 200, 90)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


def test_classify_requires_auth(client):
    response = client.post(
        "/api/classify",
        data={"image": (io.BytesIO(_jpeg_bytes()), "food.jpg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 401


def test_missing_image_field_is_400(app, auth, client):
    response = client.post("/api/classify", data={}, headers=auth,
                           content_type="multipart/form-data")
    assert response.status_code == 400
    assert response.get_json()["error"]


def test_undecodable_file_is_400(app, auth, client):
    response = client.post(
        "/api/classify",
        data={"image": (io.BytesIO(b"not an image, just garbage bytes"), "food.jpg")},
        headers=auth,
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert response.get_json()["error"]


def test_unsupported_format_is_400(app, auth, client):
    """A decodable-but-non-JPEG/PNG image (e.g. GIF) must be rejected too."""
    buf = io.BytesIO()
    Image.new("RGB", (50, 50)).save(buf, format="GIF")

    response = client.post(
        "/api/classify",
        data={"image": (io.BytesIO(buf.getvalue()), "food.gif")},
        headers=auth,
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


@pytest.mark.parametrize("make_bytes,filename", [
    (_jpeg_bytes, "food.jpg"),
    (_png_bytes, "food.png"),
])
def test_happy_path_returns_top3(app, auth, client, make_bytes, filename):
    response = client.post(
        "/api/classify",
        data={"image": (io.BytesIO(make_bytes()), filename)},
        headers=auth,
        content_type="multipart/form-data",
    )
    assert response.status_code == 200

    body = response.get_json()
    predictions = body["predictions"]
    assert len(predictions) == 3

    classes = set(classifier._preprocessing["classes"])
    for pred in predictions:
        assert set(pred.keys()) == {"label", "query", "confidence"}
        assert pred["label"] in classes
        assert pred["query"] == pred["label"].replace("_", " ")
        assert 0.0 <= pred["confidence"] <= 1.0

    # Top-3 should be sorted, highest confidence first.
    confidences = [p["confidence"] for p in predictions]
    assert confidences == sorted(confidences, reverse=True)


def test_model_unavailable_returns_503(app, auth, client, tmp_path, monkeypatch):
    """A missing model file must degrade to a clear 503, not a 500."""
    monkeypatch.setenv("CLASSIFIER_MODEL_DIR", str(tmp_path))
    # Force a fresh load attempt against the (empty) override directory --
    # otherwise the module-level cache from earlier tests would short-circuit.
    monkeypatch.setattr(classifier, "_session", None)
    monkeypatch.setattr(classifier, "_preprocessing", None)
    monkeypatch.setattr(classifier, "_load_error", None)

    response = client.post(
        "/api/classify",
        data={"image": (io.BytesIO(_jpeg_bytes()), "food.jpg")},
        headers=auth,
        content_type="multipart/form-data",
    )
    assert response.status_code == 503
    assert response.get_json()["error"]


def test_rate_limit_triggers_after_repeated_calls(app, auth, client):
    """/api/classify is capped at 20/minute (see app/routes/classify.py)."""
    for _ in range(20):
        response = client.post(
            "/api/classify",
            data={"image": (io.BytesIO(_jpeg_bytes()), "food.jpg")},
            headers=auth,
            content_type="multipart/form-data",
        )
        assert response.status_code == 200

    limited = client.post(
        "/api/classify",
        data={"image": (io.BytesIO(_jpeg_bytes()), "food.jpg")},
        headers=auth,
        content_type="multipart/form-data",
    )
    assert limited.status_code == 429


class TestPreprocessImage:
    """Pure function: a known input produces the expected tensor shape/dtype/range."""

    def test_shape_dtype_and_range(self):
        preprocessing = {
            "resize": {"size": 256},
            "center_crop_size": [224, 224],
            "mean": [0.485, 0.456, 0.406],
            "std": [0.229, 0.224, 0.225],
        }
        image = Image.new("RGB", (400, 300), color=(255, 0, 0))

        tensor = classifier.preprocess_image(image, preprocessing)

        assert tensor.shape == (1, 3, 224, 224)
        assert tensor.dtype == np.float32

        # A uniform pure-red image normalizes to a single value per channel;
        # check it lands where the mean/std say it should, not just "in range".
        expected_r = (1.0 - preprocessing["mean"][0]) / preprocessing["std"][0]
        expected_g = (0.0 - preprocessing["mean"][1]) / preprocessing["std"][1]
        expected_b = (0.0 - preprocessing["mean"][2]) / preprocessing["std"][2]
        np.testing.assert_allclose(tensor[0, 0], expected_r, atol=1e-5)
        np.testing.assert_allclose(tensor[0, 1], expected_g, atol=1e-5)
        np.testing.assert_allclose(tensor[0, 2], expected_b, atol=1e-5)

    def test_non_square_input_still_center_crops_to_target(self):
        preprocessing = {
            "resize": {"size": 256},
            "center_crop_size": [224, 224],
            "mean": [0.0, 0.0, 0.0],
            "std": [1.0, 1.0, 1.0],
        }
        # Wide image: shorter edge (height) drives the resize.
        image = Image.new("RGB", (1000, 500), color=(10, 20, 30))
        tensor = classifier.preprocess_image(image, preprocessing)
        assert tensor.shape == (1, 3, 224, 224)
