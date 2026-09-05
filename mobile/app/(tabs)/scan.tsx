import { useRouter } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import {
  Camera,
  CommonResolutions,
  isScannedCode,
  useCameraDevice,
  useCameraPermission,
  useObjectOutput,
  usePhotoOutput,
} from 'react-native-vision-camera';

import { classifyPhoto } from '../../src/api/classify';
import { ping } from '../../src/api/client';
import { lookupBarcode } from '../../src/api/products';
import { createMeal } from '../../src/db/meals';

/**
 * The formats actually printed on grocery packaging.
 *
 * Note there is no 'upc-a': a 12-digit UPC-A is an EAN-13 with a leading zero,
 * so 'ean-13' already covers US products. That zero-padding is exactly what
 * backend/app/usda_client.py's _upc_variants() reconciles against FDC records.
 */
const CODE_TYPES = ['ean-13', 'ean-8', 'upc-e'] as const;

type Mode = 'barcode' | 'photo';

/**
 * One screen, two capture modes.
 *
 * A photo-classify flow needs the exact same device/permission/no-camera
 * boilerplate the barcode scanner already has, so it lives here as a second
 * mode rather than a second screen that would duplicate all of that (and
 * duplicate the two empty-state screens below). Barcode scanning uses
 * useObjectOutput; photo capture uses usePhotoOutput — only one of the two
 * outputs is ever wired into the running Camera at a time via `outputs`.
 */
export default function ScanScreen() {
  const router = useRouter();
  const device = useCameraDevice('back');
  const { hasPermission, requestPermission } = useCameraPermission();

  const [mode, setMode] = useState<Mode>('barcode');

  // --- Barcode mode state ---
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  // The scanner fires continuously on every frame; without this guard a single
  // barcode held in view would log dozens of meals.
  const handling = useRef(false);

  // --- Photo mode state ---
  const [capturing, setCapturing] = useState(false);
  const [classifying, setClassifying] = useState(false);
  const [photoError, setPhotoError] = useState<string | null>(null);

  // Wake a sleeping Render dyno the moment the user shows intent to take a
  // photo, rather than during the classify call itself — the same idea as
  // the sync path's use of ping(), just triggered by mode instead of an
  // interval. Best-effort: classifyPhoto's own timeout covers a cold start
  // this doesn't finish in time.
  useEffect(() => {
    if (mode === 'photo') void ping();
  }, [mode]);

  const onScan = useCallback(
    async (barcode: string) => {
      if (handling.current) return;
      handling.current = true;
      setBusy(true);

      try {
        const { product, origin, ms } = await lookupBarcode(barcode);
        setStatus(`${origin} · ${ms}ms`);

        if (!product) {
          // A miss is never a dead end: open the editor prefilled so the user
          // can type it in, and that entry becomes tomorrow's cache hit.
          router.push({
            pathname: '/meal/[clientId]',
            params: { clientId: 'new', barcode },
          });
          return;
        }

        const grams = product.serving_g ?? 100;
        const factor = grams / 100;
        const scale = (v: number | null) =>
          v === null ? null : Math.round(v * factor * 10) / 10;

        const meal = await createMeal({
          name: product.name,
          brand: product.brand,
          barcode,
          servingG: grams,
          calories: scale(product.per_100g.calories),
          proteinG: scale(product.per_100g.protein_g),
          carbsG: scale(product.per_100g.carbs_g),
          fatG: scale(product.per_100g.fat_g),
          fiberG: scale(product.per_100g.fiber_g),
          sugarG: scale(product.per_100g.sugar_g),
          sodiumMg: scale(product.per_100g.sodium_mg),
          eatenAt: new Date().toISOString(),
          source: 'barcode',
          userEdited: false,
          deleted: false,
        });

        // Straight into the editor. Every generated number stays correctable
        // before it counts — logging is never blocked on confidence.
        router.push({
          pathname: '/meal/[clientId]',
          params: { clientId: meal.clientId },
        });
      } finally {
        setBusy(false);
        // Debounce so the same code isn't re-read the instant we return.
        setTimeout(() => {
          handling.current = false;
        }, 1500);
      }
    },
    [router],
  );

  // v5 replaced v4's useCodeScanner with a generic object-output pipeline:
  // codes, faces and bodies all arrive as ScannedObjects and are narrowed.
  const objectOutput = useObjectOutput({
    types: [...CODE_TYPES],
    onObjectsScanned: (objects) => {
      for (const object of objects) {
        if (isScannedCode(object) && object.value) {
          void onScan(object.value);
          return;
        }
      }
    },
  });

  // FHD_4_3 (1440x1920) at 0.85 quality keeps a JPEG comfortably under the
  // endpoint's 10MB cap while staying well above what the classifier needs.
  const photoOutput = usePhotoOutput({
    targetResolution: CommonResolutions.FHD_4_3,
    containerFormat: 'jpeg',
    quality: 0.85,
    qualityPrioritization: 'balanced',
  });

  const onCapturePhoto = useCallback(async () => {
    if (capturing || classifying) return;
    setPhotoError(null);
    setCapturing(true);

    try {
      const file = await photoOutput.capturePhotoToFile(
        { flashMode: 'off' },
        {},
      );
      setCapturing(false);
      setClassifying(true);

      // capturePhotoToFile's filePath is a bare filesystem path, not a
      // file:// URL (see react-native-vision-camera's CameraPhotoOutput.nitro
      // and Photo.nitro type docs) — both <Image> and multipart upload need
      // the scheme added back on.
      const uri = `file://${file.filePath}`;
      const outcome = await classifyPhoto(uri);

      if (outcome.ok) {
        router.push({
          pathname: '/photo/review',
          params: {
            photoUri: uri,
            predictions: JSON.stringify(outcome.predictions),
          },
        });
      } else {
        setPhotoError(outcome.message);
      }
    } catch {
      setPhotoError('Could not capture that photo. Try again.');
    } finally {
      setCapturing(false);
      setClassifying(false);
    }
  }, [capturing, classifying, photoOutput, router]);

  if (!hasPermission) {
    return (
      <View style={styles.center}>
        <Text style={styles.title}>Camera access needed</Text>
        <Text style={styles.body}>
          Scanning barcodes and photographing meals both require the camera.
          Nothing leaves your device except what you choose to log.
        </Text>
        <Pressable style={styles.button} onPress={requestPermission}>
          <Text style={styles.buttonText}>Grant access</Text>
        </Pressable>
      </View>
    );
  }

  if (device == null) {
    return (
      <View style={styles.center}>
        <Text style={styles.title}>No camera found</Text>
        <Text style={styles.body}>
          The simulator has no camera. Use a physical device to scan or
          photograph.
        </Text>
      </View>
    );
  }

  const photoBusy = capturing || classifying;

  return (
    <View style={styles.fill}>
      <Camera
        style={StyleSheet.absoluteFill}
        device={device}
        isActive={!busy && !photoBusy}
        outputs={mode === 'barcode' ? [objectOutput] : [photoOutput]}
      />

      <View style={styles.modeSwitch}>
        <ModeButton
          label="Barcode"
          active={mode === 'barcode'}
          onPress={() => setMode('barcode')}
        />
        <ModeButton
          label="Photo"
          active={mode === 'photo'}
          onPress={() => {
            setPhotoError(null);
            setMode('photo');
          }}
        />
      </View>

      {mode === 'barcode' && (
        <>
          <View style={styles.reticle} pointerEvents="none" />
          <View style={styles.overlay}>
            {busy ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.overlayText}>
                {status ?? 'Point at a barcode'}
              </Text>
            )}
          </View>
        </>
      )}

      {mode === 'photo' && (
        <View style={styles.overlay}>
          {photoError ? (
            <View style={styles.errorBox}>
              <Text style={styles.errorText}>{photoError}</Text>
              <Pressable
                style={styles.errorRetry}
                onPress={() => setPhotoError(null)}
              >
                <Text style={styles.errorRetryText}>Try again</Text>
              </Pressable>
            </View>
          ) : photoBusy ? (
            <View style={styles.busyBox}>
              <ActivityIndicator color="#fff" />
              <Text style={styles.overlayText}>
                {capturing ? 'Capturing…' : 'Classifying…'}
              </Text>
            </View>
          ) : (
            <Pressable style={styles.shutter} onPress={onCapturePhoto}>
              <View style={styles.shutterInner} />
            </Pressable>
          )}
        </View>
      )}
    </View>
  );
}

