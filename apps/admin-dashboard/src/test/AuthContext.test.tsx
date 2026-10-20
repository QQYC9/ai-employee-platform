import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { AuthProvider, useAuth } from '../context/AuthContext';
import { authStorage } from '../api/client';
import { authApi } from '../api/auth';

const TestConsumer: React.FC = () => {
  const { user, isAuthenticated, isSuperAdmin, isLoading } = useAuth();
  if (isLoading) return <div>Loading...</div>;
  return (
    <div>
      <div data-testid="auth-status">{isAuthenticated ? 'authenticated' : 'unauthenticated'}</div>
      <div data-testid="superadmin-status">{isSuperAdmin ? 'yes' : 'no'}</div>
      <div data-testid="user-email">{user?.email || 'none'}</div>
    </div>
  );
};

describe('AuthContext Role & Session Security', () => {
  beforeEach(() => {
    authStorage.clear();
    vi.restoreAllMocks();
  });

  it('rejects access when token is present but user role is not platform_admin', async () => {
    authStorage.setToken('fake-token');
    vi.spyOn(authApi, 'getMe').mockResolvedValue({
      id: 'usr-1',
      name: 'Tenant User',
      email: 'tenant_user@example.com',
      role: 'tenant_user',
      status: 'active',
    });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('unauthenticated');
      expect(screen.getByTestId('superadmin-status')).toHaveTextContent('no');
      expect(authStorage.getToken()).toBeNull();
    });
  });

  it('allows access when user has platform_admin role', async () => {
    authStorage.setToken('valid-admin-token');
    vi.spyOn(authApi, 'getMe').mockResolvedValue({
      id: 'usr-admin',
      name: 'Platform Admin',
      email: 'admin@platform.local',
      role: 'platform_admin',
      status: 'active',
    });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('authenticated');
      expect(screen.getByTestId('superadmin-status')).toHaveTextContent('yes');
      expect(screen.getByTestId('user-email')).toHaveTextContent('admin@platform.local');
    });
  });

  it('clears session when /me API call fails', async () => {
    authStorage.setToken('expired-token');
    vi.spyOn(authApi, 'getMe').mockRejectedValue(new Error('Unauthorized'));

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('unauthenticated');
      expect(authStorage.getToken()).toBeNull();
    });
  });
});
