import json

import pytest
import torch
from PIL import Image

from data import build_model, build_transforms, label_to_query
from export_onnx import build_preprocessing_metadata
from eval_real_photos import (
    wilson_interval,
    compute_classifier_accuracy,
    compute_end_to_end_rate,
    load_manifest,
    predict_top3,
    validate_manifest_against_classes,
)
from train import evaluate
from usda_search import food_match, normalize_text


def test_model_output_shape():
    model = build_model(num_classes=101, pretrained=False)
    logits = model(torch.zeros(2, 3, 224, 224))
    assert logits.shape == (2, 101)


def test_label_to_query_replaces_underscores():
    assert label_to_query("chicken_curry") == "chicken curry"
    assert label_to_query("pizza") == "pizza"


def test_evaluate_top1_and_top3():
    # 4 classes, batch of 3. Construct logits where the true class is
    # known to rank 1st, 3rd, and outside the top 3, respectively.
    logits = torch.tensor([
        [5.0, 1.0, 1.0, 1.0],  # label 0 is top-1 -> counts for both
        [1.0, 1.0, 5.0, 2.0],  # label 3 ranks 3rd -> top-3 only
        [5.0, 4.0, 3.0, 1.0],  # label 3 ranks 4th -> neither
    ])
    labels = torch.tensor([0, 3, 3])

    class DummyLoader:
        def __iter__(self):
            yield logits, labels

    class DummyModel(torch.nn.Module):
        def forward(self, x):
            return logits

        def eval(self):
            return self

    top1, top3 = evaluate(DummyModel(), DummyLoader(), torch.device("cpu"))
    assert top1 == 1 / 3
    assert top3 == 2 / 3


# --- eval_real_photos.py / usda_search.py -----------------------------------


def test_normalize_text_strips_punctuation_and_case():
    assert normalize_text("Chicken Curry (Homemade)!") == "chicken curry homemade"


def test_food_match_substring():
    assert food_match("pizza", "Cheese pizza, restaurant-prepared, FNDDS")


def test_food_match_token_overlap():
    assert food_match("chicken curry", "Curry, chicken, canned")


def test_food_match_rejects_unrelated_food():
    assert not food_match("waffles", "Beef, ground, 85% lean meat / 15% fat, raw")


def test_load_manifest_json(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps([
        {"filename": "a.jpg", "ground_truth": "chicken curry", "food101_label": "chicken_curry"},
        {"filename": "b.jpg", "ground_truth": "protein shake"},  # out of Food-101 vocab
    ]))
    entries = load_manifest(manifest_path)
    assert entries[0]["food101_label"] == "chicken_curry"
    assert entries[1]["food101_label"] is None
    assert entries[1]["ground_truth"] == "protein shake"


def test_load_manifest_csv(tmp_path):
    manifest_path = tmp_path / "manifest.csv"
    manifest_path.write_text(
        "filename,ground_truth,food101_label,notes\n"
        "a.jpg,chicken curry,chicken_curry,homemade\n"
        "b.jpg,protein shake,,not a Food-101 class\n"
    )
    entries = load_manifest(manifest_path)
    assert entries[0]["notes"] == "homemade"
    assert entries[1]["food101_label"] is None


def test_load_manifest_rejects_missing_required_field(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps([{"filename": "a.jpg"}]))  # no ground_truth
    with pytest.raises(ValueError):
        load_manifest(manifest_path)


def test_load_manifest_rejects_empty_ground_truth(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps([{"filename": "a.jpg", "ground_truth": "  "}]))
    with pytest.raises(ValueError):
        load_manifest(manifest_path)


def test_validate_manifest_against_classes_catches_typo():
    manifest = [{"filename": "a.jpg", "ground_truth": "pizza", "food101_label": "pizzaa", "notes": ""}]
    with pytest.raises(ValueError):
        validate_manifest_against_classes(manifest, ["pizza", "waffles"])


def test_validate_manifest_against_classes_allows_none():
    manifest = [{"filename": "a.jpg", "ground_truth": "protein shake", "food101_label": None, "notes": ""}]
    validate_manifest_against_classes(manifest, ["pizza", "waffles"])  # no raise


def test_compute_classifier_accuracy_only_counts_in_vocab_entries():
    records = [
        {"food101_label": "pizza", "classifier_top1_correct": True, "classifier_top3_correct": True},
        {"food101_label": "waffles", "classifier_top1_correct": False, "classifier_top3_correct": True},
        {"food101_label": None, "classifier_top1_correct": None, "classifier_top3_correct": None},
    ]
    stats = compute_classifier_accuracy(records)
    assert stats["n_in_vocab"] == 2
    assert stats["top1"] == 0.5
    assert stats["top3"] == 1.0


def test_compute_classifier_accuracy_empty_when_no_in_vocab_entries():
    stats = compute_classifier_accuracy([{"food101_label": None, "classifier_top1_correct": None,
                                           "classifier_top3_correct": None}])
    assert stats == {"n_in_vocab": 0, "top1": None, "top3": None}


def test_compute_end_to_end_rate():
    records = [
        {"end_to_end_match": True},
        {"end_to_end_match": False},
        {"end_to_end_match": None},  # skipped (e.g. --skip-usda run)
    ]
    stats = compute_end_to_end_rate(records)
    assert stats["n_evaluated"] == 2
    assert stats["success_rate_top3"] == 0.5


