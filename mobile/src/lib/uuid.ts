import * as Crypto from 'expo-crypto';

/**
 * Identity for a meal, minted on-device at creation time.
 *
 * Generated locally and not by the server, because a meal logged on a plane
 * needs an identity hours before any server hears about it. That identity is
 * what makes a retried push idempotent instead of a duplicate lunch.
 */
export function newClientId(): string {
  return Crypto.randomUUID();
}
