import client from './client';

export function sendCode(phone: string) {
  return client.post('/user/code', null, { params: { phone } });
}

export function loginByCode(phone: string, code: string) {
  return client.post('/user/login', { phone, code });
}

export function loginByPassword(phone: string, password: string) {
  return client.post('/user/login', { phone, password });
}

export function logout() {
  return client.post('/user/logout');
}
