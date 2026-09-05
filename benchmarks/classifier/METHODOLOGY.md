# Classifier benchmark methodology

Status: **partially measured, see results.json.** Fine-tuned Food-101
test-set accuracy is real (85.78% top-1, 95.05% top-3, 15 epochs). The
baseline comparison, real-photo eval, and latency numbers below are not
measured yet — this plan was written before any numbers existed, so it
can't be quietly bent to fit whatever came out.

## What's measured

1. **Food-101 test-set accuracy** (top-1 and top-3) for the fine-tuned
   checkpoint, via `model-training/eval.py`. Food-101's test split is
   manually verified (unlike its noisier training split), so this number is
   trustworthy as a standard, comparable benchmark.
2. **A pretrained-backbone baseline**, as a linear probe — makes
   "fine-tuning helped, by this much" a measured claim rather than an
   assumed one.

   This needed a decision that the original one-line plan glossed over: a
   pretrained ImageNet backbone has a 1000-class ImageNet head, not a
   101-class Food-101 head, so "Food-101 accuracy" isn't directly
   computable for it without first deciding what stands in for the head.
   Three options were considered:
   - **Linear probe (chosen)**: freeze the pretrained backbone, train only
     a fresh 101-class linear head on the Food-101 train split, evaluate on
     the test split. This is the standard transfer-learning baseline — it
     measures how good the frozen ImageNet *features* already are at
     separating Food-101 classes, isolating what full fine-tuning (which
     also updates the backbone weights) adds on top.
   - **Random/untrained head, frozen backbone, zero training**: attach a
     fresh 101-class head and evaluate immediately. Rejected — this just
     measures chance (~1%, 1/101) and turns the comparison into a
     content-free "85.78% vs ~1%," since the pretrained features are never
     actually put to use for Food-101 classification.
   - **Map ImageNet's 1000 classes onto Food-101's 101 labels**: rejected
     as ill-defined — most Food-101 dishes (e.g. "beef_carpaccio",
     "chicken_curry") have no ImageNet equivalent to map to.

   Implementation: `model-training/kaggle/baseline/baseline_kaggle.py` (run
   on Kaggle's GPU, same environment fixes as the fine-tuning kernel) and
   `model-training/eval.py`'s `train_linear_probe`/`freeze_backbone` (local
   source of truth, mirrors the Kaggle script).
3. **Real-photo end-to-end accuracy**: 30-50 photos taken with an actual
   phone camera (not Food-101 images), run through the full pipeline —
   classifier top-3 -> USDA FoodData Central search -> is the correct food
   in the returned results. This is the number that actually reflects
   whether the feature works, since Food-101 test accuracy only proves the
   model learned Food-101, not that it generalizes to a real kitchen photo.
   Script + photo set added once there's a checkpoint to test.
4. **Latency**: server-side inference time (cold vs. warm Render instance)
   and full phone round-trip. Measured, not assumed, since it's the direct
   check on the "cold-start risk is manageable" call made when choosing
   server-side over on-device inference.
5. **Model size / param count**: recorded for comparison once an on-device
   port is attempted.

## What's explicitly not claimed

No accuracy, latency, or "beats X" comparison goes in the top-level README
until the corresponding entry exists in `results.json` with this
methodology behind it.
