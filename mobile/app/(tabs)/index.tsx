import { and, desc, eq, like } from 'drizzle-orm';
import { useLiveQuery } from 'drizzle-orm/expo-sqlite';
import { useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { db } from '../../src/db/client';
import { meals } from '../../src/db/schema';
import { trySync } from '../../src/sync/engine';
import { MealRow } from '../../src/components/MealRow';
import { TotalsBar } from '../../src/components/TotalsBar';

function localDay(date = new Date()): string {
  // Local, not UTC: a meal at 11pm belongs to today from the user's point of
  // view, and toISOString() would file it under tomorrow.
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
}

export default function TodayScreen() {
  const router = useRouter();
  const [syncing, setSyncing] = useState(false);
  const today = localDay();

  // Live query: re-runs whenever the meals table changes, so logging a scan
  // updates this list with no manual refresh.
  const { data } = useLiveQuery(
    db
      .select()
      .from(meals)
      .where(and(eq(meals.deleted, false), like(meals.eatenAt, `${today}%`)))
      .orderBy(desc(meals.eatenAt)),
  );

  const rows = data ?? [];

  const onRefresh = useCallback(async () => {
    setSyncing(true);
    await trySync();
    setSyncing(false);
  }, []);

  return (
    <View style={styles.fill}>
      <TotalsBar meals={rows} />
      <FlatList
        data={rows}
        keyExtractor={(item) => item.clientId}
        contentContainerStyle={rows.length === 0 && styles.emptyContainer}
        refreshControl={
          <RefreshControl refreshing={syncing} onRefresh={onRefresh} />
        }
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text style={styles.emptyTitle}>Nothing logged yet</Text>
            <Text style={styles.emptyBody}>
              Scan a barcode, or add something manually.
            </Text>
          </View>
        }
        renderItem={({ item }) => (
          <MealRow
            meal={item}
            onPress={() =>
              router.push({
                pathname: '/meal/[clientId]',
                params: { clientId: item.clientId },
              })
            }
          />
        )}
      />
      <Pressable
        style={styles.fab}
        onPress={() =>
          router.push({
            pathname: '/meal/[clientId]',
            params: { clientId: 'new' },
          })
        }
      >
        <Text style={styles.fabText}>+</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  emptyContainer: { flexGrow: 1, justifyContent: 'center' },
  empty: { alignItems: 'center', padding: 32, gap: 6 },
  emptyTitle: { fontSize: 17, fontWeight: '600' },
  emptyBody: { fontSize: 14, opacity: 0.6, textAlign: 'center' },
  fab: {
    position: 'absolute', right: 20, bottom: 28, width: 56, height: 56,
    borderRadius: 28, backgroundColor: '#2563eb',
    alignItems: 'center', justifyContent: 'center',
    shadowColor: '#000', shadowOpacity: 0.25, shadowRadius: 8,
    shadowOffset: { width: 0, height: 4 }, elevation: 4,
  },
  fabText: { color: '#fff', fontSize: 30, lineHeight: 34, fontWeight: '300' },
});
