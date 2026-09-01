import axios, { type AxiosRequestConfig } from 'axios';
import { buildAuthEntryUrl, currentRouteTarget } from '../utils/authRedirect';

export interface AuthAwareRequestConfig extends AxiosRequestConfig {
  skipAuthRedirect?: boolean;
}

const client = axios.create({
  baseURL: '/api',
  timeout: 20000,
});

client.interceptors.request.use(
  (config) => {
    const token = sessionStorage.getItem('token');
    if (token) {
      config.headers['authorization'] = token;
    }
    return config;
  },
  (error) => {
    console.log(error);
    return Promise.reject(error);
  }
);

client.interceptors.response.use(
  (response) => {
    if (!response.data.success) {
      return Promise.reject(response.data.errorMsg || 'Request failed');
    }
    return response.data;
  },
  (error) => {
    console.log(error);
    if (error.response?.status === 401) {
      const requestConfig = error.config as AuthAwareRequestConfig | undefined;
      if (!requestConfig?.skipAuthRedirect) {
        setTimeout(() => {
          window.location.href = buildAuthEntryUrl('/login', currentRouteTarget(window.location));
        }, 200);
      }
      return Promise.reject('Please sign in first');
    }
    return Promise.reject(error.response?.data?.errorMsg || 'The server is unavailable');
  }
);

export default client;
