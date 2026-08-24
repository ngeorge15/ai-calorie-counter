import { desc, eq, sql } from 'drizzle-orm';
import { useLiveQuery } from 'drizzle-orm/expo-sqlite';
import { SectionList, StyleSheet, Text, View } from 'react-native';

import { db } from '../../src/db/client';
import { meals } from '../../src/db/schema';

export default function HistoryScreen() {
  // Daily rollups, computed in SQLite rather than in JS — the phone should not
  // load a year of rows to show four numbers a day.
  const { data } = useLiveQuery(
    db
      .select({
        day: sql<string>`substr(${meals.eatenAt}, 1, 10)`.as('day'),
        calories: sql<number>`coalesce(sum(${meals.calories}), 0)`.as('calories'),
        protein: sql<number>`coalesce(sum(${meals.proteinG}), 0)`.as('protein'),
        carbs: sql<number>`coalesce(sum(${meals.carbsG}), 0)`.as('carbs'),
        fat: sql<number>`coalesce(sum(${meals.fatG}), 0)`.as('fat'),
        count: sql<number>`count(*)`.as('count'),
      })
      .from(meals)
      .where(eq(meals.deleted, false))
      .groupBy(sql`day`)
      .orderBy(desc(sql`day`))
      .limit(90),
  );

  const days = data ?? [];

  if (days.length === 0) {
    return (
      <View style={styles.center}>
        <Text style={styles.emptyTitle}>No history yet</Text>
        <Text style={styles.emptyBody}>Logged days will show up here.</Text>
      </View>
    );
  }

  return (
    <SectionList
      sections={[{ title: 'Last 90 days', data: days }]}
      keyExtractor={(item) => item.day}
      renderSectionHeader={({ section }) => (
        <Text style={styles.sectionHeader}>{section.title}</Text>
      )}
      renderItem={({ item }) => (
        <View style={styles.row}>
          <View style={styles.dayCell}>
            <Text style={styles.day}>
              {new Date(`${item.day}T12:00:00`).toLocaleDateString([], {
                weekday: 'short', month: 'short', day: 'numeric',
              })}
            </Text>
            <Text style={styles.count}>
              {item.count} {item.count === 1 ? 'item' : 'items'}
            </Text>
          </View>
          <View style={styles.macros}>
            <Text style={styles.calories}>{Math.round(item.calories)}</Text>
            <Text style={styles.macroDetail}>
              {Math.round(item.protein)}p · {Math.round(item.carbs)}c · {Math.round(item.fat)}f
            </Text>
          </View>
        </View>
      )}
    />
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 6 },
  emptyTitle: { fontSize: 17, fontWeight: '600' },
  emptyBody: { fontSize: 14, opacity: 0.6 },
  sectionHeader: {
    paddingHorizontal: 16, paddingVertical: 8, fontSize: 12,
    textTransform: 'uppercase', letterSpacing: 0.5, opacity: 0.5,
    backgroundColor: '#f9fafb',
  },
  row: {
    flexDirection: 'row', alignItems: 'center',
    paddingHorizontal: 16, paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#e5e7eb',
  },
  dayCell: { flex: 1, gap: 2 },
  day: { fontSize: 15, fontWeight: '500' },
  count: { fontSize: 12, opacity: 0.5 },
  macros: { alignItems: 'flex-end', gap: 2 },
  calories: { fontSize: 17, fontWeight: '600', fontVariant: ['tabular-nums'] },
  macroDetail: { fontSize: 12, opacity: 0.55, fontVariant: ['tabular-nums'] },
});
