import axios, { type AxiosRequestConfig } from 'axios';

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
      return Promise.reject(response.data.errorMsg || '请求失败');
    }
    return response.data;
  },
  (error) => {
    console.log(error);
    if (error.response?.status === 401) {
      const requestConfig = error.config as AuthAwareRequestConfig | undefined;
      if (!requestConfig?.skipAuthRedirect) {
        setTimeout(() => {
          window.location.href = '/login';
        }, 200);
      }
      return Promise.reject('请先登录');
    }
    return Promise.reject(error.response?.data?.errorMsg || '服务器异常');
  }
);

export default client;
