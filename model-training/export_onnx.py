"""Export the fine-tuned checkpoint to ONNX for serving on Render's free
tier, where importing PyTorch alone would eat most of the ~512MB RAM
budget. onnxruntime is a much lighter dependency for inference-only use.

Two artifacts come out of this:
  - checkpoints/model.onnx: the exported graph (dynamic batch dimension).
  - checkpoints/preprocessing.json: everything the serving code needs to
    reproduce inference exactly -- input size, normalization, resize/crop
    behavior, channel order, and the ordered class list. Derived from
    timm's resolved data config (the same source data.py's training/eval
    transforms use), not hand-typed, so serving can't drift from what the
    checkpoint was actually trained on.

The ONNX graph only covers the model forward pass (normalized tensor in,
logits out) -- resize/crop/normalize stay outside the graph, on the
serving side, driven by preprocessing.json. That keeps the graph a plain
image classifier and keeps the exact resize/crop arithmetic in one place
(here, mirrored from data.py's build_transforms) instead of duplicated
inside two different runtimes.

Also runs the numerical-fidelity check described in the module docstring
below `verify_onnx_matches_pytorch`: the failure mode this guards against
is an export that silently changes preprocessing or output semantics,
which degrades accuracy with no error anywhere.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch

from data import build_model, build_transforms


def load_checkpoint(checkpoint_path: Path):
    # weights_only=False: this checkpoint is a dict with a plain Python
    # list (classes) alongside the tensors, not just a state_dict, so the
    # strict-unpickling default doesn't apply here. Trusted, locally
    # produced by train.py in this same repo.
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    classes = checkpoint["classes"]
    model = build_model(num_classes=len(classes), pretrained=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    return model, checkpoint


def build_preprocessing_metadata(model, classes: list[str]) -> dict:
    """Capture the exact preprocessing pipeline the model was
    trained/evaluated with, read from timm's resolved config and the
    concrete eval transform it builds -- not re-derived by hand, so this
    can't drift from what data.py actually does."""
    _, eval_tf = build_transforms(model)
    resize_tf, crop_tf = eval_tf.transforms[0], eval_tf.transforms[1]

    config = __import__("timm").data.resolve_data_config({}, model=model)

    return {
        "input_size": list(config["input_size"]),  # [channels, height, width]
        "channel_order": "RGB",
        "resize": {
            "size": resize_tf.size,  # int -> shorter edge resized to this, aspect preserved
            "interpolation": config["interpolation"],
            "antialias": bool(getattr(resize_tf, "antialias", True)),
        },
        "center_crop_size": list(crop_tf.size),  # [height, width]
        "crop_pct": config["crop_pct"],
        "crop_mode": config["crop_mode"],
        "mean": list(config["mean"]),
        "std": list(config["std"]),
        "pixel_range_before_normalize": [0.0, 1.0],
        "classes": classes,  # index -> Food-101 label, order matches model output logits
    }


def export_to_onnx(model, input_size, out_path: Path, opset: int):
    channels, height, width = input_size
    dummy_input = torch.randn(1, channels, height, width)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        model,
        dummy_input,
        str(out_path),
        input_names=["input"],
        output_names=["logits"],
        dynamic_axes={
            "input": {0: "batch"},
            "logits": {0: "batch"},
        },
        opset_version=opset,
        do_constant_folding=True,
    )


@torch.no_grad()
def verify_onnx_matches_pytorch(model, onnx_path: Path, input_size, tolerance: float = 1e-4):
    """Run identical inputs through both the PyTorch model and the
    exported ONNX graph and compare logits directly. This is the check
    that catches a silently-wrong export -- a preprocessing mismatch or
    an operator that got approximated differently during export would
    show up here as a large max-abs-diff, not as an ONNX export error."""
    channels, height, width = input_size
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])

    torch.manual_seed(0)
    test_cases = {
        "random_batch1": torch.randn(1, channels, height, width),
        "random_batch4": torch.randn(4, channels, height, width),
        "zeros_batch1": torch.zeros(1, channels, height, width),
        "ones_batch1": torch.ones(1, channels, height, width),
    }

    max_abs_diff = 0.0
    per_case = {}
    for name, inputs in test_cases.items():
        torch_out = model(inputs).numpy()
        onnx_out = session.run(["logits"], {"input": inputs.numpy().astype(np.float32)})[0]
        diff = float(np.max(np.abs(torch_out - onnx_out)))
        per_case[name] = diff
        max_abs_diff = max(max_abs_diff, diff)

    for name, diff in per_case.items():
        print(f"  {name}: max abs diff = {diff:.3e}")

    assert max_abs_diff < tolerance, (
        f"ONNX output diverges from PyTorch by {max_abs_diff:.3e}, "
        f"exceeding tolerance {tolerance:.3e}"
    )
    return max_abs_diff


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="checkpoints/best.pt")
    parser.add_argument("--onnx-out", default="checkpoints/model.onnx")
    parser.add_argument("--preprocessing-out", default="checkpoints/preprocessing.json")
    parser.add_argument("--opset", type=int, default=17)
    parser.add_argument("--tolerance", type=float, default=1e-4)
    args = parser.parse_args()

    checkpoint_path = Path(args.checkpoint)
    onnx_path = Path(args.onnx_out)
    preprocessing_path = Path(args.preprocessing_out)

    print(f"loading checkpoint from {checkpoint_path}")
    model, checkpoint = load_checkpoint(checkpoint_path)
    classes = checkpoint["classes"]
    print(f"model: {len(classes)} classes, "
          f"checkpoint top1={checkpoint.get('top1')}, top3={checkpoint.get('top3')}")

    metadata = build_preprocessing_metadata(model, classes)
    input_size = metadata["input_size"]

    print(f"exporting to {onnx_path} (opset {args.opset}, dynamic batch dim)")
    export_to_onnx(model, input_size, onnx_path, args.opset)

    onnx_size_bytes = onnx_path.stat().st_size
    print(f"ONNX file size: {onnx_size_bytes / (1024 * 1024):.2f} MB")

    print("verifying ONNX output matches PyTorch output")
    max_abs_diff = verify_onnx_matches_pytorch(model, onnx_path, input_size, args.tolerance)
    print(f"max abs diff across all cases: {max_abs_diff:.3e} (tolerance {args.tolerance:.3e})")

    preprocessing_path.parent.mkdir(parents=True, exist_ok=True)
    preprocessing_path.write_text(json.dumps(metadata, indent=2))
    print(f"preprocessing metadata written to {preprocessing_path}")


if __name__ == "__main__":
    main()
