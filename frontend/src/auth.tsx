import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { getCurrentUser, login as loginRequest, logout as logoutRequest, type AuthUser } from './api/client';

type AuthContextValue = {
  user: AuthUser | null;
  loading: boolean;
  error: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const handleUnauthorized = () => setUser(null);
    window.addEventListener('clippy:unauthorized', handleUnauthorized);
    getCurrentUser()
      .then((response) => setUser(response.user))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
    return () => window.removeEventListener('clippy:unauthorized', handleUnauthorized);
  }, []);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    loading,
    error,
    async login(username, password) {
      setError(null);
      try {
        const response = await loginRequest(username, password);
        setUser(response.user);
      } catch (cause) {
        const message = cause instanceof Error ? cause.message : 'Unable to sign in.';
        setError(message);
        throw cause;
      }
    },
    async logout() {
      await logoutRequest();
      setUser(null);
    },
  }), [error, loading, user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used inside AuthProvider');
  }
  return context;
}
