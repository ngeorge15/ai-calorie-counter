"""Food-101 loading and the label -> USDA search-string mapping.

Food-101's class names (e.g. "chicken_curry") are already shaped like search
queries; the only transform needed is underscores -> spaces. Kept as a
function, not a static dict, because it's what both training (to save the
class list next to a checkpoint) and the backend (to build a USDA query from
a prediction) need to agree on.
"""
from pathlib import Path

import timm
import torch
from torchvision.datasets import Food101


def label_to_query(label: str) -> str:
    return label.replace("_", " ")


def build_transforms(model):
    """Resolve the exact input size/normalization the pretrained backbone
    expects, rather than hand-picking ImageNet mean/std and risking a
    mismatch with what the checkpoint was actually trained on."""
    config = timm.data.resolve_data_config({}, model=model)
    train_tf = timm.data.create_transform(**config, is_training=True)
    eval_tf = timm.data.create_transform(**config, is_training=False)
    return train_tf, eval_tf


def load_datasets(data_root: Path, model, download: bool = True):
    train_tf, eval_tf = build_transforms(model)
    train_set = Food101(root=str(data_root), split="train", transform=train_tf, download=download)
    test_set = Food101(root=str(data_root), split="test", transform=eval_tf, download=download)
    return train_set, test_set


def build_model(num_classes: int = 101, pretrained: bool = True):
    # efficientnet_lite0: light enough for a later CoreML/on-device stretch
    # goal without changing architectures, strong enough pretrained on
    # ImageNet to be worth fine-tuning rather than training from scratch.
    return timm.create_model("efficientnet_lite0", pretrained=pretrained, num_classes=num_classes)


if __name__ == "__main__":
    # Smoke test: does everything import and wire together correctly,
    # without downloading the real ~5GB dataset or training anything.
    model = build_model()
    train_tf, eval_tf = build_transforms(model)
    dummy = torch.zeros(1, 3, 224, 224)
    out = model(dummy)
    assert out.shape == (1, 101), out.shape
    print("OK: model builds, forward pass produces (1, 101) logits")
    print("label_to_query('chicken_curry') ->", label_to_query("chicken_curry"))
