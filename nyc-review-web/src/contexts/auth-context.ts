import { createContext } from 'react';

export interface User {
  id: number;
  nickName: string;
  icon: string;
}

export interface UserInfo {
  introduce?: string;
  gender?: boolean;
  city?: string;
  birthday?: string;
}

export interface AuthState {
  token: string | null;
  user: User | null;
  isAuthenticated: boolean;
  login: (token: string) => void;
  logout: () => Promise<void>;
  setUser: (user: User | null) => void;
}

export const AuthContext = createContext<AuthState>({
  token: null,
  user: null,
  isAuthenticated: false,
  login: () => {},
  logout: async () => {},
  setUser: () => {},
});
