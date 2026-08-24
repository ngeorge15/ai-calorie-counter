import { eq } from 'drizzle-orm';

import { apiFetch } from '../api/client';
import type { MealPayload, SyncResponse } from '../api/types';
import { db } from '../db/client';
import { dirtyMeals, markClean, toPayload, upsertFromServer } from '../db/meals';
import { syncState } from '../db/schema';

/**
 * One sync round trip: push local edits, pull everything since the cursor.
 *
 * The client half of the protocol in backend/app/routes/meals.py. Two rules
 * hold this together and both fail silently if broken:
 *
 *  1. The cursor sent as `since` is ALWAYS the server's own `server_time` from
 *     the previous sync. This device's clock never touches it. A phone running
 *     fast would otherwise stop seeing server changes, permanently.
 *
 *  2. Everything applied from the server is an upsert keyed on client_id, so
 *     receiving the same row twice is free. That is what lets the cursor
 *     overlap rather than gap.
 */

const SYNC_ROW_ID = 1;

async function readCursor(): Promise<string | null> {
  const [row] = await db
    .select()
    .from(syncState)
    .where(eq(syncState.id, SYNC_ROW_ID))
    .limit(1);
  return row?.cursor ?? null;
}

async function writeCursor(cursor: string): Promise<void> {
  await db
    .insert(syncState)
    .values({
      id: SYNC_ROW_ID,
      cursor,
      lastSyncedAt: new Date().toISOString(),
    })
    .onConflictDoUpdate({
      target: syncState.id,
      set: { cursor, lastSyncedAt: new Date().toISOString() },
    });
}

export type SyncResult = {
  pushed: number;
  pulled: number;
  conflicts: number;
};

export async function sync(): Promise<SyncResult> {
  const cursor = await readCursor();
  const pending = await dirtyMeals();

  const response = await apiFetch<SyncResponse>('/api/meals/sync', {
    method: 'POST',
    body: {
      since: cursor,
      changes: pending.map(toPayload),
    },
  });

  // Order matters below. Conflicts are applied before the cursor advances so
  // that a crash mid-sync re-runs the whole exchange rather than skipping it.

  // The server accepted these; they no longer need pushing.
  await markClean(response.applied);

  // The server held a newer edit than ours. It wins — converge on its copy
  // rather than leaving the two permanently disagreeing.
  for (const conflict of response.conflicts) {
    await upsertFromServer(conflict);
  }

  // Changes from elsewhere (another device, or our own pushes echoed back).
  for (const change of response.changes) {
    await upsertFromServer(change);
  }

  await writeCursor(response.server_time);

  return {
    pushed: response.applied.length,
    pulled: response.changes.length,
    conflicts: response.conflicts.length,
  };
}

/** Never let a failed sync surface as a crash — offline is the normal case. */
export async function trySync(): Promise<SyncResult | null> {
  try {
    return await sync();
  } catch {
    return null;
  }
}

export type { MealPayload };
