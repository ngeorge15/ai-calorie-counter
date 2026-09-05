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
2. **The same metric for the pretrained-but-not-fine-tuned backbone**, as a
   baseline — makes "fine-tuning helped, by this much" a measured claim.
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
