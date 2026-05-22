import { createContext, useState, useCallback, type ReactNode } from 'react';
import { logout as logoutApi } from '../api/auth';

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

interface AuthState {
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

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(
    () => sessionStorage.getItem('token')
  );
  const [user, setUser] = useState<User | null>(null);

  const login = useCallback((newToken: string) => {
    sessionStorage.setItem('token', newToken);
    setToken(newToken);
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutApi();
    } catch {
      // logout API is a stub, ignore errors
    }
    sessionStorage.removeItem('token');
    sessionStorage.removeItem('userInfo');
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        token,
        user,
        isAuthenticated: !!token,
        login,
        logout,
        setUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
