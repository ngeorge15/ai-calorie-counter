"""Kaggle-kernel entry point for the Food-101 fine-tune.

Kaggle script kernels execute a single file with no access to sibling
local files, so this deliberately duplicates data.py/train.py's logic
rather than importing them — those two files stay the source of truth for
local dev/tests; this is what actually runs on Kaggle's GPU. Uses
torchvision's own Food-101 download (not a pre-attached Kaggle dataset)
so the split is the canonical, benchmark-comparable one, with GPU +
internet enabled in kernel-metadata.json.

Kaggle's default image ships a PyTorch build compiled only for sm_70+
(Volta and newer). This account's free-GPU pool keeps assigning a Tesla
P100 (sm_60, Pascal) -> "no kernel image is available for execution on
the device". Reinstalling a cu118-era build before importing torch fixes
it: that generation of wheel still targets Pascal *and* everything newer,
so it works regardless of which GPU this run happens to get.
"""
import subprocess
import sys

subprocess.check_call([
    sys.executable, "-m", "pip", "install", "--quiet",
    "torch==2.2.0+cu118", "torchvision==0.17.0+cu118",
    "--index-url", "https://download.pytorch.org/whl/cu118",
])
# torch 2.2.0 predates NumPy 2.0 and isn't ABI-compatible with it; Kaggle's
# default image ships NumPy 2.x, which breaks under the downgraded torch.
subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "numpy<2"])

import json
import time
from pathlib import Path

import timm
import torch
from torch.utils.data import DataLoader
from torchvision.datasets import Food101

WORKING = Path("/kaggle/working")
EPOCHS = 15
BATCH_SIZE = 64
LR = 3e-4


def build_model(num_classes: int = 101, pretrained: bool = True):
    return timm.create_model("efficientnet_lite0", pretrained=pretrained, num_classes=num_classes)


def build_transforms(model):
    config = timm.data.resolve_data_config({}, model=model)
    return (timm.data.create_transform(**config, is_training=True),
            timm.data.create_transform(**config, is_training=False))


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
    train_tf, eval_tf = build_transforms(model)

    # /kaggle/temp, not /kaggle/working: the dataset must not land in the
    # output directory, which Kaggle syncs back in full on every fetch —
    # that turned "download the log" into "download the whole dataset"
    # and is why pulling this kernel's output kept timing out.
    data_root = "/kaggle/temp/data"
    train_set = Food101(root=data_root, split="train", transform=train_tf, download=True)
    test_set = Food101(root=data_root, split="test", transform=eval_tf, download=True)

    train_loader = DataLoader(train_set, batch_size=BATCH_SIZE, shuffle=True,
                               num_workers=2, pin_memory=True)
    test_loader = DataLoader(test_set, batch_size=BATCH_SIZE, shuffle=False,
                              num_workers=2, pin_memory=True)

    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
    criterion = torch.nn.CrossEntropyLoss(label_smoothing=0.1)

    best_top1 = 0.0
    history = []

    for epoch in range(EPOCHS):
        model.train()
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
            }, WORKING / "best.pt")

    (WORKING / "history.json").write_text(json.dumps(history, indent=2))
    print(f"best top1={best_top1:.4f}", flush=True)


if __name__ == "__main__":
    main()
