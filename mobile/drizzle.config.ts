import type { Config } from 'drizzle-kit';

export default {
  schema: './src/db/schema.ts',
  out: './drizzle',
  dialect: 'sqlite',
  // Emits migrations bundled into the app rather than run against a live DB —
  // they execute on-device at startup against whatever version that phone is on.
  driver: 'expo',
} satisfies Config;
