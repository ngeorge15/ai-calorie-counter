# Roadmap

This is the phase plan referenced throughout commit messages and
[README.md](README.md#roadmap), written down in one place instead of living
only in commit history. It's derived strictly from what's in the repo —
README.md, commit messages, `benchmarks/classifier/`, `mobile/NOTES.md`,
`model-training/NOTES.md`, and open GitHub issues. Where a commit references
a phase that isn't otherwise defined, that's called out explicitly rather
than papered over.

No dates or time estimates appear here. Nobody has committed to a schedule,
and this is a single-person project worked on when time allows.

## Constraints that shape the plan

These aren't incidental — they explain several sequencing and architecture
decisions below.

- **Strictly free-tier stack**: Render's free web service tier, MongoDB
  Atlas M0 (free forever, 512MB), a free USDA FoodData Central API key, and
  Kaggle's free-tier GPU for model training. No paid infrastructure anywhere
  in the loop.
- **iOS-only via SideStore**: the mobile app is installed without a paid
  Apple developer account, which is part of why Expo (managed workflow) was
  chosen. Android is unverified throughout — VisionCamera v5 exposes no
  equivalent of v4's `enableCodeScanner` gradle flag, and `ScannedObject` in
  `mobile/NOTES.md` is annotated iOS-only.
- **8GB unified-memory dev machine**: per `model-training/NOTES.md`, the
  local M2 Mac is dev-and-smoke-test-only. `data.py` and `train.py` are
  written and tested locally against dummy tensors and a single forward
  pass; the real fine-tuning run happens on a free-tier cloud GPU (Kaggle or
  Colab, both giving a T4 with 16GB dedicated VRAM) because a real training
  run risks OOM on the dev machine and would tie it up for hours regardless.

## Phases

### Phase 0 — auth, offline-first sync, barcode lookup chain — **done**

Backend (`1243cb8`..`eeb4ec0`) and mobile (`eaa95a9`..`1793a2e`): JWT auth,
offline-first meal sync with server-authoritative cursors and tombstoned
deletes, the USDA → Open Food Facts → cache barcode lookup chain, and the
on-device SQLite log via Drizzle. "Done" means what the README states as
current status: scan → look up → log → sync works end to end, offline-first,
verified on a real device.

Two subtleties from the commit messages worth preserving here since they're
easy to regress:
- Sync cursors come from the server clock, never the client's — a
  fast-clocked phone would otherwise push a future-stamped meal, adopt it as
  its own cursor, and permanently miss server changes written in the gap
  behind it (further floored to millisecond precision because BSON
  truncates microseconds).
- USDA has no barcode endpoint; the UPC goes in as a search query and every
  fuzzy result is re-verified against `gtinUpc` across UPC-A/EAN-13
  zero-padding before it's trusted.

### Phase 0.5 — recent foods, favorites, one-tap re-log — **planned**

Listed in README's roadmap, not yet built. README's engineering-decisions
section gives the explicit reasoning for why this is sequenced where it is,
ahead of the classifier's inference endpoint: portion-size estimation error
dominates total calorie error more than food classification does, but the
recent/favorites/re-log loop is what makes the app usable daily while the
classifier gets built. In other words, this phase exists to keep the app
useful in the gap between "classifier trained" (Phase 1a) and "classifier
serving" (Phase 1b).

### Phase 1a — fine-tune `efficientnet_lite0` on Food-101 — **done**

Commit `3892651`. Fine-tuned for 15 epochs on Kaggle's free-tier GPU.
Measured result, from `benchmarks/classifier/results.json`:

- **85.78% top-1 / 95.05% top-3** on Food-101's held-out (manually verified)
  test split
- **13.6MB** model size
- **~374.7s/epoch** average training time

`efficientnet_lite0` was chosen specifically because it's designed for
mobile/edge deployment (`model-training/NOTES.md`) — Phase 1 runs inference
server-side, but keeping the backbone edge-capable now means the on-device
CoreML stretch goal (below) won't require re-choosing an architecture later,
just re-exporting the same one.

Real problems hit and fixed during this phase (full detail in the commit
message and `model-training/NOTES.md`):
- An unverified Kaggle account silently strips GPU/internet access rather
  than rejecting the kernel push.
- Writing the dataset into `/kaggle/working` (the output-synced directory)
  turns a log fetch into a multi-GB download; moved to `/kaggle/temp`.
- Kaggle's free-tier GPU pool assigned a Tesla P100 (compute capability
  6.0), incompatible with the default image's PyTorch build (sm_70+ only);
  fixed with a cu118-era torch/torchvision build plus `numpy<2` pinning.

