"""Kaggle-kernel entry point for the Food-101 "pretrained baseline" measurement.

## Why this is a linear probe, not a bare pretrained-backbone eval

METHODOLOGY.md commits to measuring "the same metric [Food-101 top-1/top-3]
for the pretrained-but-not-fine-tuned backbone, as a baseline." That's
underspecified: a pretrained ImageNet backbone has a 1000-class ImageNet
head, not a 101-class Food-101 head, so "accuracy on Food-101" isn't
directly computable without deciding what plays the role of the head.
Three options, and why this script implements the first:

  (a) LINEAR PROBE (what this script does): freeze the pretrained backbone,
      train only a fresh 101-class linear head on Food-101's train split,
      evaluate on the test split. This is the standard transfer-learning
      baseline in the literature -- it measures how good the *frozen
      ImageNet features* already are at separating Food-101 classes, before
      spending any compute updating the backbone itself. Comparing this
      number to the full fine-tune's 85.78%/95.05% answers a meaningful
      question: "how much did unfreezing and updating the backbone weights
      buy us, beyond what the pretrained features already gave for free?"

  (b) RANDOM/UNTRAINED HEAD, frozen backbone, no training at all: attach a
      fresh 101-class head with its default random init and evaluate
      immediately. This is degenerate -- it just measures chance (~1%,
      1/101) and produces a technically-true but content-free comparison
      ("85.78% vs ~1%"). It doesn't isolate what fine-tuning contributed,
      because it never gives the pretrained features a fair chance to be
      used for Food-101 classification at all. Rejected. (Note:
      model-training/eval.py's current `imagenet_baseline_no_finetune`
      does exactly this and is being corrected alongside this script.)

  (c) MAP ImageNet's 1000 classes onto Food-101's 101 labels (e.g. "pizza",
      "hotdog" have rough ImageNet equivalents) and score those: ill-defined
      for most Food-101 classes (there's no ImageNet synset for
      "beef_carpaccio" or "chicken_curry"), and the mapping choices would
      themselves need justifying. Rejected as messy and not standardizable.

So: linear probe. Backbone stays frozen (requires_grad=False on every
non-classifier parameter, and the whole model is kept in eval() mode
throughout -- including during the head's training steps -- so BatchNorm
running stats also aren't perturbed by Food-101 batches; eval() does not
disable autograd, so the head still trains normally). Only the classifier
head is optimized.

## Kaggle environment notes (same fixes as train_kaggle.py, reused verbatim)

Kaggle script kernels execute a single file with no access to sibling local
files, so this duplicates data.py's model/transform logic rather than
importing it. Kaggle's default image ships a PyTorch build compiled only for
sm_70+ (Volta+); this account's free-GPU pool keeps assigning a Tesla P100
(sm_60, Pascal), which throws "no kernel image is available for execution on
the device" against that build. Reinstalling a cu118-era wheel before
importing torch fixes it (that generation targets Pascal *and* everything
newer). torch 2.2.0 predates NumPy 2.0's ABI, so numpy is pinned <2 too.
"""
import subprocess
import sys

subprocess.check_call([
    sys.executable, "-m", "pip", "install", "--quiet",
    "torch==2.2.0+cu118", "torchvision==0.17.0+cu118",
    "--index-url", "https://download.pytorch.org/whl/cu118",
])
subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "numpy<2"])

import json
import time
from pathlib import Path

import timm
import torch
from torch.utils.data import DataLoader
from torchvision.datasets import Food101

WORKING = Path("/kaggle/working")
EPOCHS = 10  # only the linear head trains; converges much faster than full fine-tuning
BATCH_SIZE = 64
LR = 1e-3


def build_model(num_classes: int = 101, pretrained: bool = True):
    return timm.create_model("efficientnet_lite0", pretrained=pretrained, num_classes=num_classes)


def build_transforms(model):
    config = timm.data.resolve_data_config({}, model=model)
    return (timm.data.create_transform(**config, is_training=True),
            timm.data.create_transform(**config, is_training=False))


