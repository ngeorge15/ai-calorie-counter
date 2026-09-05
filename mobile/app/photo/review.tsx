import { useLocalSearchParams, useRouter } from 'expo-router';
import { useMemo } from 'react';
import { Image, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { ClassifyPrediction } from '../../src/api/classify';

/**
 * Shows the classifier's up-to-3 guesses for a captured photo and lets the
 * user pick one, or reject all of them.
 *
 * The model is ~86% top-1 on Food-101's test set and unvalidated on real
 * phone photos, so a wrong or unhelpful guess is an expected outcome, not a
 * failure state — "none of these" always has to be one tap away, not a dead
 * end. See mobile/AGENTS.md task notes for the accuracy figures; this screen
 * intentionally shows only the model's own per-prediction confidence, never
 * a claim about real-world accuracy.
 *
 * There is currently no name-based product search in this codebase (only
 * barcode lookup exists — see src/api/products.ts and
 * backend/app/routes/products.py). So picking a prediction hands its `query`
 * to the existing meal editor as a prefilled name rather than resolving it to
 * nutrition data automatically; the user fills in the numbers, exactly as
 * they already do after a barcode miss.
 */
export default function PhotoReviewScreen() {
  const router = useRouter();
  const { photoUri, predictions: rawPredictions } = useLocalSearchParams<{
    photoUri?: string;
    predictions?: string;
  }>();

  const predictions = useMemo<ClassifyPrediction[]>(() => {
    if (!rawPredictions) return [];
    try {
      const parsed = JSON.parse(rawPredictions);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }, [rawPredictions]);

  function choosePrediction(prediction: ClassifyPrediction) {
    // Replace, not push: once a choice is made this screen is done, and
    // saving or backing out of the editor should land on the camera/tabs
    // underneath, not bounce back through this review screen.
    router.replace({
      pathname: '/meal/[clientId]',
      params: {
        clientId: 'new',
        name: prediction.query,
        source: 'photo',
        modelConfidence: String(prediction.confidence),
      },
    });
  }

  function searchManually() {
    router.replace({
      pathname: '/meal/[clientId]',
      params: { clientId: 'new' },
    });
  }

  return (
    <ScrollView contentContainerStyle={styles.content}>
      {photoUri && (
        <Image source={{ uri: photoUri }} style={styles.photo} resizeMode="cover" />
      )}

      <Text style={styles.heading}>Does this look right?</Text>
      <Text style={styles.subheading}>
        Pick the closest match — you'll fill in the nutrition details next.
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
              <Text style={styles.cardConfidence}>
                {Math.round(prediction.confidence * 100)}% match
              </Text>
            </Pressable>
          ))}
        </View>
      )}

      <Pressable style={styles.manual} onPress={searchManually}>
        <Text style={styles.manualText}>None of these — enter it myself</Text>
      </Pressable>
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
  heading: { fontSize: 19, fontWeight: '700', marginTop: 4 },
  subheading: { fontSize: 14, opacity: 0.65 },
  empty: { fontSize: 14, opacity: 0.65, paddingVertical: 8 },
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
  },
  cardTitle: { fontSize: 16, fontWeight: '600', textTransform: 'capitalize' },
  cardConfidence: { fontSize: 13, opacity: 0.6 },
  manual: { marginTop: 10, paddingVertical: 14, alignItems: 'center' },
  manualText: { color: '#2563eb', fontSize: 15, fontWeight: '600' },
});
