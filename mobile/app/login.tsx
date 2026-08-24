import { useRouter } from 'expo-router';
import { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { ApiError } from '../src/api/client';
import { useAuth } from '../src/lib/auth';

export default function LoginScreen() {
  const router = useRouter();
  const { signIn, register } = useAuth();

  const [mode, setMode] = useState<'signIn' | 'register'>('signIn');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await (mode === 'signIn' ? signIn : register)(email.trim(), password);
      router.back();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : 'Could not reach the server. Meals still save locally.',
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <KeyboardAvoidingView
      style={styles.fill}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={styles.content}>
        <Text style={styles.title}>
          {mode === 'signIn' ? 'Sign in' : 'Create account'}
        </Text>
        <Text style={styles.subtitle}>
          Only needed to sync across devices and back up your history. The app
          works fully offline without it.
        </Text>

        <TextInput
          style={styles.input}
          value={email}
          onChangeText={setEmail}
          placeholder="Email"
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="email-address"
          textContentType="emailAddress"
        />
        <TextInput
          style={styles.input}
          value={password}
          onChangeText={setPassword}
          placeholder="Password"
          secureTextEntry
          textContentType={mode === 'signIn' ? 'password' : 'newPassword'}
        />

        {error && <Text style={styles.error}>{error}</Text>}

        <Pressable style={styles.button} onPress={submit} disabled={busy}>
          {busy ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.buttonText}>
              {mode === 'signIn' ? 'Sign in' : 'Create account'}
            </Text>
          )}
        </Pressable>

        <Pressable
          onPress={() => setMode(mode === 'signIn' ? 'register' : 'signIn')}
        >
          <Text style={styles.switch}>
            {mode === 'signIn'
              ? 'Need an account? Create one'
              : 'Already have an account? Sign in'}
          </Text>
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  content: { flex: 1, justifyContent: 'center', padding: 28, gap: 14 },
  title: { fontSize: 26, fontWeight: '700' },
  subtitle: { fontSize: 14, opacity: 0.6, marginBottom: 6, lineHeight: 20 },
  input: {
    borderWidth: 1, borderColor: '#d1d5db', borderRadius: 10,
    paddingHorizontal: 14, paddingVertical: 13, fontSize: 16,
  },
  error: { color: '#dc2626', fontSize: 13 },
  button: {
    backgroundColor: '#2563eb', borderRadius: 12,
    paddingVertical: 15, alignItems: 'center', marginTop: 4,
  },
  buttonText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  switch: { textAlign: 'center', fontSize: 14, color: '#2563eb', paddingTop: 6 },
});
