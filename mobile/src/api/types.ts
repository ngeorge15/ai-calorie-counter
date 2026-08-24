/** Per-100g nutrition. Every field nullable: crowd-sourced data has holes. */
export type Per100g = {
  calories: number | null;
  protein_g: number | null;
  carbs_g: number | null;
  fat_g: number | null;
  fiber_g: number | null;
  sugar_g: number | null;
  sodium_mg: number | null;
};

/** Normalized product. USDA and Open Food Facts both collapse into this. */
export type Product = {
  barcode: string | null;
  name: string | null;
  brand: string | null;
  serving_size: string | null;
  serving_g: number | null;
  image_url: string | null;
  per_100g: Per100g;
  source?: 'usda' | 'off' | 'user';
};

export type LookupOrigin = 'cache' | 'usda' | 'off' | 'user' | 'miss';

export type ProductResponse = {
  product: Product;
  origin: LookupOrigin;
};

/** Wire shape for a meal. snake_case to match the backend exactly. */
export type MealPayload = {
  client_id: string;
  name?: string | null;
  brand?: string | null;
  barcode?: string | null;
  serving_g?: number | null;
  calories?: number | null;
  protein_g?: number | null;
  carbs_g?: number | null;
  fat_g?: number | null;
  fiber_g?: number | null;
  sugar_g?: number | null;
  sodium_mg?: number | null;
  meal_type?: 'breakfast' | 'lunch' | 'dinner' | 'snack' | null;
  eaten_at: string;
  source: 'barcode' | 'photo' | 'manual' | 'recent';
  model_confidence?: number | null;
  user_edited: boolean;
  deleted: boolean;
  updated_at: string;
};

export type SyncResponse = {
  /** The server's clock. The ONLY valid value for the next `since`. */
  server_time: string;
  applied: string[];
  /** Server copies that beat a local edit. Overwrite local with these. */
  conflicts: MealPayload[];
  changes: MealPayload[];
};
