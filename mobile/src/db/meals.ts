import { and, desc, eq, like, sql } from 'drizzle-orm';

import type { MealPayload } from '../api/types';
import { newClientId } from '../lib/uuid';
import { db } from './client';
import { type Meal, type NewMeal, meals } from './schema';

/** Drizzle is camelCase, the wire is snake_case. Convert at exactly one place. */
export function toPayload(meal: Meal): MealPayload {
  return {
    client_id: meal.clientId,
    name: meal.name,
    brand: meal.brand,
    barcode: meal.barcode,
    serving_g: meal.servingG,
    calories: meal.calories,
    protein_g: meal.proteinG,
    carbs_g: meal.carbsG,
    fat_g: meal.fatG,
    fiber_g: meal.fiberG,
    sugar_g: meal.sugarG,
    sodium_mg: meal.sodiumMg,
    meal_type: meal.mealType,
    eaten_at: meal.eatenAt,
    source: meal.source,
    model_confidence: meal.modelConfidence,
    user_edited: meal.userEdited,
    deleted: meal.deleted,
    updated_at: meal.updatedAt,
  };
}

export function fromPayload(payload: MealPayload): NewMeal {
  return {
    clientId: payload.client_id,
    name: payload.name ?? null,
    brand: payload.brand ?? null,
    barcode: payload.barcode ?? null,
    servingG: payload.serving_g ?? null,
    calories: payload.calories ?? null,
    proteinG: payload.protein_g ?? null,
    carbsG: payload.carbs_g ?? null,
    fatG: payload.fat_g ?? null,
    fiberG: payload.fiber_g ?? null,
    sugarG: payload.sugar_g ?? null,
    sodiumMg: payload.sodium_mg ?? null,
    mealType: payload.meal_type ?? null,
    eatenAt: payload.eaten_at,
    source: payload.source,
    modelConfidence: payload.model_confidence ?? null,
    userEdited: payload.user_edited,
    deleted: payload.deleted,
    updatedAt: payload.updated_at,
    // Arrived FROM the server, so by definition it needs no push back.
    dirty: false,
  };
}

export async function createMeal(
  input: Omit<NewMeal, 'clientId' | 'updatedAt' | 'dirty'>,
): Promise<Meal> {
  const row: NewMeal = {
    ...input,
    clientId: newClientId(),
    updatedAt: new Date().toISOString(),
    dirty: true,
  };
  const [created] = await db.insert(meals).values(row).returning();
  return created;
}

export async function updateMeal(
  clientId: string,
  patch: Partial<NewMeal>,
): Promise<void> {
  await db
    .update(meals)
    .set({
      ...patch,
      // Any local edit re-stamps the edit clock and re-dirties the row, or the
      // change would never be pushed.
      updatedAt: new Date().toISOString(),
      dirty: true,
    })
    .where(eq(meals.clientId, clientId));
}

/** Tombstone, never a hard delete — a removed row can't propagate to the server. */
export async function deleteMeal(clientId: string): Promise<void> {
  await updateMeal(clientId, { deleted: true });
}

/** `day` is YYYY-MM-DD in the device's local time. */
export async function listMealsForDay(day: string): Promise<Meal[]> {
  return db
    .select()
    .from(meals)
    .where(and(eq(meals.deleted, false), like(meals.eatenAt, `${day}%`)))
    .orderBy(desc(meals.eatenAt));
}

export async function getMeal(clientId: string): Promise<Meal | undefined> {
  const [row] = await db
    .select()
    .from(meals)
    .where(eq(meals.clientId, clientId))
    .limit(1);
  return row;
}

/** Everything with unpushed edits — the push half of a sync. */
export async function dirtyMeals(): Promise<Meal[]> {
  return db.select().from(meals).where(eq(meals.dirty, true));
}

export async function markClean(clientIds: string[]): Promise<void> {
  if (clientIds.length === 0) return;
  await db
    .update(meals)
    .set({ dirty: false })
    .where(sql`${meals.clientId} IN ${clientIds}`);
}

/**
 * Apply a server-authored row, overwriting whatever is local.
 *
 * Used for both pulled changes and conflict resolutions. Safe to call twice
 * with the same row — which is exactly why the sync cursor is allowed to
 * overlap rather than risk a gap.
 */
export async function upsertFromServer(payload: MealPayload): Promise<void> {
  const row = fromPayload(payload);
  await db
    .insert(meals)
    .values(row)
    .onConflictDoUpdate({ target: meals.clientId, set: row });
}

/** Frequently-eaten foods, for one-tap re-logging. Phase 0.5. */
export async function recentDistinctMeals(limit = 20) {
  return db
    .select({
      name: meals.name,
      brand: meals.brand,
      barcode: meals.barcode,
      servingG: meals.servingG,
      calories: meals.calories,
      proteinG: meals.proteinG,
      carbsG: meals.carbsG,
      fatG: meals.fatG,
      uses: sql<number>`count(*)`.as('uses'),
      lastEaten: sql<string>`max(${meals.eatenAt})`.as('last_eaten'),
    })
    .from(meals)
    .where(and(eq(meals.deleted, false), sql`${meals.name} is not null`))
    .groupBy(meals.name, meals.brand)
    .orderBy(desc(sql`uses`), desc(sql`last_eaten`))
    .limit(limit);
}
