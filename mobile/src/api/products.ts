import { cacheProduct, getCachedProduct, recordTiming } from '../cache/products';
import { ApiError, apiFetch } from './client';
import type { LookupOrigin, Product, ProductResponse } from './types';

export type LookupResult = {
  product: Product | null;
  origin: LookupOrigin;
  ms: number;
};

/**
 * Barcode -> nutrition.
 *
 * Local MMKV cache first, then the Flask proxy (which fans out to USDA, then
 * Open Food Facts). The phone never calls those APIs directly: one backend is
 * one IP with one rate-limit budget, whereas N phones cannot coordinate.
 *
 * Every call is timed and recorded. Phase 4's cache-latency claim has to come
 * from measurements, so the instrumentation ships from the first scan rather
 * than being bolted on once the number is already being quoted.
 */
export async function lookupBarcode(barcode: string): Promise<LookupResult> {
  const startedAt = Date.now();

  const cached = getCachedProduct(barcode);
  if (cached) {
    const ms = Date.now() - startedAt;
    recordTiming({ barcode, hit: true, ms, origin: 'cache' });
    return { product: cached, origin: 'cache', ms };
  }

  try {
    const response = await apiFetch<ProductResponse>(
      `/api/products/${barcode}`,
    );
    cacheProduct(barcode, response.product);
    const ms = Date.now() - startedAt;
    recordTiming({ barcode, hit: false, ms, origin: response.origin });
    return { product: response.product, origin: response.origin, ms };
  } catch (error) {
    const ms = Date.now() - startedAt;
    // A 404 is a normal outcome, not a failure: the user types it in and we
    // cache what they enter. Logging is never blocked on a lookup.
    const origin: LookupOrigin =
      error instanceof ApiError && error.status === 404 ? 'miss' : 'miss';
    recordTiming({ barcode, hit: false, ms, origin });
    return { product: null, origin, ms };
  }
}

export type SearchFailureReason =
  | 'empty_query'
  | 'auth'
  | 'rate_limited'
  | 'upstream_failed'
  | 'unavailable'
  | 'unknown';

export type SearchOutcome =
  | { ok: true; products: SearchResult[] }
  | { ok: false; reason: SearchFailureReason; message: string };

/** A search candidate. Same normalized shape as a barcode lookup, but
 *  `barcode` is null and FDC's own id rides along for provenance. */
export type SearchResult = Product & { fdc_id?: number | null };

/**
 * Food name -> candidate products.
 *
 * This is what makes the photo classifier worth anything: it turns a
 * predicted name ("chicken curry") into real nutrition data. Without it the
 * classifier would only ever prefill a text field, leaving the user to type
 * every number by hand — which is what manual entry already was.
 *
 * Deliberately NOT cached locally, mirroring the backend's reasoning:
 * barcode -> product is a stable 1:1 mapping, which is what makes the MMKV
 * cache above safe. A free-text query has no single correct answer and the
 * ranking can legitimately change, so caching it would mean inventing a
 * staleness policy for a mapping that was never one-to-one.
 *
 * An empty result list is a real answer ("nothing matched"), not an error —
 * callers must distinguish it from the failure reasons, since the backend
 * deliberately separates the two.
 */
export async function searchProducts(query: string): Promise<SearchOutcome> {
  const trimmed = query.trim();
  if (!trimmed) {
    return {
      ok: false,
      reason: 'empty_query',
      message: 'Enter something to search for.',
    };
  }

  try {
    const response = await apiFetch<{ products: SearchResult[]; count: number }>(
      `/api/products/search?q=${encodeURIComponent(trimmed)}`,
    );
    return { ok: true, products: response.products ?? [] };
  } catch (error) {
    if (error instanceof ApiError) {
      switch (error.status) {
        case 400:
          return {
            ok: false,
            reason: 'empty_query',
            message: 'That search term was empty or too long.',
          };
        case 401:
          return {
            ok: false,
            reason: 'auth',
            message: 'Signed out — log in again to search foods.',
          };
        case 429:
          return {
            ok: false,
            reason: 'rate_limited',
            message: 'Too many searches — wait a moment and try again.',
          };
        case 502:
          return {
            ok: false,
            reason: 'upstream_failed',
            message:
              "Couldn't reach the food database. You can still enter this meal manually.",
          };
        case 503:
          return {
            ok: false,
            reason: 'unavailable',
            message:
              'Food search is unavailable right now. You can still enter this meal manually.',
          };
        default:
          return { ok: false, reason: 'unknown', message: error.message };
      }
    }
    return {
      ok: false,
      reason: 'unknown',
      message: 'The search timed out or failed. Try again, or enter it manually.',
    };
  }
}

/** Contribute a product the user typed in after a miss, so next scan hits. */
export async function contributeProduct(
  barcode: string,
  product: Partial<Product>,
): Promise<void> {
  const response = await apiFetch<ProductResponse>(
    `/api/products/${barcode}`,
    { method: 'POST', body: product },
  );
  cacheProduct(barcode, response.product);
}

/** Scale per-100g values to an actual serving. */
export function scaleToServing(product: Product, grams: number) {
  const factor = grams / 100;
  const n = product.per_100g;
  const scale = (value: number | null) =>
    value === null ? null : Math.round(value * factor * 10) / 10;

  return {
    calories: scale(n.calories),
    protein_g: scale(n.protein_g),
    carbs_g: scale(n.carbs_g),
    fat_g: scale(n.fat_g),
    fiber_g: scale(n.fiber_g),
    sugar_g: scale(n.sugar_g),
    sodium_mg: scale(n.sodium_mg),
  };
}
