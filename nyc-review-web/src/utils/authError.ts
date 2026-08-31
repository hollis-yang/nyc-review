import type { TFunction } from 'i18next';

const AUTH_ERROR_KEYS: Readonly<Record<string, string>> = {
  'Phone number is required': 'auth.errors.phoneRequired',
  'Invalid phone number': 'auth.errors.invalidPhone',
  'A valid phone region is required': 'auth.errors.invalidRegion',
  'Password is required': 'auth.errors.passwordRequired',
  'Password must be 8-64 characters and include a letter, a number, and a special character': 'auth.errors.passwordPolicy',
  'Invalid phone number or password': 'auth.errors.invalidCredentials',
  'Too many login attempts. Please try again later': 'auth.errors.loginLimited',
  'Too many registration attempts. Please try again later': 'auth.errors.registrationLimited',
  'This phone number is already registered': 'auth.errors.alreadyRegistered',
  'Nickname cannot exceed 32 characters': 'auth.errors.nicknameTooLong',
  'Current password is incorrect': 'auth.errors.currentPasswordIncorrect',
  'New password must be different from the current password': 'auth.errors.passwordUnchanged',
  'Recovery key must be 12-64 characters and include a letter, a number, and a special character': 'auth.errors.recoveryKeyPolicy',
  'Unable to reset password with those details': 'auth.errors.resetRejected',
  'Too many password reset attempts. Please try again later': 'auth.errors.resetLimited',
};

export function localizedAuthError(error: unknown, t: TFunction): string {
  const message = String(error);
  const translationKey = AUTH_ERROR_KEYS[message];
  return translationKey ? t(translationKey) : message;
}
