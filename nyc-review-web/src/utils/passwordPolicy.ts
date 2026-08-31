const MIN_CHARACTERS = 8;
const MAX_CHARACTERS = 64;
const BCRYPT_MAX_BYTES = 72;

export function isStrongRegistrationPassword(password: string): boolean {
  const characters = Array.from(password).length;
  const bytes = new TextEncoder().encode(password).length;
  return characters >= MIN_CHARACTERS
    && characters <= MAX_CHARACTERS
    && bytes <= BCRYPT_MAX_BYTES
    && /\p{L}/u.test(password)
    && /\p{N}/u.test(password)
    && /[^\p{L}\p{N}\s]/u.test(password);
}

export function isStrongRecoveryKey(recoveryKey: string): boolean {
  const characters = Array.from(recoveryKey).length;
  const bytes = new TextEncoder().encode(recoveryKey).length;
  return characters >= 12
    && characters <= 64
    && bytes <= 72
    && /\p{L}/u.test(recoveryKey)
    && /\p{N}/u.test(recoveryKey)
    && /[^\p{L}\p{N}\s]/u.test(recoveryKey);
}
