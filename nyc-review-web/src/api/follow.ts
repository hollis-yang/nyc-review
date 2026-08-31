import client from './client';

export function isFollowed(userId: number | string) {
  return client.get(`/follow/or/not/${userId}`);
}

export function follow(userId: number | string, followBool: boolean) {
  return client.put(`/follow/${userId}/${followBool}`);
}

export function getCommonFollows(userId: number | string) {
  return client.get(`/follow/common/${userId}`);
}

export function getFollowers() {
  return client.get('/follow/followers');
}
