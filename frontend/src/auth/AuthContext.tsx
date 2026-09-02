import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, setCsrfToken } from '../lib/api';
import type { CurrentUser } from '../types';

interface AuthContextValue {
  user: CurrentUser | null;
  loading: boolean;
  login: (email: string, password: string, remember: boolean) => Promise<void>;
  changePassword: (currentPassword: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const session = await api<{ authenticated: boolean; csrfToken: string; user?: CurrentUser }>('/api/v1/auth/session/');
    setCsrfToken(session.csrfToken);
    setUser(session.authenticated ? (session.user ?? null) : null);
  }, []);

  useEffect(() => {
    let active = true;
    api<{ authenticated: boolean; csrfToken: string; user?: CurrentUser }>('/api/v1/auth/session/')
      .then((session) => {
        if (!active) return;
        setCsrfToken(session.csrfToken);
        setUser(session.authenticated ? (session.user ?? null) : null);
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const login = useCallback(async (email: string, password: string, remember: boolean) => {
    const result = await api<{ user: CurrentUser; csrfToken: string }>('/api/v1/auth/login/', {
      method: 'POST',
      body: JSON.stringify({ email, password, remember }),
    });
    setCsrfToken(result.csrfToken);
    setUser(result.user);
  }, []);

  const logout = useCallback(async () => {
    await api('/api/v1/auth/logout/', { method: 'POST' });
    setUser(null);
    await refresh();
  }, [refresh]);

  const changePassword = useCallback(async (currentPassword: string, password: string) => {
    const result = await api<{ user: CurrentUser; csrfToken: string }>('/api/v1/auth/password/change/', {
      method: 'POST',
      body: JSON.stringify({ current_password: currentPassword, password }),
    });
    setCsrfToken(result.csrfToken);
    setUser(result.user);
  }, []);

  const value = useMemo(() => ({ user, loading, login, changePassword, logout, refresh }), [user, loading, login, changePassword, logout, refresh]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside AuthProvider');
  return context;
}
