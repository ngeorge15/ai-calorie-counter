"""Real-photo end-to-end eval: classifier top-3 -> USDA FoodData Central search
-> was the correct food actually surfaced.

This is the eval METHODOLOGY.md calls the one that "actually reflects
whether the feature works" — Food-101 test accuracy (eval.py) only proves
the model learned Food-101's own photos, not that it generalizes to a photo
taken on an actual phone in an actual kitchen.

This script is the HARNESS, not the measurement. It ships with zero photos
and zero results — see benchmarks/classifier/REAL-PHOTOS.md for how to
collect a valid set. Point it at a photo directory + manifest once one
exists:

    python eval_real_photos.py \\
        --photos-dir /path/to/photos \\
        --manifest /path/to/manifest.json

Requires USDA_API_KEY (see backend/.env.example) unless run with
--skip-usda, in which case only classifier top-1/top-3 accuracy is reported
and no end-to-end number is produced. The script never silently skips the
USDA step on its own — a missing key is a hard error.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

import torch
from PIL import Image

from data import build_model, build_transforms, label_to_query
from usda_search import (
    build_session,
    food_match,
    require_api_key,
    search_food,
)

try:
    from dotenv import load_dotenv
    load_dotenv()  # optional convenience: picks up model-training/.env if present
except ImportError:
    pass

REQUIRED_MANIFEST_FIELDS = {"filename", "ground_truth"}


def load_manifest(path: Path) -> list[dict]:
    """Load a JSON (list of objects) or CSV manifest.

    Each entry needs `filename` and `ground_truth` (a free-text description
    of what's actually in the photo). `food101_label` is optional — set it
    to the exact Food-101 class name (e.g. "chicken_curry") when the photo's
    food is genuinely one of the 101 trained classes, and leave it blank/
    null for anything outside that vocabulary. Classifier top-1/top-3
    accuracy is only computed against entries that have it, since the model
    cannot be "correct" on a class it was never trained to predict — but
    the end-to-end USDA check still runs on every entry, because that's
    exactly where an out-of-vocabulary photo is supposed to reveal a
    failure mode.
    """
    if not path.exists():
        raise FileNotFoundError(f"manifest not found: {path}")

    if path.suffix.lower() == ".json":
        entries = json.loads(path.read_text())
    elif path.suffix.lower() == ".csv":
        with path.open(newline="") as f:
            entries = list(csv.DictReader(f))
    else:
        raise ValueError(f"manifest must be .json or .csv, got: {path.suffix}")

    normalized = []
    for i, entry in enumerate(entries):
        missing = REQUIRED_MANIFEST_FIELDS - entry.keys()
        if missing:
            raise ValueError(f"manifest entry {i} missing required field(s): {missing}")
        if not str(entry["filename"]).strip():
            raise ValueError(f"manifest entry {i} has an empty filename")
        if not str(entry["ground_truth"]).strip():
            raise ValueError(f"manifest entry {i} ({entry['filename']}) has an empty ground_truth")

        label = entry.get("food101_label")
        if label is not None and not str(label).strip():
            label = None

        normalized.append({
            "filename": str(entry["filename"]).strip(),
            "ground_truth": str(entry["ground_truth"]).strip(),
            "food101_label": str(label).strip() if label else None,
            "notes": str(entry.get("notes") or "").strip(),
        })
    return normalized


def validate_manifest_against_classes(manifest: list[dict], classes: list[str]) -> None:
    class_set = set(classes)
    bad = [
        (e["filename"], e["food101_label"])
        for e in manifest
        if e["food101_label"] is not None and e["food101_label"] not in class_set
    ]
    if bad:
        lines = "\n".join(f"  {fn}: {label!r}" for fn, label in bad)
        raise ValueError(
            "manifest has food101_label values that don't match any of the "
            f"checkpoint's {len(classes)} classes (likely a typo — Food-101 "
            f"labels are lowercase with underscores, e.g. 'chicken_curry'):\n{lines}"
        )


def load_checkpoint(checkpoint_path: Path, device: torch.device):
    checkpoint = torch.load(checkpoint_path, map_location=device)
    classes = checkpoint["classes"]
    model = build_model(num_classes=len(classes), pretrained=False).to(device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    return model, classes


@torch.no_grad()
def predict_top3(model, classes: list[str], eval_tf, image_path: Path, device: torch.device) -> list[dict]:
    image = Image.open(image_path).convert("RGB")
    tensor = eval_tf(image).unsqueeze(0).to(device)
    logits = model(tensor)
    probs = torch.softmax(logits, dim=1)[0]
    top3 = torch.topk(probs, k=3)
    return [
        {"class": classes[idx], "query": label_to_query(classes[idx]), "confidence": round(prob.item(), 4)}
        for prob, idx in zip(top3.values, top3.indices)
    ]


def wilson_interval(successes: int, n: int, z: float = 1.96) -> dict | None:
    """95% Wilson score interval for a binomial proportion.

    Wilson rather than the textbook normal approximation (p ± z·√(p(1-p)/n)),
    because this eval runs on a deliberately small hand-collected photo set
    and the normal approximation misbehaves exactly there: it produces
    impossible bounds outside [0, 1] near p=0 or p=1, and its coverage is
    poor for small n. Wilson stays inside [0, 1] and holds up at n=20.

    The point is not decoration. At n=20, an observed 85% carries a CI of
    roughly [64%, 95%] — quoting "85%" alone from a sample that size implies
    a precision the data does not support, which is the exact failure this
    project's methodology is written to avoid.
    """
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = z * ((p * (1 - p) / n + z**2 / (4 * n**2)) ** 0.5) / denom
    return {
        "point": round(p, 4),
        "ci95_low": round(max(0.0, center - margin), 4),
        "ci95_high": round(min(1.0, center + margin), 4),
        "n": n,
    }


def compute_classifier_accuracy(records: list[dict]) -> dict:
    in_vocab = [r for r in records if r["food101_label"] is not None]
    if not in_vocab:
        return {"n_in_vocab": 0, "top1": None, "top3": None}
    n = len(in_vocab)
    top1_hits = sum(r["classifier_top1_correct"] for r in in_vocab)
    top3_hits = sum(r["classifier_top3_correct"] for r in in_vocab)
    return {
        "n_in_vocab": n,
        "top1": top1_hits / n,
        "top3": top3_hits / n,
        "top1_ci95": wilson_interval(top1_hits, n),
        "top3_ci95": wilson_interval(top3_hits, n),
    }


def compute_end_to_end_rate(records: list[dict]) -> dict:
    evaluated = [r for r in records if r["end_to_end_match"] is not None]
    if not evaluated:
        return {"n_evaluated": 0, "success_rate_top3": None}
    n = len(evaluated)
    hits = sum(r["end_to_end_match"] for r in evaluated)
    return {
        "n_evaluated": n,
        "success_rate_top3": hits / n,
        "success_rate_ci95": wilson_interval(hits, n),
    }


def run(args) -> dict:
    photos_dir = Path(args.photos_dir)
    manifest = load_manifest(Path(args.manifest))

    missing_files = [e["filename"] for e in manifest if not (photos_dir / e["filename"]).exists()]
    if missing_files:
        raise FileNotFoundError(
            f"{len(missing_files)} manifest filename(s) not found in {photos_dir}: {missing_files}"
        )

    if not args.skip_usda:
        api_key = require_api_key()
    else:
        api_key = None
        print("--skip-usda set: computing classifier accuracy only, no USDA calls will be made.",
              file=sys.stderr)

    device = torch.device(
        "cuda" if torch.cuda.is_available()
        else "mps" if torch.backends.mps.is_available()
        else "cpu"
    )
    model, classes = load_checkpoint(Path(args.checkpoint), device)
    validate_manifest_against_classes(manifest, classes)
    _, eval_tf = build_transforms(model)

    session = build_session() if not args.skip_usda else None
    data_types = [t.strip() for t in args.usda_datatypes.split(",")] if args.usda_datatypes else None
    usda_cache: dict[str, list[dict]] = {}

    records = []
    for entry in manifest:
        top3 = predict_top3(model, classes, eval_tf, photos_dir / entry["filename"], device)
        top3_classes = {p["class"] for p in top3}

        record = dict(entry)
        record["top3_predictions"] = top3
        if entry["food101_label"] is not None:
            record["classifier_top1_correct"] = top3[0]["class"] == entry["food101_label"]
            record["classifier_top3_correct"] = entry["food101_label"] in top3_classes
        else:
            record["classifier_top1_correct"] = None
            record["classifier_top3_correct"] = None

        if args.skip_usda:
            record["usda_results"] = []
            record["end_to_end_match"] = None
            record["matched_on"] = None
        else:
            usda_results = []
            match = None
            for pred in top3:
                query = pred["query"]
                if query not in usda_cache:
                    usda_cache[query] = search_food(
                        session, query, api_key,
                        page_size=args.usda_page_size, data_types=data_types,
                    )
                candidates = usda_cache[query]
                usda_results.append({"query": query, "candidates": candidates})
                if match is None:
                    for candidate in candidates:
                        if food_match(entry["ground_truth"], candidate["description"], args.match_threshold):
                            match = {"query": query, "description": candidate["description"]}
                            break
            record["usda_results"] = usda_results
            record["end_to_end_match"] = match is not None
            record["matched_on"] = match

        records.append(record)
        status = "-" if record["end_to_end_match"] is None else ("OK" if record["end_to_end_match"] else "FAIL")
        print(f"[{status}] {entry['filename']}: ground_truth={entry['ground_truth']!r} "
              f"top1={top3[0]['class']!r} ({top3[0]['confidence']:.2f})")

    classifier_stats = compute_classifier_accuracy(records)
    e2e_stats = compute_end_to_end_rate(records)

    results = {
        f"measured_{date.today().isoformat()}": {
            "real_photo_end_to_end": {
                "checkpoint": str(args.checkpoint),
                "n_photos": len(records),
                "n_classes": len(classes),
                "classifier_accuracy_in_vocab": classifier_stats,
                "end_to_end": {
                    "usda_skipped": args.skip_usda,
                    "match_method": (
                        "automated heuristic (substring / token-overlap / difflib ratio "
                        "against USDA description text) — this is a triage signal, not "
                        "ground truth; verify against the per-photo `usda_results` before "
                        "quoting success_rate_top3 anywhere, especially in README.md"
                    ),
                    **e2e_stats,
                },
                "usda_datatypes_queried": data_types or "all",
                "usda_page_size": args.usda_page_size,
                "match_threshold": args.match_threshold,
                "photos": records,
            }
        }
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nclassifier top1/top3 (n={classifier_stats['n_in_vocab']} in-vocab): "
          f"{classifier_stats['top1']}, {classifier_stats['top3']}")
    print(f"end-to-end success rate (heuristic, n={e2e_stats['n_evaluated']}): "
          f"{e2e_stats['success_rate_top3']}")
    print(f"written to {out_path}")
    return results


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--photos-dir", required=True, help="directory containing the real-phone-camera photos")
    parser.add_argument("--manifest", required=True, help="JSON or CSV file mapping filenames to ground truth")
    parser.add_argument("--checkpoint", default="./checkpoints/best.pt")
    parser.add_argument("--out", default="../benchmarks/classifier/real_photos_results.json")
    parser.add_argument("--skip-usda", action="store_true",
                         help="compute classifier accuracy only; explicit opt-out, never the default")
    parser.add_argument("--usda-page-size", type=int, default=5,
                         help="candidates fetched per USDA query (default 5)")
    parser.add_argument("--usda-datatypes", default=None,
                         help="comma-separated FDC dataType filter, e.g. 'Survey (FNDDS),SR Legacy,Branded'. "
                              "Default: no filter (searches all FDC dataTypes).")
    parser.add_argument("--match-threshold", type=float, default=0.6,
                         help="token-overlap / difflib ratio threshold for the automated match heuristic")
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
