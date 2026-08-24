import { createMMKV } from 'react-native-mmkv';

import type { Product } from '../api/types';

/**
 * Barcode -> product cache.
 *
 * MMKV rather than SQLite because this is pure key-value and sits on the
 * critical path of a scan: you are standing in an aisle waiting for a number.
 *
 * No TTL, deliberately. Product formulations change on the order of years, and
 * a slightly stale macro beats a spinner every time. The cache is also what
 * keeps us inside Open Food Facts' rate limit.
 */
// MMKV v4 replaced `new MMKV()` with createMMKV(); most docs still show the old form.
const storage = createMMKV({ id: 'product-cache' });

const key = (barcode: string) => `p:${barcode}`;

/** Timing for /benchmarks/cache_latency.md. Real measurements, not estimates. */
export type LookupTiming = {
  barcode: string;
  hit: boolean;
  /** Milliseconds from call to resolved product. */
  ms: number;
  /** cache | usda | off | user | miss — where the number actually came from. */
  origin: string;
};

const timings: LookupTiming[] = [];

export function recordTiming(entry: LookupTiming) {
  timings.push(entry);
}

export function drainTimings(): LookupTiming[] {
  return timings.splice(0, timings.length);
}

export function getCachedProduct(barcode: string): Product | null {
  const raw = storage.getString(key(barcode));
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Product;
  } catch {
    // A corrupt entry must never wedge a scan; drop it and fall through.
    storage.remove(key(barcode));
    return null;
  }
}

export function cacheProduct(barcode: string, product: Product): void {
  storage.set(key(barcode), JSON.stringify(product));
}

export function clearProductCache(): void {
  storage.clearAll();
}