def freeze_backbone(model):
    """Freeze every parameter except the classifier head. timm's
    efficientnet_lite0 exposes the head as `model.classifier` (a Linear
    layer); `model.get_classifier()` confirms this is the same module
    across timm versions rather than hardcoding the attribute name."""
    head = model.get_classifier()
    head_params = set(id(p) for p in head.parameters())
    trainable, frozen = 0, 0
    for p in model.parameters():
        if id(p) in head_params:
            p.requires_grad = True
            trainable += p.numel()
        else:
            p.requires_grad = False
            frozen += p.numel()
    print(f"frozen params: {frozen:,}  trainable (head) params: {trainable:,}", flush=True)
    return head


@torch.no_grad()
def evaluate(model, loader, device):
    model.eval()
    correct1 = correct3 = total = 0
    for images, labels in loader:
        images, labels = images.to(device), labels.to(device)
        logits = model(images)
        top3_preds = logits.topk(3, dim=1).indices
        correct1 += (top3_preds[:, 0] == labels).sum().item()
        correct3 += (top3_preds == labels.unsqueeze(1)).any(dim=1).sum().item()
        total += labels.size(0)
    return correct1 / total, correct3 / total


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device: {device}", flush=True)

    model = build_model(num_classes=101, pretrained=True).to(device)
    head = freeze_backbone(model)
    train_tf, eval_tf = build_transforms(model)

    # /kaggle/temp, not /kaggle/working: the dataset must not land in the
    # output directory, which Kaggle syncs back in full on every fetch.
    data_root = "/kaggle/temp/data"
    train_set = Food101(root=data_root, split="train", transform=train_tf, download=True)
    test_set = Food101(root=data_root, split="test", transform=eval_tf, download=True)

    train_loader = DataLoader(train_set, batch_size=BATCH_SIZE, shuffle=True,
                               num_workers=2, pin_memory=True)
    test_loader = DataLoader(test_set, batch_size=BATCH_SIZE, shuffle=False,
                              num_workers=2, pin_memory=True)

    # Pretrained-and-untrained sanity check: eval the frozen backbone with
    # its freshly-initialized (untrained) head before any training, to show
    # explicitly that this run does NOT start from the degenerate
    # interpretation-(b) baseline described in the module docstring.
    untrained_top1, untrained_top3 = evaluate(model, test_loader, device)
    print(f"untrained head (epoch 0, sanity check): "
          f"top1={untrained_top1:.4f}  top3={untrained_top3:.4f}", flush=True)

    optimizer = torch.optim.AdamW(head.parameters(), lr=LR, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
    criterion = torch.nn.CrossEntropyLoss(label_smoothing=0.1)

    best_top1 = 0.0
    history = [{"epoch": 0, "train_loss": None, "top1": untrained_top1, "top3": untrained_top3, "seconds": 0}]

    for epoch in range(EPOCHS):
        # Whole model stays in eval() mode: dropout off, BatchNorm uses its
        # pretrained running stats rather than adapting to Food-101 batches.
        # eval() only changes those layers' forward behavior -- it does not
        # disable autograd, so the head's parameters still accumulate
        # gradients and update normally.
        model.eval()
        t0 = time.time()
        running_loss = 0.0
        for images, labels in train_loader:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()
            running_loss += loss.item() * images.size(0)
        scheduler.step()

        train_loss = running_loss / len(train_set)
        top1, top3 = evaluate(model, test_loader, device)
        elapsed = time.time() - t0
        print(f"epoch {epoch+1}/{EPOCHS}  loss={train_loss:.4f}  "
              f"top1={top1:.4f}  top3={top3:.4f}  ({elapsed:.0f}s)", flush=True)
        history.append({"epoch": epoch + 1, "train_loss": train_loss,
                         "top1": top1, "top3": top3, "seconds": elapsed})

        if top1 > best_top1:
            best_top1 = top1
            torch.save({
                "model_state_dict": model.state_dict(),
                "classes": train_set.classes,
                "top1": top1,
                "top3": top3,
                "method": "linear_probe_frozen_backbone",
            }, WORKING / "linear_probe_best.pt")

    (WORKING / "history.json").write_text(json.dumps(history, indent=2))
    print(f"best linear-probe top1={best_top1:.4f}", flush=True)


if __name__ == "__main__":
    main()
