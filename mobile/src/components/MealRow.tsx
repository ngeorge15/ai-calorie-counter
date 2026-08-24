import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { Meal } from '../db/schema';

/** Signals where a number came from, so a model guess never looks authoritative. */
const SOURCE_GLYPH: Record<Meal['source'], string> = {
  barcode: '▮▯▮',
  photo: '📷',
  manual: '✎',
  recent: '↻',
};

export function MealRow({ meal, onPress }: { meal: Meal; onPress: () => void }) {
  const time = new Date(meal.eatenAt).toLocaleTimeString([], {
    hour: 'numeric',
    minute: '2-digit',
  });

  return (
    <Pressable style={styles.row} onPress={onPress}>
      <View style={styles.main}>
        <Text style={styles.name} numberOfLines={1}>
          {meal.name ?? 'Untitled'}
        </Text>
        <Text style={styles.meta} numberOfLines={1}>
          {[meal.brand, time, meal.servingG ? `${Math.round(meal.servingG)}g` : null]
            .filter(Boolean)
            .join(' · ')}
        </Text>
      </View>
      <View style={styles.right}>
        <Text style={styles.calories}>
          {meal.calories == null ? '—' : Math.round(meal.calories)}
        </Text>
        <Text style={styles.source}>
          {SOURCE_GLYPH[meal.source]}
          {/* An unsynced row is normal offline, but worth being able to see. */}
          {meal.dirty ? ' ○' : ''}
        </Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row', alignItems: 'center', gap: 12,
    paddingHorizontal: 16, paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#e5e7eb',
  },
  main: { flex: 1, gap: 2 },
  name: { fontSize: 16, fontWeight: '500' },
  meta: { fontSize: 12, opacity: 0.55 },
  right: { alignItems: 'flex-end', gap: 2 },
  calories: { fontSize: 16, fontWeight: '600', fontVariant: ['tabular-nums'] },
  source: { fontSize: 10, opacity: 0.4 },
});
