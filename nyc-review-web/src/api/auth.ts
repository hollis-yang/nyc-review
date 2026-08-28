import client, { type AuthAwareRequestConfig } from './client';

export interface PasswordCredentials {
  regionCode: string;
  phoneNumber: string;
  password: string;
}

export interface RegistrationDetails extends PasswordCredentials {
  nickName?: string;
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
