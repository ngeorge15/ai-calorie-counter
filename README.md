# AI Calorie Counter

An offline-first calorie tracker for iOS, built to eventually classify food
photos into a logged meal instead of requiring a manual search. Barcode
scanning and offline logging are built and working; the AI classifier is the
next phase.

**Status: Phase 0 complete, Phase 1 in progress.** Scan → look up → log →
sync works end to end, offline-first, on a real device. The food classifier
(Phase 1) has a training pipeline but no trained model yet — see
[Roadmap](#roadmap).

## Why this exists

Most calorie trackers either cost money past a trial or hand-wave the "just
take a photo" pitch without a real classifier behind it. This is a from-scratch
build on a strictly free-tier stack (Render free web service, MongoDB Atlas
M0, USDA's free FoodData Central key) to see how far that actually goes, and
to have a real answer — backed by numbers, not a claim — for "how accurate is
the AI part."

## How it works today

1. Scan a barcode → the phone hits a Flask backend, which checks its own
   cache, then USDA FoodData Central, then falls back to Open Food Facts.
2. Nutrition comes back, you can correct it, and it's logged to an on-device
   SQLite database — this works with no network at all.
3. When the phone's back online, an offline-first sync engine reconciles the
   local log against the server: client-minted UUIDs, server-authoritative
   timestamps, tombstoned deletes so an offline delete doesn't silently
   resurrect on the next sync.

## Architecture

```
┌─────────────────────────┐         ┌──────────────────────────────┐
│   iOS app (Expo/RN)      │         │   Flask API (Render, free)     │
│                           │         │                                 │
│  VisionCamera v5  ──────────scan──▶│  /api/products  ──┐             │
│  (barcode → UPC)          │        │                    ▼             │
│                           │        │            Mongo cache miss?     │
│  Drizzle + expo-sqlite   │◀───────│                    │             │
│  (offline meal log)       │  JSON  │        USDA FoodData Central     │
│                           │         │           (primary, 1000/hr)    │
│  Sync engine  ───────────sync─────▶│                    │ miss        │
│  (server-authoritative    │        │                    ▼             │
│   cursor, LWW conflicts)  │        │           Open Food Facts        │
│                           │        │           (fallback, 15/min)     │
│  Keychain (expo-secure-   │        │                                 │
│   store) — JWT             │        │  MongoDB Atlas M0 (free, 512MB) │
└─────────────────────────┘         └──────────────────────────────┘
```

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Mobile | Expo SDK 57 (React Native) + expo-router | File-based routing, managed workflow, SideStore-installable without a paid Apple dev account |
| Local DB | Drizzle ORM over expo-sqlite | Generated, versioned migrations instead of hand-written schema |
| Barcode scan | VisionCamera v5 (Nitro) | Only actively maintained scanning library targeting current RN architecture |
| Cache | MMKV | Fast key-value cache for looked-up products, instrumented for a latency benchmark |
| Backend | Flask + Gunicorn on Render (free tier) | Small surface area, easy to reason about on a single free web worker |
| DB | MongoDB Atlas M0 | Free forever, no card required, enough for a single-user tracker |
| Validation | Pydantic | Structured 422s instead of silently dropping bad input |
| Auth | flask-jwt-extended, Keychain-stored token | Long-lived token — this is a single-user personal tracker, not a multi-tenant product |
| Barcode data | USDA FoodData Central (primary) → Open Food Facts (fallback) → user contribution | FDC has far better US branded-product coverage; OFF fills the gaps |

## Engineering decisions worth knowing about

A few choices here were deliberate deviations from the "obvious" approach,
made for reasons that turned out to matter:

- **Sync cursors come from the server clock, not the client's.** A phone with
  a fast clock would otherwise push a future-stamped meal, adopt that as its
  own cursor, and permanently stop seeing server changes written in the gap
  behind it.
- **USDA has no barcode endpoint.** The UPC goes in as a search query and
  comes back with fuzzy near-matches, so every result is re-verified against
  `gtinUpc` across UPC-A/EAN-13 zero-padding before it's trusted.
- **VisionCamera v5 is a ground-up rewrite** of v4 with an entirely different
  scanning API (`useObjectOutput` instead of `useCodeScanner`) and no Expo
  config plugin — most existing tutorials describe v4 and won't compile
  against it. Full notes in [`mobile/NOTES.md`](mobile/NOTES.md).
- **Gunicorn runs with `--workers 1` on purpose.** The Open Food Facts rate
  limiter is an in-process bucket; a second worker would think it had its own
  full budget and the pair would exceed OFF's real limit together.
- **The food classifier (Phase 1) is scoped after retention features, not
  before them** — portion-size estimation error dominates total calorie
  error more than food classification does, but the recent/favorites/re-log
  loop is what makes the app usable daily while the classifier gets built.

## Running it locally

**Backend**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # fill in MONGODB_URI, JWT_SECRET, USDA_API_KEY, OFF_USER_AGENT
flask --app wsgi run
```

**Mobile**
```bash
cd mobile
npm install
cp .env.example .env   # point EXPO_PUBLIC_API_BASE_URL at the backend above
npx expo start
```

iOS 16.4+ required (Expo SDK 57's floor). Barcode scanning is verified on
iOS; Android is untested — VisionCamera v5 exposes no equivalent of v4's
`enableCodeScanner` gradle flag.

## Roadmap

- [x] **Phase 0** — auth, offline-first sync, barcode lookup chain, scan-to-log loop
- [ ] **Phase 0.5** — recent foods, favorites, one-tap re-log
- [ ] **Phase 1** — food classifier (fine-tuned `efficientnet_lite0` on Food-101, server-side inference), seeded from a USDA search on its top-3 predictions. Training pipeline built ([`model-training/`](model-training)); no trained checkpoint yet.
- [ ] **Benchmarks** — classifier accuracy (Food-101 test set + real-photo end-to-end), latency, and a fine-tuned-vs-baseline comparison. Methodology written up in [`benchmarks/classifier/METHODOLOGY.md`](benchmarks/classifier/METHODOLOGY.md); no results until there's a trained model to measure.

### Stretch goals (after Phase 1 ships)

- On-device inference via Core ML — the backbone is already chosen for this
- Multi-item plate detection (segment-then-classify, reusing the Phase 1 classifier per detected region)
- A zero-shot multimodal-LLM baseline, benchmarked against the trained classifier

No performance or accuracy claims are made here until they're measured — see
[`benchmarks/`](benchmarks).

## License

MIT — see [LICENSE](LICENSE).
