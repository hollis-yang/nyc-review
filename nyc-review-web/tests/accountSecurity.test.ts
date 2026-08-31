import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { isStrongRecoveryKey, isStrongRegistrationPassword } from '../src/utils/passwordPolicy.ts';

test('password and recovery-key policies match the server contracts', () => {
  assert.equal(isStrongRegistrationPassword('Strong-password-2!'), true);
  assert.equal(isStrongRegistrationPassword('letters-only!'), false);
  assert.equal(isStrongRecoveryKey('Recovery-Key-123!'), true);
  assert.equal(isStrongRecoveryKey('Short-1!'), false);
});

test('forgot-password requires a recovery key and account security invalidates local session', () => {
  const forgot = readFileSync(new URL('../src/pages/ForgotPassword/index.tsx', import.meta.url), 'utf8');
  const security = readFileSync(new URL('../src/pages/AccountSecurity/index.tsx', import.meta.url), 'utf8');

  assert.match(forgot, /recoveryKey/);
  assert.match(forgot, /resetPassword/);
  assert.match(security, /currentPassword/);
  assert.match(security, /sessionStorage\.removeItem\('token'\)/);
});