def test_predict_top3_wiring_with_a_synthetic_image(tmp_path):
    # Not a real food photo — a random-noise PNG, purely to exercise the
    # PIL -> timm eval-transform -> model -> topk wiring end to end, the
    # same "dummy tensor, not real Food-101 data" spirit as
    # test_model_output_shape above. No claim about accuracy is made here.
    classes = ["pizza", "waffles", "sushi"]
    model = build_model(num_classes=len(classes), pretrained=False)
    model.eval()
    _, eval_tf = build_transforms(model)

    image_path = tmp_path / "noise.png"
    Image.new("RGB", (224, 224), color=(73, 109, 137)).save(image_path)

    predictions = predict_top3(model, classes, eval_tf, image_path, torch.device("cpu"))
    assert len(predictions) == 3
    assert {p["class"] for p in predictions} == set(classes)
    assert all(p["query"] == p["class"].replace("_", " ") for p in predictions)


# --- export_onnx.py ----------------------------------------------------------


def test_preprocessing_metadata_matches_resolved_timm_config():
    # The serving side must reproduce this pipeline exactly with no
    # hand-typed constants; assert the sidecar metadata actually reflects
    # what timm resolved for this backbone rather than a hardcoded guess.
    import timm

    classes = ["pizza", "waffles", "sushi"]
    model = build_model(num_classes=len(classes), pretrained=False)
    model.eval()

    metadata = build_preprocessing_metadata(model, classes)
    config = timm.data.resolve_data_config({}, model=model)

    assert metadata["input_size"] == list(config["input_size"])
    assert metadata["mean"] == list(config["mean"])
    assert metadata["std"] == list(config["std"])
    assert metadata["crop_pct"] == config["crop_pct"]
    assert metadata["crop_mode"] == config["crop_mode"]
    assert metadata["resize"]["interpolation"] == config["interpolation"]
    assert metadata["channel_order"] == "RGB"


def test_preprocessing_metadata_resize_and_crop_sizes_are_consistent():
    # Resize's shorter-edge target and the center-crop size come straight
    # off the real eval transform (not recomputed by hand), so they can't
    # silently drift apart from what build_transforms() actually does.
    classes = ["pizza", "waffles", "sushi"]
    model = build_model(num_classes=len(classes), pretrained=False)
    model.eval()
    _, eval_tf = build_transforms(model)

    metadata = build_preprocessing_metadata(model, classes)

    resize_tf, crop_tf = eval_tf.transforms[0], eval_tf.transforms[1]
    assert metadata["resize"]["size"] == resize_tf.size
    assert metadata["center_crop_size"] == list(crop_tf.size)
    assert metadata["center_crop_size"] == [metadata["input_size"][1], metadata["input_size"][2]]


def test_preprocessing_metadata_class_list_preserves_order_and_length():
    # The endpoint maps output logit index -> label using this list
    # positionally; any reordering or drop/dup would silently mislabel
    # every prediction.
    classes = ["waffles", "pizza", "sushi", "chicken_curry"]
    model = build_model(num_classes=len(classes), pretrained=False)
    model.eval()

    metadata = build_preprocessing_metadata(model, classes)

    assert metadata["classes"] == classes
    assert len(metadata["classes"]) == len(classes)
    assert len(set(metadata["classes"])) == len(classes)  # no duplicates introduced


def test_wilson_interval_brackets_the_point_estimate():
    r = wilson_interval(17, 20)
    assert r["n"] == 20
    assert r["point"] == 0.85
    assert r["ci95_low"] < r["point"] < r["ci95_high"]


def test_wilson_interval_stays_inside_zero_to_one_at_the_extremes():
    """The reason Wilson is used instead of the normal approximation: at
    p=0 or p=1 the textbook formula produces a degenerate or out-of-range
    interval, which is exactly the small-sample regime this eval runs in."""
    perfect = wilson_interval(20, 20)
    assert perfect["ci95_high"] <= 1.0
    assert perfect["ci95_low"] < 1.0, "20/20 must not imply zero uncertainty"

    zero = wilson_interval(0, 20)
    assert zero["ci95_low"] >= 0.0
    assert zero["ci95_high"] > 0.0, "0/20 must not imply certainty of failure"


def test_wilson_interval_narrows_as_n_grows():
    small = wilson_interval(17, 20)
    large = wilson_interval(170, 200)
    small_width = small["ci95_high"] - small["ci95_low"]
    large_width = large["ci95_high"] - large["ci95_low"]
    assert large_width < small_width


def test_wilson_interval_undefined_for_empty_sample():
    assert wilson_interval(0, 0) is None


def test_classifier_accuracy_reports_intervals_alongside_point_estimates():
    records = [
        {"food101_label": "pizza", "classifier_top1_correct": True,
         "classifier_top3_correct": True},
        {"food101_label": "sushi", "classifier_top1_correct": False,
         "classifier_top3_correct": True},
        # Out-of-vocabulary entries are excluded from classifier accuracy:
        # the model cannot be wrong about a class it never learned.
        {"food101_label": None, "classifier_top1_correct": False,
         "classifier_top3_correct": False},
    ]
    result = compute_classifier_accuracy(records)
    assert result["n_in_vocab"] == 2
    assert result["top1"] == 0.5
    assert result["top3"] == 1.0
    assert result["top1_ci95"]["n"] == 2
    assert result["top3_ci95"]["ci95_high"] <= 1.0
