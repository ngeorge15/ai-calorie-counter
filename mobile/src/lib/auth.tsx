import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { apiFetch, clearToken, getToken, setToken } from '../api/client';

type AuthResponse = { token: string; user_id: string };

type AuthContextValue = {
  token: string | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTokenState] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Restore from the Keychain on cold start so a re-signed sideload doesn't
    // force a fresh login every week.
    getToken()
      .then(setTokenState)
      .finally(() => setLoading(false));
  }, []);

  const authenticate = useCallback(
    async (path: string, email: string, password: string) => {
      const response = await apiFetch<AuthResponse>(path, {
        method: 'POST',
        body: { email, password },
      });
      await setToken(response.token);
      setTokenState(response.token);
    },
    [],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      token,
      loading,
      signIn: (email, password) =>
        authenticate('/api/auth/login', email, password),
      register: (email, password) =>
        authenticate('/api/auth/register', email, password),
      signOut: async () => {
        await clearToken();
        setTokenState(null);
      },
    }),
    [token, loading, authenticate],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside AuthProvider');
  return context;
}
