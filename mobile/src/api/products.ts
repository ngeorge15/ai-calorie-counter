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
