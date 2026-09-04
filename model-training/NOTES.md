# Training notes

## Local machine is dev-only, not where the real training run happens

This was developed on an M2 Mac with 8GB unified memory. That's shared
between the OS, the model, optimizer state, and activations during
training — tight enough that a real training run risks OOM mid-epoch,
especially with a batch size large enough for stable gradients.

`data.py` and `train.py` are written and smoke-tested locally (`python
data.py`, `pytest`) against dummy tensors and a single forward pass — no
full Food-101 download or real training happens on this machine. The actual
fine-tuning run happens on a free-tier cloud GPU (Colab or Kaggle, both give
a T4 with 16GB dedicated VRAM — double this machine's *total* memory, and
neither ties up the laptop for however many hours training takes).

## Why efficientnet_lite0

Chosen specifically because it's designed for mobile/edge deployment. Phase
1 runs inference server-side (see the architecture decision in the main
README), but keeping the backbone edge-capable now means the on-device
CoreML stretch goal doesn't require re-choosing an architecture later —
just re-exporting the same one.

## timm resolves the input transform, not a hardcoded ImageNet mean/std

`timm.data.resolve_data_config` + `create_transform` reads the exact
input size and normalization the chosen backbone's pretrained weights
expect. Hand-typing `[0.485, 0.456, 0.406]` and hoping it matches the
checkpoint is how you silently degrade accuracy without an error anywhere.
