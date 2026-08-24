import { drizzle } from 'drizzle-orm/expo-sqlite';
import { openDatabaseSync } from 'expo-sqlite';

import * as schema from './schema';

/**
 * The on-device meal log.
 *
 * The filename is stable and the app's bundle identifier is fixed in app.json,
 * which together are what let this database survive SideStore's weekly
 * re-signing. iOS keys app data to the bundle id — change it and the next
 * install is a different app with an empty history.
 */
export const sqlite = openDatabaseSync('calorie-counter.db', {
  enableChangeListener: true,
});

export const db = drizzle(sqlite, { schema });
export { schema };
