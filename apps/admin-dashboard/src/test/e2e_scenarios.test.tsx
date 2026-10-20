import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { App } from '../App';
import { authStorage } from '../api/client';
import { authApi } from '../api/auth';
import { adminApi } from '../api/admin';

describe('Phase 19.2 — End-to-End Browser Scenarios (JSDOM Environment)', () => {
  beforeEach(() => {
    authStorage.clear();
    window.history.pushState({}, '', '/login');
    vi.restoreAllMocks();
  });

  it('Scenario 1: Unauthenticated visitor accessing protected route is redirected to /login', async () => {
    window.history.pushState({}, '', '/tenants');
    render(<App />);

    const emailField = await screen.findByPlaceholderText('admin@platform.local');
    expect(emailField).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /تسجيل الدخول/i })).toBeInTheDocument();
  });

  it('Scenario 2: Authorized Super Admin (platform_admin) logs in and navigates to Dashboard', async () => {
    window.history.pushState({}, '', '/login');
    vi.spyOn(authApi, 'login').mockResolvedValue({
      access_token: 'valid-admin-token',
      refresh_token: 'valid-refresh-token',
      token_type: 'bearer',
      expires_in: 3600,
      user: {
        id: 'usr-superadmin',
        name: 'Platform Super Admin',
        email: 'admin@platform.local',
        role: 'platform_admin',
        status: 'active',
      },
    });

    vi.spyOn(adminApi, 'getPlatformOverview').mockResolvedValue({
      tenants: { total: 2, by_status: { active: 2 } },
      agents: { total: 2, by_status: { active: 2 } },
      tasks: {
        total: 10,
        completed: 8,
        failed: 1,
        pending: 1,
        in_progress: 0,
        tasks_with_errors: 1,
        success_rate_pct: 80,
        failure_rate_pct: 10,
      },
      channels: { total: 1, by_status: { active: 1 }, by_type: { whatsapp: 1 } },
      outbox: { total: 15, by_status: { completed: 15 }, dead_letter: 0, stuck_processing: 0 },
      ai_usage: {
        total_requests: 100,
        prompt_tokens: 30000,
        completion_tokens: 20000,
        total_tokens: 50000,
        avg_duration_ms: 450,
        error_requests: 0,
        fallback_requests: 0,
      },
      audit: { recent_events_24h: 5 },
      generated_at: '2026-10-19T00:00:00Z',
    });

    vi.spyOn(adminApi, 'getOperationalHealth').mockResolvedValue({
      overall_status: 'healthy',
      components: {
        database: { status: 'healthy', details: { connected: true } },
        outbox: { status: 'healthy', details: { total: 15, pending: 0, processing: 0, dead_letter: 0, stuck_processing: 0 } },
        stalled_tasks: { status: 'healthy', details: { count: 0, sample: [] } },
      },
    });

    render(<App />);

    const emailInput = await screen.findByPlaceholderText('admin@platform.local');
    const passwordInput = screen.getByPlaceholderText('••••••••••••');
    const submitBtn = screen.getByRole('button', { name: /تسجيل الدخول/i });

    fireEvent.change(emailInput, { target: { value: 'admin@platform.local' } });
    fireEvent.change(passwordInput, { target: { value: 'AdminPassword123!' } });
    fireEvent.click(submitBtn);

    const overviewHeading = await screen.findByText(/لوحة المعلومات الرئيسية/i);
    expect(overviewHeading).toBeInTheDocument();
  });

  it('Scenario 3: Unauthorized user (tenant_owner) is rejected with clear error message', async () => {
    window.history.pushState({}, '', '/login');
    vi.spyOn(authApi, 'login').mockResolvedValue({
      access_token: 'tenant-owner-token',
      refresh_token: 'tenant-owner-refresh',
      token_type: 'bearer',
      expires_in: 3600,
      user: {
        id: 'usr-owner-alpha',
        name: 'Alpha Owner',
        email: 'owner-alpha@staging.local',
        role: 'tenant_owner',
        status: 'active',
      },
    });

    render(<App />);

    const emailInput = await screen.findByPlaceholderText('admin@platform.local');
    const passwordInput = screen.getByPlaceholderText('••••••••••••');
    const submitBtn = screen.getByRole('button', { name: /تسجيل الدخول/i });

    fireEvent.change(emailInput, { target: { value: 'owner-alpha@staging.local' } });
    fireEvent.change(passwordInput, { target: { value: 'StagingPassword123!' } });
    fireEvent.click(submitBtn);

    const errorAlert = await screen.findByText(/ليس لديك صلاحيات الإدارة العليا/i);
    expect(errorAlert).toBeInTheDocument();
    expect(authStorage.getToken()).toBeNull();
  });

  it('Scenario 4 & 5: Navigation between sections displays real data from API', async () => {
    authStorage.setToken('valid-admin-token');
    vi.spyOn(authApi, 'getMe').mockResolvedValue({
      id: 'usr-admin',
      name: 'Super Admin',
      email: 'admin@platform.local',
      role: 'platform_admin',
      status: 'active',
    });

    vi.spyOn(adminApi, 'getPlatformOverview').mockResolvedValue({
      tenants: { total: 2, by_status: { active: 2 } },
      agents: { total: 2, by_status: { active: 2 } },
      tasks: {
        total: 10,
        completed: 8,
        failed: 1,
        pending: 1,
        in_progress: 0,
        tasks_with_errors: 1,
        success_rate_pct: 80,
        failure_rate_pct: 10,
      },
      channels: { total: 1, by_status: { active: 1 }, by_type: { whatsapp: 1 } },
      outbox: { total: 15, by_status: { completed: 15 }, dead_letter: 0, stuck_processing: 0 },
      ai_usage: {
        total_requests: 100,
        prompt_tokens: 30000,
        completion_tokens: 20000,
        total_tokens: 50000,
        avg_duration_ms: 450,
        error_requests: 0,
        fallback_requests: 0,
      },
      audit: { recent_events_24h: 5 },
      generated_at: '2026-10-19T00:00:00Z',
    });

    vi.spyOn(adminApi, 'getOperationalHealth').mockResolvedValue({
      overall_status: 'healthy',
      components: {
        database: { status: 'healthy', details: { connected: true } },
        outbox: { status: 'healthy', details: { total: 15, pending: 0, processing: 0, dead_letter: 0, stuck_processing: 0 } },
        stalled_tasks: { status: 'healthy', details: { count: 0, sample: [] } },
      },
    });

    vi.spyOn(adminApi, 'listTenants').mockResolvedValue({
      tenants: [
        {
          id: 't-alpha',
          name: 'Tenant Alpha Staging',
          slug: 'tenant-alpha',
          status: 'active',
          created_at: '2026-01-01T00:00:00Z',
          agent_count: 1,
          task_count: 5,
          failed_task_count: 0,
          budget: {
            configured: true,
            daily_limit: 10000,
            monthly_limit: 300000,
            current_day_tokens: 500,
            current_month_tokens: 15000,
            alert_level: 'none',
          },
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });

    window.history.pushState({}, '', '/');
    render(<App />);

    const tenantsLink = await screen.findByRole('link', { name: /المستأجرون والعملاء/i });
    fireEvent.click(tenantsLink);

    const tenantRow = await screen.findByText('Tenant Alpha Staging');
    expect(tenantRow).toBeInTheDocument();
  });

  it('Scenario 6: Empty state is rendered when search filter finds no matching tenants', async () => {
    authStorage.setToken('valid-admin-token');
    vi.spyOn(authApi, 'getMe').mockResolvedValue({
      id: 'usr-admin',
      name: 'Super Admin',
      email: 'admin@platform.local',
      role: 'platform_admin',
      status: 'active',
    });

    vi.spyOn(adminApi, 'listTenants').mockResolvedValue({
      tenants: [],
      total: 0,
      limit: 50,
      offset: 0,
    });

    window.history.pushState({}, '', '/tenants');
    render(<App />);

    const emptyTitle = await screen.findByText(/لم يتم العثور على أي مستأجر/i);
    expect(emptyTitle).toBeInTheDocument();
  });

  it('Scenario 7 & 9: Action error handling does not display false success on API failure', async () => {
    authStorage.setToken('valid-admin-token');
    vi.spyOn(authApi, 'getMe').mockResolvedValue({
      id: 'usr-admin',
      name: 'Super Admin',
      email: 'admin@platform.local',
      role: 'platform_admin',
      status: 'active',
    });

    vi.spyOn(adminApi, 'listTenants').mockResolvedValue({
      tenants: [
        {
          id: 't-test',
          name: 'Test Tenant',
          slug: 'test-tenant',
          status: 'active',
          created_at: '2026-01-01T00:00:00Z',
          agent_count: 1,
          task_count: 0,
          failed_task_count: 0,
          budget: {
            configured: true,
            daily_limit: 1000,
            monthly_limit: 50000,
            current_day_tokens: 0,
            current_month_tokens: 0,
            alert_level: 'none',
          },
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });

    // Mock API failure for status update
    vi.spyOn(adminApi, 'updateTenantStatus').mockRejectedValue(new Error('قاعدة البيانات غير متاحة حالياً'));

    window.history.pushState({}, '', '/tenants');
    render(<App />);

    const tenantName = await screen.findByText('Test Tenant');
    expect(tenantName).toBeInTheDocument();

    // Open status modal
    const statusBtn = screen.getByRole('button', { name: /^الحالة$/i });
    fireEvent.click(statusBtn);

    // Click confirm in modal
    const confirmBtn = screen.getByRole('button', { name: /حفظ التغييرات/i });
    fireEvent.click(confirmBtn);

    const errorMessage = await screen.findByText(/قاعدة البيانات غير متاحة حالياً/i);
    expect(errorMessage).toBeInTheDocument();
    expect(screen.queryByText(/تم الحفظ بنجاح/i)).not.toBeInTheDocument();
  });

  it('Scenario 8: Expired token during user refresh clears session and redirects to /login', async () => {
    authStorage.setToken('expired-admin-token');
    vi.spyOn(authApi, 'getMe').mockRejectedValue(new Error('Token expired'));

    window.history.pushState({}, '', '/');
    render(<App />);

    const loginField = await screen.findByPlaceholderText('admin@platform.local');
    expect(loginField).toBeInTheDocument();
    expect(authStorage.getToken()).toBeNull();
  });
});
