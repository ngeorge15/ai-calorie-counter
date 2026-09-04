"""Produce the benchmark numbers that back the README's accuracy claims.

Two comparisons, not just one accuracy number:
  1. The fine-tuned checkpoint's top-1/top-3 on Food-101's test split.
  2. The same backbone's top-1/top-3 with its pretrained ImageNet head only
     (no fine-tuning) — the baseline that makes "fine-tuning helped" a
     measured claim instead of an assumed one.

Writes results to benchmarks/classifier/results.json. Real-photo end-to-end
eval (predicted top-3 -> actual USDA search -> correct match) is a separate
script, added once there's a trained checkpoint to point a phone camera at.
"""
import argparse
import json
import time
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from data import build_model, load_datasets
from train import evaluate


def run(args):
    device = torch.device(
        "cuda" if torch.cuda.is_available()
        else "mps" if torch.backends.mps.is_available()
        else "cpu"
    )

    checkpoint = torch.load(args.checkpoint, map_location=device)
    classes = checkpoint["classes"]

    fine_tuned = build_model(num_classes=len(classes), pretrained=False).to(device)
    fine_tuned.load_state_dict(checkpoint["model_state_dict"])

    baseline = build_model(num_classes=len(classes), pretrained=True).to(device)

    _, test_set = load_datasets(Path(args.data_root), fine_tuned, download=False)
    test_loader = DataLoader(test_set, batch_size=64, shuffle=False, num_workers=4)

    results = {"n_test_images": len(test_set), "n_classes": len(classes)}

    t0 = time.time()
    results["fine_tuned"] = dict(zip(("top1", "top3"), evaluate(fine_tuned, test_loader, device)))
    results["fine_tuned"]["eval_seconds"] = time.time() - t0

    t0 = time.time()
    results["imagenet_baseline_no_finetune"] = dict(
        zip(("top1", "top3"), evaluate(baseline, test_loader, device))
    )
    results["imagenet_baseline_no_finetune"]["eval_seconds"] = time.time() - t0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    print(f"\nwritten to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="./checkpoints/best.pt")
    parser.add_argument("--data-root", default="./data")
    parser.add_argument("--out", default="../benchmarks/classifier/results.json")
    run(parser.parse_args())
