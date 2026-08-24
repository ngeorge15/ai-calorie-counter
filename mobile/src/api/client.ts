import * as SecureStore from 'expo-secure-store';

const TOKEN_KEY = 'auth_token';

/**
 * Base URL for the Flask backend.
 *
 * In development this points at the Tailscale hostname (https://<box>.ts.net),
 * which gives a real TLS cert — iOS App Transport Security blocks plain HTTP,
 * and a tailnet name stays stable across wifi, cellular, and coffee shops.
 * In production it's the Render deployment.
 */
export const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_BASE_URL ?? 'http://localhost:5000';

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
  }
}

/** Token lives in the Keychain, not MMKV — it never expires by design. */
export async function getToken(): Promise<string | null> {
  return SecureStore.getItemAsync(TOKEN_KEY);
}

export async function setToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(TOKEN_KEY, token);
}

export async function clearToken(): Promise<void> {
  await SecureStore.deleteItemAsync(TOKEN_KEY);
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'DELETE';
  body?: unknown;
  /** Render's free tier sleeps; a cold start can take ~30s on first hit. */
  timeoutMs?: number;
};

export async function apiFetch<T>(
  path: string,
  { method = 'GET', body, timeoutMs = 15_000 }: RequestOptions = {},
): Promise<T> {
  const token = await getToken();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });

    const text = await response.text();
    const parsed = text ? JSON.parse(text) : null;

    if (!response.ok) {
      throw new ApiError(
        response.status,
        parsed?.error ?? `Request failed (${response.status})`,
        parsed?.detail,
      );
    }
    return parsed as T;
  } finally {
    clearTimeout(timer);
  }
}

/** Wake a sleeping Render dyno before a sync, rather than during one. */
export async function ping(): Promise<boolean> {
  try {
    await apiFetch('/api/health', { timeoutMs: 30_000 });
    return true;
  } catch {
    return false;
  }
}
