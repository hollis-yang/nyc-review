import { useState, useCallback, type ReactNode } from 'react';
import { logout as logoutApi } from '../api/auth';
import { AuthContext, type User } from './auth-context';

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
