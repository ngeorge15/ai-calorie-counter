import { useRouter } from 'expo-router';
import { useCallback, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import {
  Camera,
  isScannedCode,
  useCameraDevice,
  useCameraPermission,
  useObjectOutput,
} from 'react-native-vision-camera';

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

export default function ScanScreen() {
  const router = useRouter();
  const device = useCameraDevice('back');
  const { hasPermission, requestPermission } = useCameraPermission();

  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  // The scanner fires continuously on every frame; without this guard a single
  // barcode held in view would log dozens of meals.
  const handling = useRef(false);

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

  if (!hasPermission) {
    return (
      <View style={styles.center}>
        <Text style={styles.title}>Camera access needed</Text>
        <Text style={styles.body}>
          Scanning barcodes requires the camera. Nothing leaves your device
          except the barcode number itself.
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
          The simulator has no camera. Use a physical device to scan.
        </Text>
      </View>
    );
  }

  return (
    <View style={styles.fill}>
      <Camera
        style={StyleSheet.absoluteFill}
        device={device}
        isActive={!busy}
        outputs={[objectOutput]}
      />
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
    </View>
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
});
