"""ONNX food-classifier inference: model loading, preprocessing, prediction.

Loaded once per process (see `_load`) rather than per request -- this is a
512MB Render free-tier box; re-loading a 13MB ONNX graph and spinning up a
fresh onnxruntime session on every /api/classify call would be slow and, on
a box this tight on RAM, wasteful of the one resource it doesn't have much
of. `--workers 1` in render.yaml means there's exactly one process to warm
up; a second worker would just duplicate this (read-only, immutable) state
in its own memory, not race on it, so nothing here needs cross-process
coordination the way the OFF/limiter in-memory buckets do.

Preprocessing intentionally reads every numeric constant (input size, resize
behavior, crop size, mean/std, class list) from preprocessing.json at
runtime instead of hardcoding it here. See model-training/export_onnx.py's
docstring: a silently mismatched train/serve preprocessing pipeline degrades
accuracy with no error anywhere -- that's the whole reason that file exists
as the single source of truth.
"""
import io
import json
import os
import threading
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

_SUPPORTED_FORMATS = {"JPEG", "PNG"}

_lock = threading.Lock()
_session = None
_preprocessing = None
_load_error = None  # set once loading has failed, so we don't retry every request


class ModelUnavailable(Exception):
    """The ONNX model or its preprocessing metadata isn't available.

    The route layer turns this into a 503. It must never surface as an
    unhandled exception at import time: both `flask run`/pytest (no model
    file checked out, or onnxruntime not installed yet) and a Render deploy
    that happens to run before the model artifact is in place need
    `create_app()` to succeed regardless.
    """


class InvalidImage(Exception):
    """Upload isn't a decodable JPEG/PNG. The route layer turns this into 400."""


def _model_dir() -> Path:
    """Where model.onnx and preprocessing.json live at runtime.

    CLASSIFIER_MODEL_DIR overrides this outright. Otherwise it resolves
    relative to this file (not the process's cwd), landing on
    model-training/checkpoints/ as a sibling of backend/ in the same repo.

    Why not copy the model under backend/: model-training/checkpoints/ is
    already committed to git (see the repo .gitignore's comment on why the
    14MB checkpoint is small enough to commit directly) -- duplicating the
    13MB ONNX file under backend/ would mean two copies to keep in sync in
    git for no benefit.

    Why resolve from __file__ instead of cwd: Render's "root directory" /
    render.yaml's build & start commands run from backend/, but that only
    changes the working directory for those commands -- Render still clones
    the whole git repo, so model-training/ is on disk as a sibling of
    backend/ either way. Resolving from __file__ finds it regardless of
    which directory a given command happened to be launched from.
    """
    override = os.environ.get("CLASSIFIER_MODEL_DIR")
    if override:
        return Path(override)
    # backend/app/classifier.py -> backend/app -> backend -> repo root
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "model-training" / "checkpoints"


def _load() -> None:
    """Load the ONNX session + preprocessing.json once per process.

    Safe to call on every request; after the first successful (or failed)
    attempt this is just a None-check, no filesystem or ONNX work.
    """
    global _session, _preprocessing, _load_error

    if _session is not None and _preprocessing is not None:
        return
    if _load_error is not None:
        raise ModelUnavailable(_load_error)

    with _lock:
        if _session is not None and _preprocessing is not None:
            return
        if _load_error is not None:
            raise ModelUnavailable(_load_error)

        model_dir = _model_dir()
        onnx_path = model_dir / "model.onnx"
        preprocessing_path = model_dir / "preprocessing.json"

        if not onnx_path.exists() or not preprocessing_path.exists():
            _load_error = (
                f"classifier model not found at {model_dir} "
                "(expected model.onnx and preprocessing.json there; set "
                "CLASSIFIER_MODEL_DIR to override)"
            )
            raise ModelUnavailable(_load_error)

        try:
            # Imported lazily (not at module top) so importing this module --
            # and therefore the whole app -- never fails just because
            # onnxruntime isn't installed yet or the model file is absent;
            # only calling predict_top3()/is_available() can hit that.
            import onnxruntime as ort

            preprocessing = json.loads(preprocessing_path.read_text())
            session = ort.InferenceSession(
                str(onnx_path), providers=["CPUExecutionProvider"]
            )
        except ModelUnavailable:
            raise
        except Exception as exc:  # pragma: no cover - defensive, not expected in practice
            _load_error = f"failed to load classifier model: {exc}"
            raise ModelUnavailable(_load_error) from exc

        _preprocessing = preprocessing
        _session = session


