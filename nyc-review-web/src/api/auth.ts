import client, { type AuthAwareRequestConfig } from './client';

export interface PasswordCredentials {
  regionCode: string;
  phoneNumber: string;
  password: string;
}

export interface RegistrationDetails extends PasswordCredentials {
  nickName?: string;
}

export interface PasswordResetDetails extends Omit<PasswordCredentials, 'password'> {
  recoveryKey: string;
  newPassword: string;
}

export interface ChangePasswordDetails {
  currentPassword: string;
  newPassword: string;
}

export interface RecoveryKeyDetails {
  currentPassword: string;
  recoveryKey: string;
}

export function loginByPassword(credentials: PasswordCredentials) {
  const config: AuthAwareRequestConfig = { skipAuthRedirect: true };
  return client.post('/user/login', credentials, config);
}

export function register(details: RegistrationDetails) {
  const config: AuthAwareRequestConfig = { skipAuthRedirect: true };
  return client.post('/user/register', details, config);
}

export function logout() {
  return client.post('/user/logout');
}

export function getAccountSecurityStatus() {
  return client.get('/user/security/status');
}

export function setRecoveryKey(details: RecoveryKeyDetails) {
  return client.put('/user/security/recovery-key', details);
}

export function changePassword(details: ChangePasswordDetails) {
  return client.put('/user/security/password', details);
}

export function resetPassword(details: PasswordResetDetails) {
  const config: AuthAwareRequestConfig = { skipAuthRedirect: true };
  return client.post('/user/password/reset', details, config);
}
