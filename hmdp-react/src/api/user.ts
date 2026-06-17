import client from './client';

export function getMe() {
  return client.get('/user/me');
}

export function getUserById(id: number | string) {
  return client.get(`/user/${id}`);
}

export function getUserInfo(id: number | string) {
  return client.get(`/user/info/${id}`);
}

export function sign() {
  return client.post('/user/sign');
}

export function signCount() {
  return client.get('/user/sign/count');
}