def is_available() -> bool:
    """Best-effort readiness check, e.g. for a future health/status route."""
    try:
        _load()
        return True
    except ModelUnavailable:
        return False


def decode_image(file_bytes: bytes) -> Image.Image:
    """Decode + validate an upload.

    Raises InvalidImage for anything that isn't a clean JPEG/PNG: corrupt or
    truncated data, unsupported formats (gif, webp, pdf, ...), or an empty
    body. Never lets Pillow's exceptions escape as an unhandled 500.
    """
    if not file_bytes:
        raise InvalidImage("empty file")

    try:
        image = Image.open(io.BytesIO(file_bytes))
        image.load()  # force full decode now; truncated/corrupt data raises here
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImage(f"not a decodable image: {exc}") from exc

    if image.format not in _SUPPORTED_FORMATS:
        raise InvalidImage(f"unsupported image format: {image.format}")

    return image.convert("RGB")


def preprocess_image(image: Image.Image, preprocessing: dict) -> np.ndarray:
    """Reproduce preprocessing.json's pipeline: resize shorter edge (bicubic,
    antialiased), center crop, scale to [0,1], normalize, NCHW float32.

    preprocessing.json records numbers, not code, so this mirrors
    torchvision.transforms.Resize + CenterCrop semantics by hand (the same
    ops build_transforms() in model-training/data.py applies at train/eval
    time):
      - Resize: shorter edge -> `resize.size`, aspect preserved, new long
        edge computed as int(size * long / short) -- torchvision truncates
        here, it does not round.
      - CenterCrop: crop offset is round((dim - crop_dim) / 2) -- torchvision
        rounds here, unlike the resize step above.
    Pillow's BICUBIC resize is anti-aliased on downsampling by construction
    (no separate flag needed), which is what `antialias: true` in
    preprocessing.json is describing.
    """
    resize_size = preprocessing["resize"]["size"]
    crop_h, crop_w = preprocessing["center_crop_size"]
    mean = np.array(preprocessing["mean"], dtype=np.float32)
    std = np.array(preprocessing["std"], dtype=np.float32)

    w, h = image.size
    if w <= h:
        new_w = resize_size
        new_h = int(resize_size * h / w)
    else:
        new_h = resize_size
        new_w = int(resize_size * w / h)
    resized = image.resize((new_w, new_h), resample=Image.BICUBIC)

    left = round((new_w - crop_w) / 2.0)
    top = round((new_h - crop_h) / 2.0)
    cropped = resized.crop((left, top, left + crop_w, top + crop_h))

    arr = np.asarray(cropped, dtype=np.float32) / 255.0  # HWC, [0,1]
    arr = (arr - mean) / std
    arr = arr.transpose(2, 0, 1)  # HWC -> CHW
    return arr[np.newaxis, ...].astype(np.float32)  # add batch dim -> NCHW


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / np.sum(exp, axis=-1, keepdims=True)


def predict_top3(file_bytes: bytes) -> list[dict]:
    """Full pipeline: decode -> preprocess -> ONNX forward -> softmax -> top 3.

    Raises ModelUnavailable (-> 503) or InvalidImage (-> 400); the route
    layer is responsible for turning those into HTTP responses.
    """
    _load()
    image = decode_image(file_bytes)
    tensor = preprocess_image(image, _preprocessing)

    input_name = _session.get_inputs()[0].name
    logits = _session.run(["logits"], {input_name: tensor})[0]
    probs = _softmax(logits)[0]

    classes = _preprocessing["classes"]
    top_indices = np.argsort(-probs)[:3]
    return [
        {
            "label": classes[i],
            "query": classes[i].replace("_", " "),
            "confidence": float(probs[i]),
        }
        for i in top_indices
    ]
