# Build notes

## VisionCamera v5 has no Expo config plugin

v5.2.3 ships no `app.plugin.js`. The `["react-native-vision-camera", {...}]`
entry that v3/v4 tutorials show is invalid and Expo silently loads the package
main instead, then fails at prebuild.

Configure it through `app.json` directly instead:
- iOS: `ios.infoPlist.NSCameraUsageDescription`
- Android: `android.permissions: ["android.permission.CAMERA"]`

Code scanning on iOS goes through AVFoundation and needs no extra dependency.
**Android is unverified** — v5 exposes no `enableCodeScanner` gradle flag the
way v4 did, so if Android is targeted later, confirm how MLKit gets pulled in.

## npm needs legacy-peer-deps

See `.npmrc`. expo-router depends on a `react-dom` newer than the `react` Expo
SDK 57 pins. Only affects web, which this app doesn't target.

## MMKV v4 API

`new MMKV()` was removed in v4. Use `createMMKV({ id })`, and `.remove()`
rather than `.delete()`. Most tutorials online still show the v2/v3 form.

## VisionCamera v5 is a ground-up rewrite

v5 is Nitro-based and its scanning API is nothing like v4's. Tutorials and LLM
output describing v4 will not compile.

| v4 | v5 |
| --- | --- |
| `useCodeScanner({ codeTypes, onCodeScanned })` | `useObjectOutput({ types, onObjectsScanned })` |
| `<Camera codeScanner={...} />` | `<Camera outputs={[objectOutput]} />` |
| callback receives `Code[]` | receives `ScannedObject[]`; narrow with `isScannedCode()` |

Codes, faces and bodies now share one object-detection pipeline.

**No `upc-a` code type.** This is correct, not an omission: a 12-digit UPC-A is
an EAN-13 with a leading zero, so `ean-13` covers US products. The padding is
reconciled in `backend/app/usda_client.py::_upc_variants`.

`ScannedObject` is annotated `@platform iOS`. Android scanning in v5 is
unverified — see the plugin note above.

## iOS 16.4 is the floor

Expo SDK 57 refuses a `deploymentTarget` below 16.4.

## babel.config.js means you own babel-preset-expo

SDK 57 resolves `babel-preset-expo` internally and ships no `babel.config.js`.
Adding one (needed here for `inline-import` of `.sql` migrations) makes the
preset an explicit devDependency — otherwise Metro fails with
`Cannot find module 'babel-preset-expo'`.
