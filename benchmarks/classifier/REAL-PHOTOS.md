# Collecting a real-photo eval set

This is the how-to for the eval METHODOLOGY.md calls "the number that
actually reflects whether the feature works." The harness
(`model-training/eval_real_photos.py`) is built and tested; it has nothing
to run against until a photo set exists. This doc is about collecting that
set without quietly rigging the result.

## How many, and how

- **30-50 photos**, taken with an actual phone camera. Not Food-101 images,
  not stock photos, not screenshots — the whole point is testing whether
  the model generalizes past the curated dataset it was trained on.
- Take them the way you'd actually use the app: pull out a phone, snap a
  plate or a package, don't stage a photo studio. Handheld, ambient
  lighting, whatever angle is natural.
- Save them as a flat directory of image files (`.jpg`/`.png`), and write
  down what each one actually is *before* you run the eval, not after —
  see the manifest section below. Deciding "well, that's kind of a
  caesar salad" after seeing the model's prediction is how you rig your
  own benchmark.

## Variety that matters

A photo set that's 40 clean overhead shots of restaurant plates in good
light will produce a number that means almost nothing, because it's not
what the classifier will actually see in use. Spread the set across:

- **Lighting** — daylight, kitchen overhead light, dim restaurant lighting,
  warm-toned indoor bulbs. The training data (Food-101) is a curated,
  fairly well-lit dataset; real usage will not be.
- **Angles** — top-down and the more natural ~45 degree "phone over a
  plate" angle, not just the flattering angle.
- **Plated vs. packaged** — a home-plated meal looks very different from a
  cafeteria tray, which looks very different from food still in its
  wrapper/container. The 101 trained classes (see below) are all
  restaurant-style plated dishes — none of them are packaged/branded
  products — so packaged-food photos are specifically testing the
  *out-of-vocabulary* failure mode, not a fair top-1 accuracy test.
- **Distance/framing** — a full plate, a close crop, food that's partially
  out of frame or partially eaten (real photos are messy).
- **Backgrounds** — a plain plate, a cluttered table, a to-go container.

## The sampling-bias traps to avoid

This is the part that actually determines whether the resulting number
means anything:

1. **Don't only photograph foods you know the model handles well.** If
   you already have a sense from playing with the app that it nails pizza
   and sushi, resist the urge to fill the set with pizza and sushi. That
   produces a number that flatters the model instead of measuring it.
2. **Include foods outside the 101 Food-101 classes on purpose.** The
   classifier can only ever predict one of the 101 classes it was trained
   on (list below) — it has no "I don't know" output. Feeding it
   completely out-of-vocabulary food (a protein shake, a homemade dish
   with no Food-101 analog, a regional dish the dataset doesn't cover,
   a packaged granola bar) and recording what it *wrongly* guesses is
   exactly how you find the feature's real failure mode. Aim for
   something like a 70/30 or 60/40 split of in-vocab/out-of-vocab photos,
   not 100% in-vocab.
3. **Don't retake a photo because the first one "isn't fair to the
   model."** A blurry, oddly-lit, or awkwardly-framed photo is real input
   the app will see in production. Replacing it with a better shot biases
   the set toward the model's best conditions.
4. **Don't cherry-pick which photos make it into the manifest after
   seeing predictions.** Write ground truth down first (or immediately
   after taking the photo, before running anything), lock the manifest,
   then run the script once. If you want to expand the set later, add a
   new batch — don't edit ground truth on existing entries after seeing
   how the model did.
5. **Vary who/what took the photo if possible.** A single phone, held by
   a single person, in one kitchen, across one afternoon, still narrows
   the lighting/camera/angle distribution more than it looks like it does.

## The 101 trained classes

The classifier can only predict one of these (Food-101's classes, verified
against `model-training/checkpoints/best.pt`'s saved class list — don't
hand-type this list elsewhere, load it from the checkpoint if you need it
programmatically):

