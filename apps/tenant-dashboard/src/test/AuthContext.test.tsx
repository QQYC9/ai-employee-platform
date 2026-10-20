import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { AuthProvider, useAuth } from '../context/AuthContext';
import { authStorage } from '../api/client';
import { authApi } from '../api/auth';

const TestConsumer: React.FC = () => {
  const { user, isAuthenticated, isTenantOwner, isLoading } = useAuth();
  if (isLoading) return <div>Loading...</div>;
  return (
    <div>
      <div data-testid="auth-status">{isAuthenticated ? 'authenticated' : 'unauthenticated'}</div>
      <div data-testid="owner-status">{isTenantOwner ? 'yes' : 'no'}</div>
      <div data-testid="user-email">{user?.email || 'none'}</div>
      <div data-testid="tenant-id">{user?.tenant_id || 'none'}</div>
    </div>
  );
};

describe('Tenant AuthContext Role & Boundary Isolation', () => {
  beforeEach(() => {
    authStorage.clear();
    vi.restoreAllMocks();
  });

  it('rejects access when user is platform_admin with no tenant_id', async () => {
    authStorage.setToken('platform-token');
    vi.spyOn(authApi, 'getMe').mockResolvedValue({
      id: 'super-1',
      name: 'Super Admin',
      email: 'admin@platform.local',
      role: 'platform_admin',
      tenant_id: null,
      status: 'active',
    });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('unauthenticated');
      expect(screen.getByTestId('owner-status')).toHaveTextContent('no');
      expect(authStorage.getToken()).toBeNull();
    });
  });

  it('rejects access when user has valid role but tenant_id is missing', async () => {
    authStorage.setToken('tenant-user-token');
    vi.spyOn(authApi, 'getMe').mockResolvedValue({
      id: 'usr-1',
      name: 'Orphan User',
      email: 'orphan@example.com',
      role: 'tenant_owner',
      tenant_id: null,
      status: 'active',
    });

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

  it('allows access when user is tenant_owner with valid tenant_id', async () => {
    authStorage.setToken('valid-owner-token');
    vi.spyOn(authApi, 'getMe').mockResolvedValue({
      id: 'usr-owner',
      name: 'Company Owner',
      email: 'owner@tenant-alpha.local',
      role: 'tenant_owner',
      tenant_id: 'tenant-12345',
      status: 'active',
    });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('authenticated');
      expect(screen.getByTestId('owner-status')).toHaveTextContent('yes');
      expect(screen.getByTestId('user-email')).toHaveTextContent('owner@tenant-alpha.local');
      expect(screen.getByTestId('tenant-id')).toHaveTextContent('tenant-12345');
    });
  });

  it('allows access when user is tenant_user with valid tenant_id', async () => {
    authStorage.setToken('valid-user-token');
    vi.spyOn(authApi, 'getMe').mockResolvedValue({
      id: 'usr-staff',
      name: 'Support Agent',
      email: 'staff@tenant-alpha.local',
      role: 'tenant_user',
      tenant_id: 'tenant-12345',
      status: 'active',
    });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('authenticated');
      expect(screen.getByTestId('owner-status')).toHaveTextContent('no');
      expect(screen.getByTestId('user-email')).toHaveTextContent('staff@tenant-alpha.local');
      expect(screen.getByTestId('tenant-id')).toHaveTextContent('tenant-12345');
    });
  });

  it('clears session when auth token is rejected by backend /me', async () => {
    authStorage.setToken('expired-or-tampered-token');
    vi.spyOn(authApi, 'getMe').mockRejectedValue(new Error('Invalid token'));

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