function ModeButton({
  label,
  active,
  onPress,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={[styles.modeButton, active && styles.modeButtonActive]}
    >
      <Text style={[styles.modeButtonText, active && styles.modeButtonTextActive]}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: '#000' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32, gap: 12 },
  title: { fontSize: 18, fontWeight: '600' },
  body: { fontSize: 14, opacity: 0.7, textAlign: 'center' },
  button: { marginTop: 8, paddingHorizontal: 20, paddingVertical: 12, borderRadius: 10, backgroundColor: '#2563eb' },
  buttonText: { color: '#fff', fontWeight: '600' },
  reticle: {
    position: 'absolute', left: '10%', right: '10%', top: '35%', height: 160,
    borderWidth: 2, borderColor: 'rgba(255,255,255,0.8)', borderRadius: 12,
  },
  overlay: { position: 'absolute', bottom: 48, left: 0, right: 0, alignItems: 'center' },
  overlayText: { color: '#fff', fontSize: 14, backgroundColor: 'rgba(0,0,0,0.5)', paddingHorizontal: 14, paddingVertical: 8, borderRadius: 20 },
  modeSwitch: {
    position: 'absolute', top: 16, left: 0, right: 0,
    flexDirection: 'row', justifyContent: 'center', gap: 8,
  },
  modeButton: {
    paddingHorizontal: 16, paddingVertical: 8, borderRadius: 18,
    backgroundColor: 'rgba(0,0,0,0.5)',
  },
  modeButtonActive: { backgroundColor: '#2563eb' },
  modeButtonText: { color: '#fff', fontSize: 13, fontWeight: '600' },
  modeButtonTextActive: { color: '#fff' },
  shutter: {
    width: 72, height: 72, borderRadius: 36,
    borderWidth: 4, borderColor: '#fff',
    alignItems: 'center', justifyContent: 'center',
  },
  shutterInner: {
    width: 58, height: 58, borderRadius: 29, backgroundColor: '#fff',
  },
  busyBox: { alignItems: 'center', gap: 10 },
  errorBox: {
    backgroundColor: 'rgba(0,0,0,0.75)', borderRadius: 14,
    paddingHorizontal: 18, paddingVertical: 16, gap: 10,
    maxWidth: '85%', alignItems: 'center',
  },
  errorText: { color: '#fff', fontSize: 14, textAlign: 'center' },
  errorRetry: {
    backgroundColor: '#2563eb', paddingHorizontal: 16, paddingVertical: 8,
    borderRadius: 10,
  },
  errorRetryText: { color: '#fff', fontSize: 13, fontWeight: '600' },
});