No other accuracy or performance number beyond the three above is
established anywhere in this repo — see
[`benchmarks/classifier/results.json`](benchmarks/classifier/results.json)
for what's measured vs. still pending.

### Phase 1b — server-side inference endpoint — **planned**

Listed in README's roadmap: a Flask endpoint serving the Phase 1a
checkpoint, seeded into a USDA search on the classifier's top-3 predictions.
Not yet built as of this writing.

**Why server-side, not on-device, despite an edge-capable backbone**: this
is the architecture decision `model-training/NOTES.md` points back to —
inference runs server-side for Phase 1, with on-device CoreML deferred to a
stretch goal. The tradeoff this defers is measured, not assumed: per
`benchmarks/classifier/METHODOLOGY.md`, server latency (cold vs. warm Render
instance, plus full phone round-trip) is tracked specifically as "the direct
check on the 'cold-start risk is manageable' call made when choosing
server-side over on-device inference." That check hasn't been run yet —
`server_inference_latency` is listed under `not_yet_measured` in
`results.json`, pending the endpoint this phase builds.

### Benchmarks — real-photo accuracy, baseline comparison, latency — **in progress**

README lists this as its own roadmap line, and `benchmarks/classifier/`
defines the plan in detail. Per `METHODOLOGY.md` and `results.json`:

| Measurement | Status |
|---|---|
| Food-101 test-set accuracy (fine-tuned) | done — 85.78% top-1 / 95.05% top-3 |
| Same metric on pretrained-but-not-fine-tuned backbone (baseline) | pending |
| Real-photo end-to-end accuracy (30-50 real phone photos through the full classify → USDA-search pipeline) | pending — script not yet written |
| Server-side inference latency (cold/warm) and full phone round-trip | pending — needs the Phase 1b endpoint deployed first |
| Model size / param count for on-device comparison | recorded (13.6MB), to be revisited once an on-device port is attempted |

The methodology doc is explicit about why this exists as written-down
process rather than after-the-fact narrative: "this plan was written before
any numbers existed, so it can't be quietly bent to fit whatever came out."
The same document commits that no accuracy, latency, or comparison claim
goes in the top-level README until the corresponding entry exists in
`results.json`.

### A note on the phase numbering

The numbering here is not a clean sequence: it runs Phase 0, 0.5, 1a, 1b,
then an unnumbered "Benchmarks" line, with no Phase 2, 3, or 4 defined
anywhere. An earlier draft of this project's history referred to a "Phase 4
latency benchmark" in the context of the MMKV product cache instrumentation;
that work is now tracked as the latency row in the Benchmarks table above
and in `benchmarks/classifier/METHODOLOGY.md` §4.

This is recorded rather than retroactively tidied, because renumbering
phases after the fact would misrepresent how the project was actually
sequenced. If a fuller numbering is wanted going forward, it should be
defined here first rather than inferred from commit messages.

## Known gaps

- **Auth rate limiting** ([#1](../../issues/1)): `net.py`'s outbound rate
  limiting (USDA/OFF) has a pyrate-limiter pattern already in place, but
  nothing currently guards the inbound `/api/auth/login` and
  `/api/auth/register` routes — a live deployment is brute-forceable as-is.
  Tracked as an open issue, not yet scheduled into a phase above.
- **Android**: unverified throughout Phase 0 and Phase 1. VisionCamera v5
  ships no equivalent of v4's `enableCodeScanner` gradle flag, so how MLKit
  gets pulled in in v5 has not been confirmed (`mobile/NOTES.md`).

## Stretch goals (after Phase 1 ships)

Named in [README.md](README.md#stretch-goals-after-phase-1-ships), not
scoped or sequenced beyond being explicitly deferred until after Phase 1:

- **On-device inference via Core ML** — the `efficientnet_lite0` backbone
  was chosen in Phase 1a specifically to make this a re-export rather than a
  re-architecture.
- **Multi-item plate detection** via segment-then-classify, reusing the
  Phase 1 classifier per detected region.
- **A zero-shot multimodal-LLM baseline**, benchmarked against the trained
  classifier — would extend the comparison work already planned in
  `benchmarks/classifier/METHODOLOGY.md`.
