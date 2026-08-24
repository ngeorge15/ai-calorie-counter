import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useMigrations } from 'drizzle-orm/expo-sqlite/migrator';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import migrations from '../drizzle/migrations';
import { db } from '../src/db/client';
import { AuthProvider } from '../src/lib/auth';

export default function RootLayout() {
  // Migrations run on-device at startup, bringing whatever schema version this
  // phone is on up to current WITHOUT touching existing rows. This is the
  // whole reason for Drizzle here: adding a column in month three must not
  // cost you months of logged meals.
  const { success, error } = useMigrations(db, migrations);

  if (error) {
    return (
      <View style={styles.center}>
        <Text style={styles.error}>Database migration failed</Text>
        <Text style={styles.detail}>{error.message}</Text>
      </View>
    );
  }

  if (!success) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  return (
    <SafeAreaProvider>
      <AuthProvider>
        <StatusBar style="auto" />
        <Stack screenOptions={{ headerShown: false }}>
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="login" options={{ presentation: 'modal' }} />
          <Stack.Screen
            name="meal/[clientId]"
            options={{ presentation: 'modal', headerShown: true, title: 'Edit meal' }}
          />
        </Stack>
      </AuthProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  error: { fontSize: 16, fontWeight: '600', marginBottom: 8 },
  detail: { fontSize: 13, opacity: 0.7, textAlign: 'center' },
});
