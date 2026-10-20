import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { authApi } from '../api/auth';
import { authStorage } from '../api/client';
import { User } from '../api/types';

const ALLOWED_TENANT_ROLES = ['tenant_owner', 'owner', 'tenant_admin', 'admin', 'tenant_user', 'user'];

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isTenantOwner: boolean;
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

          if (!ALLOWED_TENANT_ROLES.includes(role) || !me.tenant_id) {
            authStorage.clear();
            setUser(null);
          } else {
            setUser(me);
          }
        } catch {
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

      if (!ALLOWED_TENANT_ROLES.includes(role) || !res.user.tenant_id) {
        authStorage.clear();
        throw new Error(
          'هذه البوابة مخصصة لعملاء ومستأجري المنصة فقط. يتطلب تسجيل الدخول حساباً مرتبطاً بشركة أو مستأجر.'
        );
      }
      setUser(res.user);
    } finally {
      setIsLoading(false);
    }
  };

  const logout = useCallback(() => {
    authStorage.clear();
    setUser(null);
    window.location.href = '/login';
  }, []);

  const refreshUser = async () => {
    try {
      const me = await authApi.getMe();
      setUser(me);
    } catch (err) {
      logout();
    }
  };

  const isTenantOwner =
    user?.role === 'tenant_owner' || user?.role === 'owner' || user?.role === 'tenant_admin' || user?.role === 'admin';

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isTenantOwner,
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

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
