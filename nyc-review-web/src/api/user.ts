import client, { type AuthAwareRequestConfig } from './client';

export function getMe() {
  return client.get('/user/me');
}

export function getMeOptional() {
  const config: AuthAwareRequestConfig = { skipAuthRedirect: true };
  return client.get('/user/me', config);
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

export interface SignCalendarData {
  year: number;
  month: number;
  checkedDays: number[];
  currentStreak: number;
  signedToday: boolean;
  today: string;
}

export function getSignCalendar(year?: number, month?: number) {
  return client.get<SignCalendarData>('/user/sign/calendar', {
    params: year != null && month != null ? { year, month } : undefined,
  });
}

export function updateUser(data: { nickName?: string; icon?: string }) {
  return client.put('/user/me', data);
}

export function updateUserInfo(data: {
  introduce?: string;
  gender?: boolean;
  city?: string;
  birthday?: string;
}) {
  return client.put('/user/info', data);
}
