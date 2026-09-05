"""Produce the benchmark numbers that back the README's accuracy claims.

Two comparisons, not just one accuracy number:
  1. The fine-tuned checkpoint's top-1/top-3 on Food-101's test split.
  2. A pretrained-backbone baseline, to make "fine-tuning helped" a measured
     claim instead of an assumed one.

## Why the baseline is a linear probe, not a bare untrained-head eval

A pretrained ImageNet backbone has a 1000-class ImageNet head, not a
101-class Food-101 head, so "Food-101 accuracy" isn't directly computable
for it without deciding what plays the role of the head first. This module
used to attach a fresh 101-class head with its default random init and
evaluate immediately with zero training -- that measures chance (~1%,
1/101) and makes "85.78% vs ~1%" a technically-true but content-free
comparison, since it never gives the pretrained features a fair chance to
be used for Food-101 classification at all.

What's actually measured now is a **linear probe**: freeze the pretrained
backbone (requires_grad=False on every non-classifier parameter, whole
model kept in eval() mode throughout so BatchNorm running stats aren't
perturbed either), train only a fresh 101-class linear head on the train
split, then evaluate on the test split. This is the standard
transfer-learning baseline -- it measures how good the frozen ImageNet
features already are at separating Food-101 classes, so the gap to the
full fine-tune's accuracy reflects what unfreezing and updating the
backbone weights actually bought, not just "a classifier exists vs. one
doesn't." (A third option -- mapping ImageNet's 1000 classes onto
Food-101's 101 labels -- was also considered and rejected as ill-defined:
most Food-101 dishes, e.g. "beef_carpaccio" or "chicken_curry", have no
ImageNet equivalent to map to.) See benchmarks/classifier/METHODOLOGY.md
and model-training/kaggle/baseline/baseline_kaggle.py (the version of this
logic that actually ran, on Kaggle's GPU, since Food-101 doesn't fit this
machine's local dev setup) for the full writeup.

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


def freeze_backbone(model):
    """Freeze every parameter except the classifier head, for a linear
    probe. `model.get_classifier()` is timm's stable accessor for the head
    module across architectures, rather than hardcoding an attribute name
    like `model.classifier`."""
    head = model.get_classifier()
    head_param_ids = {id(p) for p in head.parameters()}
    for p in model.parameters():
        p.requires_grad = id(p) in head_param_ids
    return head


def train_linear_probe(model, train_loader, device, epochs, lr):
    head = freeze_backbone(model)
    optimizer = torch.optim.AdamW(head.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    criterion = torch.nn.CrossEntropyLoss(label_smoothing=0.1)

    for epoch in range(epochs):
        # eval() mode for the whole model: dropout off, BatchNorm uses its
        # pretrained running stats instead of adapting to Food-101 batches.
        # This only changes those layers' forward behavior -- autograd
        # still flows into the (unfrozen) head's parameters normally.
        model.eval()
        for images, labels in train_loader:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()
        scheduler.step()
    return model


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

    train_set, test_set = load_datasets(Path(args.data_root), fine_tuned, download=False)
    train_loader = DataLoader(train_set, batch_size=64, shuffle=True, num_workers=4)
    test_loader = DataLoader(test_set, batch_size=64, shuffle=False, num_workers=4)

    results = {"n_test_images": len(test_set), "n_classes": len(classes)}

    t0 = time.time()
    results["fine_tuned"] = dict(zip(("top1", "top3"), evaluate(fine_tuned, test_loader, device)))
    results["fine_tuned"]["eval_seconds"] = time.time() - t0

    t0 = time.time()
    train_linear_probe(baseline, train_loader, device, args.probe_epochs, args.probe_lr)
    train_seconds = time.time() - t0

    t0 = time.time()
    results["imagenet_linear_probe_baseline"] = dict(
        zip(("top1", "top3"), evaluate(baseline, test_loader, device))
    )
    results["imagenet_linear_probe_baseline"]["probe_train_seconds"] = train_seconds
    results["imagenet_linear_probe_baseline"]["eval_seconds"] = time.time() - t0
    results["imagenet_linear_probe_baseline"]["probe_epochs"] = args.probe_epochs
    results["imagenet_linear_probe_baseline"]["method"] = (
        "ImageNet-pretrained efficientnet_lite0 backbone frozen (eval() mode, "
        "no gradient/no BatchNorm update); fresh 101-class linear head trained "
        f"for {args.probe_epochs} epochs on the Food-101 train split; evaluated "
        "on the official test split."
    )

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
    parser.add_argument("--probe-epochs", type=int, default=10)
    parser.add_argument("--probe-lr", type=float, default=1e-3)
    run(parser.parse_args())
