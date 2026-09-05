import * as Network from 'expo-network';

import { ApiError, apiUpload } from './client';

/**
 * One guess from the classifier.
 *
 * `query` (not `label`) is what gets typed into product search — it's the
 * human-readable phrase ("chicken curry"), while `label` is the model's own
 * class name (e.g. "chicken_curry") and is only useful for display/debugging.
 */
export type ClassifyPrediction = {
  label: string;
  query: string;
  confidence: number;
};

type ClassifyResponse = {
  predictions: ClassifyPrediction[];
};

export type ClassifyFailureReason =
  | 'offline'
  | 'bad_photo'
  | 'auth'
  | 'too_large'
  | 'rate_limited'
  | 'unavailable'
  | 'unknown';

export type ClassifyOutcome =
  | { ok: true; predictions: ClassifyPrediction[] }
  | { ok: false; reason: ClassifyFailureReason; message: string };

/**
 * Photo -> up to 3 food guesses.
 *
 * Unlike barcode lookup, this has no offline path and no local cache to fall
 * back to: a photo the model hasn't seen has no cached answer. So this checks
 * connectivity up front rather than letting the app sit through a full
 * request timeout only to report the obvious.
 *
 * The model is ~86% top-1 / ~95% top-3 on Food-101's *test set*, and has not
 * been validated against real phone photos. Callers must let the user reject
 * all three predictions and fall back to manual entry — this is expected to
 * happen often, not treated as an edge case.
 */
export async function classifyPhoto(fileUri: string): Promise<ClassifyOutcome> {
  const net = await Network.getNetworkStateAsync();
  if (!net.isConnected || net.isInternetReachable === false) {
    return {
      ok: false,
      reason: 'offline',
      message:
        "You're offline. Photo classification needs an internet connection — barcode scanning and manual entry still work offline.",
    };
  }

  const formData = new FormData();
  // React Native's FormData accepts this {uri, name, type} shape in place of
  // a Blob; fetch reads the file at `uri` when the request is sent.
  formData.append('image', {
    uri: fileUri,
    name: 'meal.jpg',
    type: 'image/jpeg',
  } as unknown as Blob);

  try {
    const response = await apiUpload<ClassifyResponse>(
      '/api/classify',
      formData,
    );
    return { ok: true, predictions: response.predictions };
  } catch (error) {
    if (error instanceof ApiError) {
      switch (error.status) {
        case 400:
          return {
            ok: false,
            reason: 'bad_photo',
            message:
              "Couldn't read that photo. Try a clearer, well-lit shot of the food.",
          };
        case 401:
          return {
            ok: false,
            reason: 'auth',
            message: 'Signed out — log in again to classify photos.',
          };
        case 413:
          return {
            ok: false,
            reason: 'too_large',
            message: 'That photo was too large to upload.',
          };
        case 429:
          return {
            ok: false,
            reason: 'rate_limited',
            message: 'Too many requests — wait a moment and try again.',
          };
        case 503:
          return {
            ok: false,
            reason: 'unavailable',
            message:
              'The classifier is unavailable right now. Try again shortly.',
          };
        default:
          return { ok: false, reason: 'unknown', message: error.message };
      }
    }

    // Not an ApiError: the fetch itself failed — timeout/abort (a cold Render
    // instance taking too long), DNS, TLS, connection reset, etc.
    return {
      ok: false,
      reason: 'unknown',
      message: 'The request timed out or failed. Try again.',
    };
  }
}