```
apple_pie, baby_back_ribs, baklava, beef_carpaccio, beef_tartare, beet_salad,
beignets, bibimbap, bread_pudding, breakfast_burrito, bruschetta,
caesar_salad, cannoli, caprese_salad, carrot_cake, ceviche, cheese_plate,
cheesecake, chicken_curry, chicken_quesadilla, chicken_wings, chocolate_cake,
chocolate_mousse, churros, clam_chowder, club_sandwich, crab_cakes,
creme_brulee, croque_madame, cup_cakes, deviled_eggs, donuts, dumplings,
edamame, eggs_benedict, escargots, falafel, filet_mignon, fish_and_chips,
foie_gras, french_fries, french_onion_soup, french_toast, fried_calamari,
fried_rice, frozen_yogurt, garlic_bread, gnocchi, greek_salad,
grilled_cheese_sandwich, grilled_salmon, guacamole, gyoza, hamburger,
hot_and_sour_soup, hot_dog, huevos_rancheros, hummus, ice_cream, lasagna,
lobster_bisque, lobster_roll_sandwich, macaroni_and_cheese, macarons,
miso_soup, mussels, nachos, omelette, onion_rings, oysters, pad_thai, paella,
pancakes, panna_cotta, peking_duck, pho, pizza, pork_chop, poutine,
prime_rib, pulled_pork_sandwich, ramen, ravioli, red_velvet_cake, risotto,
samosa, sashimi, scallops, seaweed_salad, shrimp_and_grits,
spaghetti_bolognese, spaghetti_carbonara, spring_rolls, steak,
strawberry_shortcake, sushi, tacos, takoyaki, tiramisu, tuna_tartare, waffles
```

Notice these are all restaurant-style plated dishes — no raw single
ingredients (no "an apple," no "a chicken breast"), no packaged/branded
products. Any photo of a raw ingredient or a packaged product is
automatically an out-of-vocabulary test case, which is fine and useful —
just set `food101_label` to `null` for it in the manifest (see below).

## Writing the manifest

The script accepts either JSON (a list of objects) or CSV. See
`benchmarks/classifier/manifest.example.json` for the JSON shape. CSV uses
the same four columns: `filename,ground_truth,food101_label,notes`.

| field           | required | meaning |
|-----------------|----------|---------|
| `filename`      | yes      | must match a file in the photos directory exactly |
| `ground_truth`  | yes      | free-text description of what's actually in the photo, e.g. `"chicken curry"` or `"store-bought granola bar, still in wrapper"`. This is what the USDA search results get matched against. |
| `food101_label` | no       | the *exact* Food-101 class name (from the list above, underscores not spaces) if — and only if — the food genuinely is one of the 101 trained classes. Leave blank/`null` otherwise. This field, not `ground_truth`, is what classifier top-1/top-3 accuracy is computed against, because the model can't be scored as "wrong" on a class it was never trained to know about. |
| `notes`         | no       | lighting, angle, plated/packaged, anything worth remembering when reading the per-photo breakdown later |

The script validates `food101_label` against the checkpoint's actual class
list and fails loudly on a typo (e.g. `pizzaa`) rather than silently
scoring it as a miss.

## Running it

```bash
cd model-training
export USDA_API_KEY=your-key-here   # https://fdc.nal.usda.gov/api-key-signup, free, no card
python eval_real_photos.py \
  --photos-dir /path/to/your/photos \
  --manifest /path/to/manifest.json
```

Results are written to `benchmarks/classifier/real_photos_results.json` (a
separate file from `results.json`, so a run of this script never
overwrites the Food-101 test-set numbers). It reports:

- classifier top-1/top-3 accuracy, computed only over photos that have a
  `food101_label` (in-vocab photos)
- an end-to-end success rate: for every photo, did any of the top-3
  predicted labels' USDA FoodData Central search results actually surface
  the ground-truth food
- a full per-photo breakdown (predictions, confidence, every USDA
  candidate returned, which one matched if any) so a failure is
  inspectable, not just a number

**The end-to-end match is a heuristic** (substring / word-overlap /
fuzzy-string match against USDA's returned descriptions) meant to flag
likely hits and misses for a first pass — it is not perfectly reliable in
either direction (a real match phrased unusually can be missed; an
unrelated food that happens to share words can be flagged as a false
positive). Read the `usda_results` field for each photo before trusting
the aggregate `success_rate_top3`, especially before it goes anywhere near
`results.json` or the README.

Run with `--skip-usda` to get classifier-only numbers without hitting the
USDA API (no end-to-end number is produced in that mode — it's for
sanity-checking the classifier side alone, e.g. while a USDA key is still
being requested).

## After the run

`real_photos_results.json` is a separate file from `results.json` on
purpose (another workstream may be editing `results.json` concurrently).
Once the numbers are reviewed and trusted, fold the relevant fields into
`results.json`'s `real_photo_end_to_end` entry by hand, and update
METHODOLOGY.md's "what's measured" section to match.
