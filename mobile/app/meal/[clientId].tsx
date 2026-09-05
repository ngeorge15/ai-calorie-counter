import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { createMeal, deleteMeal, getMeal, updateMeal } from '../../src/db/meals';
import type { Meal } from '../../src/db/schema';
import { trySync } from '../../src/sync/engine';

type Draft = {
  name: string;
  brand: string;
  servingG: string;
  calories: string;
  proteinG: string;
  carbsG: string;
  fatG: string;
  mealType: Meal['mealType'];
};

const EMPTY: Draft = {
  name: '', brand: '', servingG: '', calories: '',
  proteinG: '', carbsG: '', fatG: '', mealType: 'snack',
};

const MEAL_TYPES: NonNullable<Meal['mealType']>[] = [
  'breakfast', 'lunch', 'dinner', 'snack',
];

const num = (value: string): number | null => {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : null;
};

export default function MealEditScreen() {
  const router = useRouter();
  const { clientId, barcode, name, source, modelConfidence } =
    useLocalSearchParams<{
      clientId: string;
      barcode?: string;
      /** Prefill for a new meal, e.g. a photo classifier's `query` string. */
      name?: string;
      /** Origin of this new meal. Defaults to 'manual' — see MealPayload. */
      source?: 'barcode' | 'photo' | 'manual' | 'recent';
      /** Model's own confidence, carried through from the photo flow. */
      modelConfidence?: string;
    }>();
  const isNew = clientId === 'new';

  const [draft, setDraft] = useState<Draft>(() =>
    isNew && name ? { ...EMPTY, name } : EMPTY,
  );
  const [existing, setExisting] = useState<Meal | null>(null);
  /** Tracks whether the human changed any generated number. */
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    if (isNew) return;
    void getMeal(clientId).then((meal) => {
      if (!meal) return;
      setExisting(meal);
      setDraft({
        name: meal.name ?? '',
        brand: meal.brand ?? '',
        servingG: meal.servingG?.toString() ?? '',
        calories: meal.calories?.toString() ?? '',
        proteinG: meal.proteinG?.toString() ?? '',
        carbsG: meal.carbsG?.toString() ?? '',
        fatG: meal.fatG?.toString() ?? '',
        mealType: meal.mealType ?? 'snack',
      });
    });
  }, [clientId, isNew]);

  const set = (key: keyof Draft) => (value: string) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setTouched(true);
  };

  async function onSave() {
    const fields = {
      name: draft.name.trim() || null,
      brand: draft.brand.trim() || null,
      servingG: num(draft.servingG),
      calories: num(draft.calories),
      proteinG: num(draft.proteinG),
      carbsG: num(draft.carbsG),
      fatG: num(draft.fatG),
      mealType: draft.mealType,
    };

    if (isNew) {
      await createMeal({
        ...fields,
        barcode: barcode ?? null,
        eatenAt: new Date().toISOString(),
        source: source ?? 'manual',
        // Only set when a classifier produced this row. The confidence is
        // the model's own, on the query it suggested — not a claim about the
        // nutrition numbers below, which the user always typed in themselves.
        modelConfidence: modelConfidence ? Number.parseFloat(modelConfidence) : null,
        userEdited: false,
        deleted: false,
      });
    } else {
      await updateMeal(clientId, {
        ...fields,
        // Only flip this when a human actually changed something. The
        // /benchmarks work depends on distinguishing "model was right" from
        // "user never looked" — see benchmarks/portion_accuracy.md.
        userEdited: existing?.userEdited || touched,
      });
    }

    router.back();
    // Fire and forget: saving must never block on the network.
    void trySync();
  }

  async function onDelete() {
    if (!isNew) await deleteMeal(clientId);
    router.back();
    void trySync();
  }

  return (
    <KeyboardAvoidingView
      style={styles.fill}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Field label="Name" value={draft.name} onChange={set('name')} autoFocus={isNew} />
        <Field label="Brand" value={draft.brand} onChange={set('brand')} />

        <View style={styles.chips}>
          {MEAL_TYPES.map((type) => (
            <Pressable
              key={type}
              onPress={() => setDraft((d) => ({ ...d, mealType: type }))}
              style={[styles.chip, draft.mealType === type && styles.chipActive]}
            >
              <Text style={[styles.chipText, draft.mealType === type && styles.chipTextActive]}>
                {type}
              </Text>
            </Pressable>
          ))}
        </View>

        <Field label="Serving (g)" value={draft.servingG} onChange={set('servingG')} numeric />
        <Field label="Calories" value={draft.calories} onChange={set('calories')} numeric />

        <View style={styles.macroRow}>
          <Field label="Protein" value={draft.proteinG} onChange={set('proteinG')} numeric compact />
          <Field label="Carbs" value={draft.carbsG} onChange={set('carbsG')} numeric compact />
          <Field label="Fat" value={draft.fatG} onChange={set('fatG')} numeric compact />
        </View>

        <Pressable style={styles.save} onPress={onSave}>
          <Text style={styles.saveText}>{isNew ? 'Log meal' : 'Save'}</Text>
        </Pressable>

        {!isNew && (
          <Pressable style={styles.delete} onPress={onDelete}>
            <Text style={styles.deleteText}>Delete</Text>
          </Pressable>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function Field({
  label, value, onChange, numeric, compact, autoFocus,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  numeric?: boolean;
  compact?: boolean;
  autoFocus?: boolean;
}) {
  return (
    <View style={[styles.field, compact && styles.fieldCompact]}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        style={styles.input}
        value={value}
        onChangeText={onChange}
        autoFocus={autoFocus}
        keyboardType={numeric ? 'decimal-pad' : 'default'}
        placeholder={numeric ? '—' : ''}
        placeholderTextColor="#9ca3af"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  content: { padding: 20, gap: 14 },
  field: { gap: 6 },
  fieldCompact: { flex: 1 },
  label: { fontSize: 12, opacity: 0.6, textTransform: 'uppercase', letterSpacing: 0.5 },
  input: {
    borderWidth: 1, borderColor: '#d1d5db', borderRadius: 10,
    paddingHorizontal: 12, paddingVertical: 11, fontSize: 16,
  },
  macroRow: { flexDirection: 'row', gap: 10 },
  chips: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  chip: {
    paddingHorizontal: 14, paddingVertical: 7, borderRadius: 16,
    borderWidth: 1, borderColor: '#d1d5db',
  },
  chipActive: { backgroundColor: '#2563eb', borderColor: '#2563eb' },
  chipText: { fontSize: 13, textTransform: 'capitalize' },
  chipTextActive: { color: '#fff', fontWeight: '600' },
  save: {
    marginTop: 8, backgroundColor: '#2563eb', borderRadius: 12,
    paddingVertical: 15, alignItems: 'center',
  },
  saveText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  delete: { paddingVertical: 12, alignItems: 'center' },
  deleteText: { color: '#dc2626', fontSize: 15 },
});
