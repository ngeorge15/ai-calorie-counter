import { useLocalSearchParams, useRouter } from 'expo-router';
import { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import type { ClassifyPrediction } from '../../src/api/classify';
import { scaleToServing, searchProducts } from '../../src/api/products';
import type { SearchResult } from '../../src/api/products';
import { createMeal } from '../../src/db/meals';

/**
 * The photo flow's two picks: which food the classifier got right, then
 * which database entry actually matches it.
 *
 * Both stages live in one screen rather than two routes, so backing out of
 * the product list returns to the predictions instantly instead of
 * re-running the classifier on a photo that hasn't changed.
 *
 * The model is ~86% top-1 on Food-101's test set and has NOT been validated
 * on real phone photos, so a wrong guess is an expected outcome rather than
 * an error state. Every stage keeps an escape hatch one tap away: reject all
 * three predictions, or reject every product match, and land in manual entry
 * — the same place a barcode miss already lands.
 */
type Stage =
  | { kind: 'predictions' }
  | { kind: 'searching'; prediction: ClassifyPrediction }
  | { kind: 'results'; prediction: ClassifyPrediction; products: SearchResult[] }
  | { kind: 'failed'; prediction: ClassifyPrediction; message: string };

export default function PhotoReviewScreen() {
  const router = useRouter();
  const { photoUri, predictions: rawPredictions } = useLocalSearchParams<{
    photoUri?: string;
    predictions?: string;
  }>();

  const [stage, setStage] = useState<Stage>({ kind: 'predictions' });

  const predictions = useMemo<ClassifyPrediction[]>(() => {
    if (!rawPredictions) return [];
    try {
      const parsed = JSON.parse(rawPredictions);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }, [rawPredictions]);

  async function choosePrediction(prediction: ClassifyPrediction) {
    setStage({ kind: 'searching', prediction });
    const outcome = await searchProducts(prediction.query);

    if (!outcome.ok) {
      setStage({ kind: 'failed', prediction, message: outcome.message });
      return;
    }
    // An empty list is a real answer, not a failure — the backend
    // deliberately distinguishes "nothing matched" from "search broke", so
    // this keeps them separate too.
    setStage({ kind: 'results', prediction, products: outcome.products });
  }

  /** Log the chosen product with its real nutrition, exactly as a successful
   *  barcode scan does — the whole point of the search step. */
  async function chooseProduct(
    product: SearchResult,
    prediction: ClassifyPrediction,
  ) {
    const grams = product.serving_g ?? 100;
    const scaled = scaleToServing(product, grams);

    // Mapped field by field, NOT spread. scaleToServing returns the API's
    // snake_case shape (protein_g) while the Drizzle schema is camelCase
    // (proteinG) — and a spread inside an object literal skips TypeScript's
    // excess-property check, so `...scaled` typechecks clean and silently
    // drops every macro except calories. This is also why scan.tsx scales
    // inline instead of calling the shared helper.
    const meal = await createMeal({
      name: product.name ?? prediction.query,
      brand: product.brand,
      barcode: null,
      servingG: grams,
      calories: scaled.calories,
      proteinG: scaled.protein_g,
      carbsG: scaled.carbs_g,
      fatG: scaled.fat_g,
      fiberG: scaled.fiber_g,
      sugarG: scaled.sugar_g,
      sodiumMg: scaled.sodium_mg,
      eatenAt: new Date().toISOString(),
      source: 'photo',
      modelConfidence: prediction.confidence,
      userEdited: false,
      deleted: false,
    });

    // Into the editor, same as a barcode hit: every generated number stays
    // correctable before it counts.
    router.replace({
      pathname: '/meal/[clientId]',
      params: { clientId: meal.clientId },
    });
  }

  /** Manual entry, optionally carrying the name the user already confirmed. */
  function enterManually(prediction?: ClassifyPrediction) {
    router.replace({
      pathname: '/meal/[clientId]',
      params: prediction
        ? {
            clientId: 'new',
            name: prediction.query,
            source: 'photo',
            modelConfidence: String(prediction.confidence),
          }
        : { clientId: 'new' },
    });
  }

  return (
    <ScrollView contentContainerStyle={styles.content}>
      {photoUri && (
        <Image source={{ uri: photoUri }} style={styles.photo} resizeMode="cover" />
      )}

      {stage.kind === 'predictions' && (
        <>
          <Text style={styles.heading}>Does this look right?</Text>
          <Text style={styles.subheading}>
            Pick the closest match and we'll look up its nutrition.
          </Text>

          {predictions.length === 0 ? (
            <Text style={styles.empty}>No guesses came back for this photo.</Text>
          ) : (
            <View style={styles.list}>
              {predictions.map((prediction) => (
                <Pressable
                  key={prediction.label}
                  style={styles.card}
                  onPress={() => choosePrediction(prediction)}
                >
                  <Text style={styles.cardTitle}>{prediction.query}</Text>
                  <Text style={styles.cardMeta}>
                    {Math.round(prediction.confidence * 100)}% match
                  </Text>
                </Pressable>
              ))}
            </View>
          )}

          <Pressable style={styles.textButton} onPress={() => enterManually()}>
            <Text style={styles.textButtonLabel}>
              None of these — enter it myself
            </Text>
          </Pressable>
        </>
      )}

      {stage.kind === 'searching' && (
        <View style={styles.busy}>
          <ActivityIndicator />
          <Text style={styles.subheading}>
            Looking up “{stage.prediction.query}”…
          </Text>
        </View>
      )}

      {stage.kind === 'results' && (
        <>
          <Text style={styles.heading}>{stage.prediction.query}</Text>
          <Text style={styles.subheading}>
            {stage.products.length > 0
              ? 'Pick the entry that matches what you ate.'
              : `Nothing in the food database matched “${stage.prediction.query}”.`}
          </Text>

          <View style={styles.list}>
            {stage.products.map((product, i) => {
              const perServing = product.serving_g
                ? scaleToServing(product, product.serving_g)
                : null;
              const kcal = perServing?.calories ?? product.per_100g.calories;
              return (
                <Pressable
                  key={product.fdc_id ?? `${product.name}-${i}`}
                  style={styles.card}
                  onPress={() => chooseProduct(product, stage.prediction)}
                >
                  <View style={styles.cardMain}>
                    <Text style={styles.cardTitle}>{product.name ?? 'Unnamed'}</Text>
                    {product.brand && (
                      <Text style={styles.cardMeta}>{product.brand}</Text>
                    )}
                  </View>
                  <Text style={styles.cardMeta}>
                    {kcal === null
                      ? 'no calorie data'
                      : `${Math.round(kcal)} kcal / ${
                          product.serving_g ? `${product.serving_g}g` : '100g'
                        }`}
                  </Text>
                </Pressable>
              );
            })}
          </View>

          <Pressable
            style={styles.textButton}
            onPress={() => enterManually(stage.prediction)}
          >
            <Text style={styles.textButtonLabel}>
              {stage.products.length > 0
                ? 'None of these — enter it myself'
                : 'Enter it myself'}
            </Text>
          </Pressable>
          <Pressable
            style={styles.textButton}
            onPress={() => setStage({ kind: 'predictions' })}
          >
            <Text style={styles.textButtonSubtle}>Back to the other guesses</Text>
          </Pressable>
        </>
      )}

      {stage.kind === 'failed' && (
        <>
          <Text style={styles.heading}>Couldn't look that up</Text>
          <Text style={styles.subheading}>{stage.message}</Text>
          <View style={styles.list}>
            <Pressable
              style={styles.card}
              onPress={() => choosePrediction(stage.prediction)}
            >
              <Text style={styles.cardTitle}>Try again</Text>
            </Pressable>
          </View>
          <Pressable
            style={styles.textButton}
            onPress={() => enterManually(stage.prediction)}
          >
            <Text style={styles.textButtonLabel}>
              Enter “{stage.prediction.query}” manually
            </Text>
          </Pressable>
          <Pressable
            style={styles.textButton}
            onPress={() => setStage({ kind: 'predictions' })}
          >
            <Text style={styles.textButtonSubtle}>Back to the other guesses</Text>
          </Pressable>
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: 20, gap: 14, paddingBottom: 40 },
  photo: {
    width: '100%',
    aspectRatio: 4 / 3,
    borderRadius: 12,
    backgroundColor: '#e5e7eb',
  },
  heading: { fontSize: 19, fontWeight: '700', marginTop: 4, textTransform: 'capitalize' },
  subheading: { fontSize: 14, opacity: 0.65 },
  empty: { fontSize: 14, opacity: 0.65, paddingVertical: 8 },
  busy: { paddingVertical: 28, alignItems: 'center', gap: 12 },
  list: { gap: 10, marginTop: 4 },
  card: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 12,
  },
  cardMain: { flexShrink: 1, gap: 2 },
  cardTitle: { fontSize: 16, fontWeight: '600', textTransform: 'capitalize' },
  cardMeta: { fontSize: 13, opacity: 0.6, flexShrink: 0 },
  textButton: { paddingVertical: 12, alignItems: 'center' },
  textButtonLabel: { color: '#2563eb', fontSize: 15, fontWeight: '600' },
  textButtonSubtle: { color: '#6b7280', fontSize: 14 },
});
