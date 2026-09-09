# Deploying the backend

Render free tier, ~10 minutes. The Blueprint (`render.yaml`, repo root)
already encodes the service config; what follows is the part that needs a
human, plus the checks worth running afterwards.

## Before you start

You need four values to hand:

| Variable | Where it comes from |
|---|---|
| `MONGODB_URI` | MongoDB Atlas → your M0 cluster → Connect → Drivers. Includes a password. |
| `USDA_API_KEY` | https://fdc.nal.usda.gov/api-key-signup — free, no card |
| `OFF_USER_AGENT` | A contact string, e.g. `CalorieCounter/1.0 (your@email)`. Open Food Facts blocks unidentified clients; this is a hard requirement of theirs, not politeness. |
| `JWT_SECRET` | **Don't set this.** Render generates it (`generateValue: true`). |

## Deploy

1. render.com → **New** → **Blueprint**
2. Connect the `ngeorge15/ai-calorie-counter` repo. Render reads
   `render.yaml` from the root and proposes one web service,
   `calorie-counter-api`.
3. It prompts for the three `sync: false` variables above. Paste them.
4. Apply. First build takes a few minutes — it installs `onnxruntime`,
   `numpy` and `Pillow`, all of which have prebuilt Linux wheels for
   Python 3.12, so nothing compiles from source.

## Atlas network access

Atlas rejects connections from unknown IPs, and Render's free tier has no
static outbound IP. In Atlas → Network Access, allow `0.0.0.0/0`.

That is genuinely open to the internet, and it's acceptable here only
because the database is defended by credentials rather than by network
position: the URI carries a password, the user should be scoped to this
one database, and nothing else is exposed. If this ever handles anyone
else's data, move to a paid tier with a static IP and drop the wildcard.

## Verify it worked

Substitute your service URL:

```bash
BASE=https://calorie-counter-api.onrender.com

# 1. Health check. On a cold instance this may take 30-60s — the free tier
#    sleeps when idle, and this request is what wakes it.
curl -s $BASE/api/health

# 2. Register (or log in) to get a token.
curl -s -X POST $BASE/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"a-long-password"}'

# 3. Classify a real photo. Anything plated will do.
TOKEN=paste-the-token
curl -s -X POST $BASE/api/classify \
  -H "Authorization: Bearer $TOKEN" \
  -F image=@/path/to/food.jpg

# 4. Turn a predicted name into real nutrition.
curl -s -G $BASE/api/products/search \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode 'q=chicken curry'
```

Step 3 returning three predictions means the ONNX model loaded and the
whole serving path works. A `503` there means the model file wasn't found
in the checkout; a `502` on step 4 means USDA rejected the key.

## Point the phone at it

In `mobile/.env`:

    EXPO_PUBLIC_API_BASE_URL=https://calorie-counter-api.onrender.com

Rebuild the app for the change to take effect — Expo inlines
`EXPO_PUBLIC_*` at build time rather than reading it at runtime.

## What to expect from the free tier

The instance sleeps after inactivity, so the first request after a quiet
period pays a cold start, and the first *classify* additionally pays
one-time ONNX session initialisation. The app already mitigates this: the
scan screen pings `/api/health` in the background when you switch to photo
mode, so the instance is usually awake before the shutter is pressed.

Memory is the constraint that shaped the architecture, and it has room:
the ONNX serving stack peaks around 136MB against roughly 512MB available
(PyTorch would have been ~310MB — see
`benchmarks/classifier/results.json`). Those are dev-machine figures, so
watch Render's own memory graph after the first few requests and treat
that as the real number.

## Then: measure the latency

`server_inference_latency` is still listed under `not_yet_measured` in
`benchmarks/classifier/results.json`. It is the direct test of the
decision to serve inference server-side instead of on-device, so measure
cold and warm separately and record both — a warm-only number would flatter
the architecture by hiding exactly the cost that decision incurred.
