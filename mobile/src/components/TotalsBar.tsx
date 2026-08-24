import { StyleSheet, Text, View } from 'react-native';

import type { Meal } from '../db/schema';

const sum = (meals: Meal[], key: keyof Meal) =>
  Math.round(meals.reduce((total, meal) => total + (Number(meal[key]) || 0), 0));

export function TotalsBar({ meals }: { meals: Meal[] }) {
  const macros = [
    { label: 'kcal', value: sum(meals, 'calories') },
    { label: 'protein', value: `${sum(meals, 'proteinG')}g` },
    { label: 'carbs', value: `${sum(meals, 'carbsG')}g` },
    { label: 'fat', value: `${sum(meals, 'fatG')}g` },
  ];

  return (
    <View style={styles.bar}>
      {macros.map((macro) => (
        <View key={macro.label} style={styles.cell}>
          <Text style={styles.value}>{macro.value}</Text>
          <Text style={styles.label}>{macro.label}</Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row', paddingVertical: 14, paddingHorizontal: 8,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#d1d5db',
  },
  cell: { flex: 1, alignItems: 'center', gap: 2 },
  value: { fontSize: 18, fontWeight: '700', fontVariant: ['tabular-nums'] },
  label: { fontSize: 11, opacity: 0.55, textTransform: 'uppercase', letterSpacing: 0.5 },
});
