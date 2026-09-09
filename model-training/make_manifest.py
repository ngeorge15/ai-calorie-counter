"""Scaffold a manifest from a directory of photos, so labelling is a
fill-in-the-blanks job rather than typing 50 filenames by hand.

Writes one entry per image found, with `filename` filled in and
`ground_truth` left empty for you. Optionally runs the classifier and
records its guesses as a *hint* in a separate field.

  python make_manifest.py --photos-dir ~/Desktop/meal-photos --out manifest.json
  python make_manifest.py --photos-dir ~/Desktop/meal-photos --out manifest.json --hint

On --hint: the model's own guesses are written to `model_hint`, which the
eval NEVER reads. It exists so you can skim rather than recall the exact
Food-101 spelling. Do not paste a hint into `ground_truth` without looking
at the photo — that would grade the model against its own output and
guarantee a perfect score. REAL-PHOTOS.md says the same thing at more
length; it's repeated here because this is the moment the mistake is easy
to make.

Re-running against a directory of new photos merges: existing labelled
entries are preserved, only genuinely new files get appended.
"""
import argparse
import json
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".HEIC", ".JPG", ".JPEG", ".PNG"}


def find_images(photos_dir: Path) -> list[str]:
    if not photos_dir.is_dir():
        raise NotADirectoryError(f"not a directory: {photos_dir}")
    names = [
        p.name for p in sorted(photos_dir.iterdir())
        if p.is_file() and p.suffix in IMAGE_SUFFIXES
    ]
    if not names:
        raise FileNotFoundError(
            f"no images found in {photos_dir} "
            f"(looked for {', '.join(sorted(IMAGE_SUFFIXES))})"
        )
    return names


def load_existing(out_path: Path) -> dict[str, dict]:
    """Existing entries keyed by filename, so re-running never clobbers
    labels you already wrote."""
    if not out_path.exists():
        return {}
    try:
        entries = json.loads(out_path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"{out_path} exists but isn't valid JSON ({exc}). "
            "Move it aside rather than letting this overwrite your labels."
        )
    return {e["filename"]: e for e in entries if isinstance(e, dict) and "filename" in e}


def build_hints(photos_dir: Path, names: list[str], checkpoint: Path) -> dict[str, list[str]]:
    # Imported lazily: scaffolding a manifest shouldn't require torch to be
    # installed or a checkpoint to exist unless hints were actually asked for.
    import torch
    from data import build_model, build_transforms
    from PIL import Image

    ck = torch.load(checkpoint, map_location="cpu", weights_only=False)
    classes = ck["classes"]
    model = build_model(num_classes=len(classes), pretrained=False)
    model.load_state_dict(ck["model_state_dict"])
    model.eval()
    _, eval_tf = build_transforms(model)

    hints: dict[str, list[str]] = {}
    for name in names:
        try:
            image = Image.open(photos_dir / name).convert("RGB")
        except Exception as exc:  # unreadable/corrupt file shouldn't abort the run
            hints[name] = [f"<could not read: {exc}>"]
            continue
        with torch.no_grad():
            logits = model(eval_tf(image).unsqueeze(0))
        top3 = logits.topk(3, dim=1).indices[0].tolist()
        hints[name] = [classes[i] for i in top3]
    return hints


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--photos-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--hint", action="store_true",
                        help="record the model's top-3 guesses as a labelling aid "
                             "(never read by the eval)")
    parser.add_argument("--checkpoint", default="./checkpoints/best.pt")
    args = parser.parse_args()

    photos_dir = Path(args.photos_dir).expanduser()
    out_path = Path(args.out).expanduser()

    names = find_images(photos_dir)
    existing = load_existing(out_path)
    new_names = [n for n in names if n not in existing]

    hints = {}
    if args.hint and new_names:
        hints = build_hints(photos_dir, new_names, Path(args.checkpoint))

    entries = [existing[n] for n in names if n in existing]
    for name in new_names:
        entry = {
            "filename": name,
            "ground_truth": "",
            "food101_label": None,
            "notes": "",
        }
        if name in hints:
            entry["model_hint"] = hints[name]
        entries.append(entry)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(entries, indent=2) + "\n")

    labelled = sum(1 for e in entries if str(e.get("ground_truth", "")).strip())
    print(f"{len(names)} image(s) in {photos_dir}")
    print(f"  {len(existing)} already in the manifest ({labelled} with a ground_truth "
          f"filled in), {len(new_names)} newly added")
    print(f"written to {out_path}")
    if new_names:
        print("\nNext: fill in `ground_truth` for each new entry (what the food")
        print("actually is, in plain words). Set `food101_label` to the exact")
        print("Food-101 class name only when the food really is one of the 101")
        print("trained classes — leave it null otherwise. Out-of-vocabulary")
        print("photos are wanted, not a problem: they're where failure shows.")


if __name__ == "__main__":
    main()
