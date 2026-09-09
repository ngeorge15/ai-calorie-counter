# Getting the app onto an iPhone

No paid Apple Developer account. The app is built by EAS (Expo's cloud
builder, so no Xcode needed locally) and installed with **SideStore**,
which re-signs it using your free Apple ID.

> **Status: not yet performed.** The persistence design below is
> implemented and in the code; the build itself has never been run. Config
> here follows Expo's documented options, but treat the first run as a
> shakedown and correct this file with whatever actually happens.

## Why the meal history survives re-signing

A free Apple ID signing certificate expires every 7 days, so a sideloaded
app has to be re-signed regularly. Two things in this codebase are what
keep that from wiping your data each time — neither is incidental:

- **The bundle identifier is pinned** to `com.nikhil.caloriecounter` in
  `app.json`. iOS keys an app's container to its bundle id, so a changed id
  is a *different app* to the OS, with an empty database. See the comment in
  `src/db/client.ts`. **Never change this value.**
- **The auth token lives in the Keychain**, restored on cold start
  (`src/lib/auth.tsx`), so a re-signed install doesn't force a fresh login
  every week.

The SQLite filename is likewise fixed (`calorie-counter.db`) rather than
generated, for the same reason.

## Order of operations

The backend URL is compiled into the binary — Expo inlines `EXPO_PUBLIC_*`
at build time rather than reading it at runtime. So:

1. **Deploy the backend first** (see `../DEPLOY.md`) and note its URL.
2. Put that URL in the `sideload` profile's `env` in `eas.json` if it
   differs from the default there.
3. Then build. Pointing the app at a different backend later means another
   build, not an app setting.

## Build

```bash
cd mobile
npm install -g eas-cli        # or: npx eas-cli@latest
eas login                     # free Expo account
eas build --platform ios --profile sideload
```

The build runs on Expo's servers (free tier: 15 iOS builds/month, so don't
burn them casually) and ends with a download link for an `.ipa`.

`withoutCredentials: true` is what lets this run without an Apple Developer
account — EAS skips signing entirely and SideStore signs at install.

**First-run unknowns, to verify rather than assume:** whether EAS produces a
directly installable artifact under `withoutCredentials` or requires an
extra repackaging step, and whether it prompts for credentials anyway. If it
does prompt, decline rather than entering an Apple ID — and record what
happened here.

## Install with SideStore

1. Set up SideStore on the iPhone per its current instructions
   (sidestore.io). Modern SideStore refreshes certificates on-device using
   a local VPN mechanism, so it does **not** need a tethered Mac every week
   the way older AltStore setups did.
2. Get the `.ipa` onto the phone (AirDrop, iCloud Drive, or the EAS
   download link opened on the device).
3. Open it in SideStore and install. SideStore signs it with your free
   Apple ID.
4. Trust the developer profile: Settings → General → VPN & Device
   Management.

A free Apple ID also caps you at **3 sideloaded apps** at once — worth
knowing before you install two other things and wonder why this one won't.

## Point it at the right backend

The `sideload` profile bakes in `EXPO_PUBLIC_API_BASE_URL`. For local
development against a laptop-hosted backend instead, `.env.example`
documents the Tailscale route — a real TLS cert and a hostname stable
across wifi and cellular, which beats a LAN IP that changes.

## What only works on a real device

- **Barcode scanning and photo capture.** The Simulator has no camera, so
  neither can be tested there. `mobile/NOTES.md` also records that
  VisionCamera v5's `ScannedObject` is annotated iOS-only and that Android
  scanning is unverified.
- The full offline → sync round trip against a sleeping free-tier backend.

## Refresh cadence

The 7-day certificate expiry is Apple's limit on free accounts, not
SideStore's. SideStore handles the refresh itself once set up; the app
keeps its data across refreshes for the bundle-id reason above. If the app
ever launches to an empty history, the first thing to check is whether the
bundle identifier changed.
