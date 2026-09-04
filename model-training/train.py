"""Fine-tune efficientnet_lite0 on Food-101.

Meant to run on a free-tier cloud GPU (Colab/Kaggle T4) — see NOTES.md for
why this doesn't run on the 8GB M2 this was developed on. Run locally only
for `python data.py`-style smoke tests on the wiring, not for the real job.
"""
import argparse
import json
import time
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from data import build_model, load_datasets


def train(args):
    device = torch.device(
        "cuda" if torch.cuda.is_available()
        else "mps" if torch.backends.mps.is_available()
        else "cpu"
    )
    print(f"device: {device}")

    model = build_model(num_classes=101, pretrained=True).to(device)
    train_set, test_set = load_datasets(Path(args.data_root), model, download=True)

    train_loader = DataLoader(train_set, batch_size=args.batch_size, shuffle=True,
                               num_workers=args.num_workers, pin_memory=True)
    test_loader = DataLoader(test_set, batch_size=args.batch_size, shuffle=False,
                              num_workers=args.num_workers, pin_memory=True)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    criterion = torch.nn.CrossEntropyLoss(label_smoothing=0.1)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    best_top1 = 0.0
    history = []

    for epoch in range(args.epochs):
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
        print(f"epoch {epoch+1}/{args.epochs}  loss={train_loss:.4f}  "
              f"top1={top1:.4f}  top3={top3:.4f}  ({elapsed:.0f}s)")
        history.append({"epoch": epoch + 1, "train_loss": train_loss,
                         "top1": top1, "top3": top3, "seconds": elapsed})

        if top1 > best_top1:
            best_top1 = top1
            torch.save({
                "model_state_dict": model.state_dict(),
                "classes": train_set.classes,
                "top1": top1,
                "top3": top3,
            }, out_dir / "best.pt")

    (out_dir / "history.json").write_text(json.dumps(history, indent=2))
    print(f"best top1={best_top1:.4f}, checkpoint saved to {out_dir / 'best.pt'}")


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="./data")
    parser.add_argument("--out-dir", default="./checkpoints")
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--num-workers", type=int, default=4)
    train(parser.parse_args())
