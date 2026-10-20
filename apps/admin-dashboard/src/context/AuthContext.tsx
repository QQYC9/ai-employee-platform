import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { authApi } from '../api/auth';
import { authStorage } from '../api/client';
import { User } from '../api/types';

const SUPER_ADMIN_ROLES = ['platform_admin', 'superadmin'];

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isSuperAdmin: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  useEffect(() => {
    async function initAuth() {
      if (authStorage.getToken()) {
        try {
          const me = await authApi.getMe();
          const role = (me.role || '').trim().toLowerCase();
          if (!SUPER_ADMIN_ROLES.includes(role)) {
            // Non-admin user should not access this dashboard
            authStorage.clear();
            setUser(null);
          } else {
            setUser(me);
          }
        } catch {
          // Token invalid — always clear to prevent stale access
          authStorage.clear();
          setUser(null);
        }
      } else {
        setUser(null);
      }
      setIsLoading(false);
    }
    initAuth();
  }, []);

  const login = async (email: string, password: string) => {
    setIsLoading(true);
    try {
      const res = await authApi.login(email, password);
      const role = (res.user.role || '').trim().toLowerCase();
      if (!SUPER_ADMIN_ROLES.includes(role)) {
        authStorage.clear();
        throw new Error('ليس لديك صلاحيات الإدارة العليا (Super Admin). يُسمح فقط لدور platform_admin بالدخول.');
      }
      setUser(res.user);
    } finally {
      setIsLoading(false);
    }
  };

  const logout = () => {
    setUser(null);
    authApi.logout();
  };

  const refreshUser = useCallback(async () => {
    try {
      const me = await authApi.getMe();
      const role = (me.role || '').trim().toLowerCase();
      if (!SUPER_ADMIN_ROLES.includes(role)) {
        authStorage.clear();
        setUser(null);
        return;
      }
      setUser(me);
    } catch (err) {
      console.error('Failed to refresh user:', err);
    }
  }, []);

  const isSuperAdmin = !!user && SUPER_ADMIN_ROLES.includes((user.role || '').trim().toLowerCase());

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user && isSuperAdmin,
        isSuperAdmin,
        isLoading,
        login,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
