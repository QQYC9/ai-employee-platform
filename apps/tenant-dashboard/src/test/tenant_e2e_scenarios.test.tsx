import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { App } from '../App';
import { authStorage } from '../api/client';
import { authApi } from '../api/auth';
import { tenantApi } from '../api/tenant';
import { agentsApi } from '../api/agents';
import { tasksApi } from '../api/tasks';
import { channelsApi } from '../api/channels';

describe('Tenant Dashboard E2E Scenarios & Security Isolation', () => {
  const mockTenant = {
    id: 'tenant-alpha-uuid',
    name: 'شركة ألفا للتقنية',
    slug: 'alpha-tech',
    status: 'active',
  };

  const mockOwnerUser = {
    id: 'user-alpha-owner',
    name: 'سالم الشمري',
    email: 'owner-alpha@staging.local',
    role: 'tenant_owner',
    tenant_id: 'tenant-alpha-uuid',
    status: 'active',
  };

  const mockDashboardData = {
    tenant: mockTenant,
    agents: {
      total: 3,
      items: [
        { id: 'agent-1', name: 'منسق العمليات', agent_type: 'react', status: 'active' },
        { id: 'agent-2', name: 'مساعد المبيعات', agent_type: 'assistant', status: 'active' },
        { id: 'agent-3', name: 'محلل البيانات المتوقف', agent_type: 'specialist', status: 'inactive' },
      ],
    },
    tasks: {
      total: 10,
      completed: 8,
      failed: 1,
      pending: 1,
      in_progress: 0,
      tasks_with_errors: 1,
      success_rate_pct: 88.9,
      failure_rate_pct: 11.1,
    },
    channels: {
      total: 1,
      by_type: { whatsapp: 1 },
      items: [
        {
          id: 'chan-1',
          tenant_id: 'tenant-alpha-uuid',
          name: 'واتساب خدمة العملاء',
          channel_type: 'whatsapp',
          provider: 'meta',
          status: 'active',
        },
      ],
    },
    outbox: {
      total: 45,
      by_status: { processed: 44 },
      dead_letter: 0,
      stuck_processing: 0,
    },
    budget: {
      configured: true,
      daily_limit: 100000,
      monthly_limit: 1000000,
      current_day_tokens: 15400,
      current_month_tokens: 125000,
      alert_level: 'none' as const,
    },
  };

  const mockTasks = [
    {
      id: 'task-1',
      tenant_id: 'tenant-alpha-uuid',
      agent_id: 'agent-1',
      title: 'تحليل عقود الموردين',
      objective: 'قراءة ملفات PDF وتلخيص البنود',
      status: 'completed',
      priority: 'high',
      created_at: '2026-10-19T10:00:00Z',
    },
    {
      id: 'task-2',
      tenant_id: 'tenant-alpha-uuid',
      agent_id: 'agent-2',
      title: 'إرسال نشرة العملاء البريدية',
      objective: 'توليد المحتوى الإعلاني',
      status: 'failed',
      priority: 'medium',
      error: 'Connection timeout with SMTP server',
      created_at: '2026-10-19T12:00:00Z',
    },
  ];

  beforeEach(() => {
    window.history.pushState({}, '', '/');
    authStorage.clear();
    vi.restoreAllMocks();

    // Default mocks for APIs
    vi.spyOn(tenantApi, 'getTenant').mockResolvedValue(mockTenant);
    vi.spyOn(tenantApi, 'getDashboard').mockResolvedValue(mockDashboardData);
    vi.spyOn(tenantApi, 'getBusinessBrain').mockResolvedValue({
      identity: { voice_tone: 'احترافي ومهني', mission: 'الريادة التقنية' },
      policies: { rules: ['الالتزام باللغة العربية'] },
    });
    vi.spyOn(tenantApi, 'getBudget').mockResolvedValue(mockDashboardData.budget);
    vi.spyOn(tenantApi, 'getMetrics').mockResolvedValue({
      time_window_days: 30,
      summary: {
        total_requests: 120,
        successful_requests: 118,
        error_requests: 2,
        fallback_requests: 0,
        prompt_tokens: 85000,
        completion_tokens: 40000,
        total_tokens: 125000,
        avg_duration_ms: 450,
        unique_tasks_invoked: 10,
      },
      by_provider: {
        gemini: { requests: 120, tokens: 125000, errors: 2 },
      },
      by_model: {
        'gemini-1.5-pro': { provider: 'gemini', requests: 120, tokens: 125000, errors: 2 },
      },
      daily_trends: [
        { date: '2026-10-18', requests: 40, tokens: 45000, errors: 0 },
        { date: '2026-10-19', requests: 80, tokens: 80000, errors: 2 },
      ],
    });
    vi.spyOn(agentsApi, 'listAgents').mockResolvedValue(mockDashboardData.agents.items);
    vi.spyOn(tasksApi, 'listTasks').mockResolvedValue(mockTasks);
    vi.spyOn(channelsApi, 'listChannels').mockResolvedValue(mockDashboardData.channels.items);
  });

  it('renders login page when unauthenticated', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('بوابة عمليات الشركة')).toBeInTheDocument();
      expect(screen.getByPlaceholderText('owner@company.local')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /دخول إلى لوحة الشركة/i })).toBeInTheDocument();
    });
  });

  it('shows error when login credentials fail', async () => {
    vi.spyOn(authApi, 'login').mockRejectedValue(new Error('البريد الإلكتروني أو كلمة المرور غير صحيحة'));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText('owner@company.local')).toBeInTheDocument();
    });

    const emailInput = screen.getByPlaceholderText('owner@company.local');
    const passwordInput = screen.getByPlaceholderText('••••••••••••');
    const submitBtn = screen.getByRole('button', { name: /دخول إلى لوحة الشركة/i });

    fireEvent.change(emailInput, { target: { value: 'wrong@company.local' } });
    fireEvent.change(passwordInput, { target: { value: 'BadPassword123' } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText('البريد الإلكتروني أو كلمة المرور غير صحيحة')).toBeInTheDocument();
    });
  });

  it('authenticates tenant owner and displays dashboard with isolated tenant data', async () => {
    authStorage.setToken('alpha-owner-jwt-token');
    vi.spyOn(authApi, 'getMe').mockResolvedValue(mockOwnerUser);

    render(<App />);

    await waitFor(() => {
      // Check tenant name in header and sidebar
      expect(screen.getAllByText('شركة ألفا للتقنية').length).toBeGreaterThan(0);
      // Check KPI values
      expect(screen.getByText('125,000')).toBeInTheDocument(); // Tokens consumed
      // Check agent name
      expect(screen.getByText('منسق العمليات')).toBeInTheDocument();
      // Check task name
      expect(screen.getByText('تحليل عقود الموردين')).toBeInTheDocument();
    });
  });

  it('enables retrying a failed task from tasks page', async () => {
    authStorage.setToken('alpha-owner-jwt-token');
    vi.spyOn(authApi, 'getMe').mockResolvedValue(mockOwnerUser);
    const retrySpy = vi.spyOn(tasksApi, 'retryTask').mockResolvedValue({
      ...mockTasks[1],
      status: 'pending',
      error: null,
    });

    // Mock confirm dialog
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('سجل المهام')).toBeInTheDocument();
    });

    // Click on tasks link in navigation
    fireEvent.click(screen.getByText('سجل المهام'));

    await waitFor(() => {
      expect(screen.getByText('إرسال نشرة العملاء البريدية')).toBeInTheDocument();
      expect(screen.getByTitle('إعادة المحاولة')).toBeInTheDocument();
    });

    // Trigger retry
    fireEvent.click(screen.getByTitle('إعادة المحاولة'));

    await waitFor(() => {
      expect(retrySpy).toHaveBeenCalledWith('task-2', expect.any(String));
    });
  });

  it('correctly calculates active agents from items and binds budget metrics (DEF-20-01, DEF-20-02)', async () => {
    authStorage.setToken('alpha-owner-jwt-token');
    vi.spyOn(authApi, 'getMe').mockResolvedValue(mockOwnerUser);

    render(<App />);

    await waitFor(() => {
      // DEF-20-02: Total 3, Active 2 (calculated from items with status 'active', ignoring inactive)
      expect(screen.getByText('2 موظف في وضع التشغيل')).toBeInTheDocument();
      // DEF-20-01: Budget tokens consumed bound from data.budget.current_month_tokens
      expect(screen.getByText('125,000')).toBeInTheDocument();
      expect(screen.getByText(/من أصل 1,000,000/)).toBeInTheDocument();
    });
  });

  it('restores authenticated session using /api/v1/auth/me profile (DEF-20-03)', async () => {
    authStorage.setToken('alpha-owner-jwt-token');
    const getMeSpy = vi.spyOn(authApi, 'getMe').mockResolvedValue(mockOwnerUser);

    render(<App />);

    await waitFor(() => {
      expect(getMeSpy).toHaveBeenCalled();
      expect(screen.getAllByText('شركة ألفا للتقنية').length).toBeGreaterThan(0);
    });
  });
});
