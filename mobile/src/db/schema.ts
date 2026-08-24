import { sql } from 'drizzle-orm';
import { index, integer, real, sqliteTable, text } from 'drizzle-orm/sqlite-core';

/**
 * Local meal log — the source of truth while offline.
 *
 * Mirrors the server's meal shape plus two columns the server never sees:
 * `dirty` (this row has unpushed edits) and `syncedAt`. Everything else is
 * kept byte-compatible with the backend so sync is a field copy, not a
 * translation layer.
 */
export const meals = sqliteTable(
  'meals',
  {
    /**
     * Minted on-device with crypto.randomUUID() at creation time, offline.
     * This is the sync identity: the server upserts on it, which is what
     * makes a retried push idempotent. Never regenerate it for a given meal.
     */
    clientId: text('client_id').primaryKey(),

    name: text('name'),
    brand: text('brand'),
    barcode: text('barcode'),

    servingG: real('serving_g'),
    calories: real('calories'),
    proteinG: real('protein_g'),
    carbsG: real('carbs_g'),
    fatG: real('fat_g'),
    fiberG: real('fiber_g'),
    sugarG: real('sugar_g'),
    sodiumMg: real('sodium_mg'),

    mealType: text('meal_type', {
      enum: ['breakfast', 'lunch', 'dinner', 'snack'],
    }),

    /** ISO8601. Client-supplied so offline entries can be backdated. */
    eatenAt: text('eaten_at').notNull(),

    source: text('source', {
      enum: ['barcode', 'photo', 'manual', 'recent'],
    })
      .notNull()
      .default('manual'),

    /** Model's own confidence, when a model produced this. Null otherwise. */
    modelConfidence: real('model_confidence'),

    /**
     * True once the user has corrected any generated number. Load-bearing for
     * the /benchmarks work: model accuracy can only be measured honestly if we
     * know which rows a human overrode.
     */
    userEdited: integer('user_edited', { mode: 'boolean' })
      .notNull()
      .default(false),

    /** Tombstone. A hard delete could never propagate to the server. */
    deleted: integer('deleted', { mode: 'boolean' }).notNull().default(false),

    /** THIS DEVICE's edit clock. Resolves last-write-wins. Never a cursor. */
    updatedAt: text('updated_at').notNull(),

    /** Unpushed local edits live here. Cleared when the server acks. */
    dirty: integer('dirty', { mode: 'boolean' }).notNull().default(true),
  },
  (table) => [
    // The two queries that actually run: "today's meals" and "what to push".
    index('meals_eaten_at_idx').on(table.eatenAt),
    index('meals_dirty_idx').on(table.dirty),
  ],
);

/**
 * Single-row sync bookkeeping.
 *
 * `cursor` is the server's own timestamp from the last successful sync, and is
 * the ONLY thing that may be sent as `since`. Writing this device's clock here
 * would silently start skipping server changes — see backend/app/routes/meals.py.
 */
export const syncState = sqliteTable('sync_state', {
  id: integer('id').primaryKey().default(1),
  cursor: text('cursor'),
  lastSyncedAt: text('last_synced_at'),
});

/** One-tap re-logging. Phase 0.5 — the reason this app survives past week one. */
export const favorites = sqliteTable('favorites', {
  id: text('id').primaryKey(),
  name: text('name').notNull(),
  brand: text('brand'),
  barcode: text('barcode'),
  servingG: real('serving_g'),
  calories: real('calories'),
  proteinG: real('protein_g'),
  carbsG: real('carbs_g'),
  fatG: real('fat_g'),
  fiberG: real('fiber_g'),
  sugarG: real('sugar_g'),
  sodiumMg: real('sodium_mg'),
  useCount: integer('use_count').notNull().default(0),
  lastUsedAt: text('last_used_at').default(sql`CURRENT_TIMESTAMP`),
});

export type Meal = typeof meals.$inferSelect;
export type NewMeal = typeof meals.$inferInsert;
export type Favorite = typeof favorites.$inferSelect;
