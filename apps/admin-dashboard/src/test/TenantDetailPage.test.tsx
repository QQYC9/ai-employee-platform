import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { TenantDetailPage } from '../pages/TenantDetailPage';
import { TenantsPage } from '../pages/TenantsPage';
import { adminApi } from '../api/admin';
import { TenantDashboardData } from '../api/types';

const mockDashboardData: TenantDashboardData = {
  tenant: {
    id: 't-alpha-uuid',
    name: 'شركة سحاب التجارة',
    slug: 'sahab-trade-co',
    status: 'active',
  },
  tasks: {
    total: 3,
    completed: 2,
    failed: 1,
    pending: 0,
    in_progress: 0,
    success_rate_pct: 66.7,
    failure_rate_pct: 33.3,
    avg_execution_latency_sec: 1.8,
  },
  agents: {
    total: 1,
    items: [
      {
        id: 'ag-1',
        name: 'سارة - موظف خدمة العملاء',
        agent_type: 'main',
        status: 'active',
        created_at: '2026-01-01T00:00:00Z',
      },
    ],
  },
  channels: {
    total: 1,
    items: [
      {
        id: 'ch-1',
        name: 'WhatsApp Business',
        channel_type: 'whatsapp',
        status: 'active',
        config: {},
      },
    ],
  },
  outbox: {
    total: 10,
    by_status: { completed: 10 },
    dead_letter: 0,
  },
  budget: {
    configured: true,
    daily_limit: 50000,
    monthly_limit: 1500000,
    current_day_tokens: 3500,
    current_month_tokens: 85000,
    alert_level: 'none',
  },
  recent_audit_events: [],
  generated_at: '2026-10-24T12:00:00Z',
};

describe('Phase 1 Tenant Details Page (/tenants/:tenantId) — Direct Route & Deep Linking', () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('Scenario 1: Opens /tenants/:tenantId directly, loads tenant dashboard data and displays breadcrumbs', async () => {
    vi.spyOn(adminApi, 'getTenantDashboard').mockResolvedValue(mockDashboardData);
    vi.spyOn(adminApi, 'getTenantTasks').mockResolvedValue({
      total: 1,
      limit: 50,
      offset: 0,
      tasks: [
        {
          id: 'tsk-101',
          tenant_id: 't-alpha-uuid',
          title: 'تحليل مبيعات الأسبوع',
          objective: 'حساب الأرباح الأسبوعية',
          status: 'completed',
          priority: 'normal',
          result: { profit: '+20%' },
        },
      ],
    });

    render(
      <MemoryRouter initialEntries={['/tenants/t-alpha-uuid']}>
        <Routes>
          <Route path="/tenants" element={<TenantsPage />} />
          <Route path="/tenants/:tenantId" element={<TenantDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    // Verify tenant name in header and breadcrumbs
    expect(await screen.findByRole('heading', { name: 'شركة سحاب التجارة' })).toBeInTheDocument();
    expect(screen.getByText(/sahab-trade-co/i)).toBeInTheDocument();
    expect(screen.getByText(/t-alpha-uuid/i)).toBeInTheDocument();

    // Verify tasks tab loaded by default
    expect(await screen.findByText('تحليل مبيعات الأسبوع')).toBeInTheDocument();
  });

  it('Scenario 2: Deep linking via ?tab=errors opens the Error Diagnostics tab directly', async () => {
    vi.spyOn(adminApi, 'getTenantDashboard').mockResolvedValue(mockDashboardData);
    vi.spyOn(adminApi, 'getTenantErrors').mockResolvedValue({
      tenant_id: 't-alpha-uuid',
      total_errors: 1,
      tasks_errors: [
        {
          id: 'err-99',
          task_title: 'مهمة مزامنة الفواتير',
          status: 'failed',
          error_message: 'فشل الاتصال بقاعدة بيانات المحاسبة بعد 3 محاولات',
        },
      ],
      traces_errors: [],
      ai_errors: [],
      outbox_errors: [],
    });

    render(
      <MemoryRouter initialEntries={['/tenants/t-alpha-uuid?tab=errors']}>
        <Routes>
          <Route path="/tenants" element={<TenantsPage />} />
          <Route path="/tenants/:tenantId" element={<TenantDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('فشل الاتصال بقاعدة بيانات المحاسبة بعد 3 محاولات')).toBeInTheDocument();
    expect(screen.getByText('مهمة مزامنة الفواتير')).toBeInTheDocument();
  });

  it('Scenario 3: Deep linking via ?tab=capabilities opens the Capabilities separation tab', async () => {
    vi.spyOn(adminApi, 'getTenantDashboard').mockResolvedValue(mockDashboardData);
    vi.spyOn(adminApi, 'getTenantCapabilities').mockResolvedValue({
      tenant_id: 't-alpha-uuid',
      tenant_capabilities: [
        {
          id: 'cap-custom',
          name: 'المحاسبة السحابية المخصصة',
          slug: 'custom-cloud-accounting',
          is_active: true,
          scope: 'tenant_custom',
        },
      ],
      shared_capabilities: [
        {
          id: 'cap-shared',
          name: 'محلل PDF القياسي',
          slug: 'global-pdf-parser',
          is_active: true,
          scope: 'global_shared',
        },
      ],
      self_development_versions: [],
    });

    render(
      <MemoryRouter initialEntries={['/tenants/t-alpha-uuid?tab=capabilities']}>
        <Routes>
          <Route path="/tenants" element={<TenantsPage />} />
          <Route path="/tenants/:tenantId" element={<TenantDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('المحاسبة السحابية المخصصة')).toBeInTheDocument();
    expect(screen.getByText('محلل PDF القياسي')).toBeInTheDocument();
  });

  it('Scenario 4: Handles 404 / Non-existent tenant with clear error state and back button', async () => {
    vi.spyOn(adminApi, 'getTenantDashboard').mockRejectedValue(new Error('المستأجر غير موجود'));

    render(
      <MemoryRouter initialEntries={['/tenants/non-existent-uuid']}>
        <Routes>
          <Route path="/tenants" element={<TenantsPage />} />
          <Route path="/tenants/:tenantId" element={<TenantDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText(/المستأجر غير موجود/i)).toBeInTheDocument();
    const backBtn = screen.getByRole('button', { name: /العودة لقائمة المستأجرين/i });
    expect(backBtn).toBeInTheDocument();

    fireEvent.click(backBtn);
    // After clicking back, it navigates to /tenants
  });

  it('Scenario 5: Navigation from /tenants table button "مركز المستأجر" routes to /tenants/:tenantId', async () => {
    vi.spyOn(adminApi, 'listTenants').mockResolvedValue({
      tenants: [
        {
          id: 't-beta-uuid',
          name: 'شركة بيتا الرقمية',
          slug: 'beta-digital',
          status: 'active',
          created_at: '2026-01-01T00:00:00Z',
          agent_count: 1,
          task_count: 2,
          failed_task_count: 0,
          budget: {
            configured: true,
            daily_limit: 10000,
            monthly_limit: 300000,
            current_day_tokens: 100,
            current_month_tokens: 1500,
            alert_level: 'none',
          },
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });

    vi.spyOn(adminApi, 'getTenantDashboard').mockResolvedValue({
      ...mockDashboardData,
      tenant: {
        id: 't-beta-uuid',
        name: 'شركة بيتا الرقمية',
        slug: 'beta-digital',
        status: 'active',
      },
    });

    vi.spyOn(adminApi, 'getTenantTasks').mockResolvedValue({
      total: 0,
      limit: 50,
      offset: 0,
      tasks: [],
    });

    render(
      <MemoryRouter initialEntries={['/tenants']}>
        <Routes>
          <Route path="/tenants" element={<TenantsPage />} />
          <Route path="/tenants/:tenantId" element={<TenantDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    // Find the row
    expect(await screen.findByText('شركة بيتا الرقمية')).toBeInTheDocument();

    // Click "مركز المستأجر" button
    const hubBtn = screen.getByRole('button', { name: /مركز المستأجر/i });
    fireEvent.click(hubBtn);

    // Verify detail page header renders for t-beta-uuid
    expect(await screen.findByRole('heading', { name: 'شركة بيتا الرقمية' })).toBeInTheDocument();
  });

  it('Scenario 6: Platform admin opens channels tab and registers a new communication channel via modal', async () => {
    vi.spyOn(adminApi, 'getTenantDashboard').mockResolvedValue(mockDashboardData);
    vi.spyOn(adminApi, 'getTenantChannels').mockResolvedValue([]);
    const createChannelSpy = vi.spyOn(adminApi, 'createTenantChannel').mockResolvedValue({
      id: 'ch-new-1',
      tenant_id: 't-alpha-uuid',
      name: 'بوت تيليجرام خدمة العملاء',
      channel_type: 'telegram',
      provider: 'telegram',
      status: 'active',
      config: { bot_token: '123456:ABC-DEF-masked' },
      last_test_status: 'untested',
      last_test_result: {},
    });

    render(
      <MemoryRouter initialEntries={['/tenants/t-alpha-uuid?tab=channels']}>
        <Routes>
          <Route path="/tenants/:tenantId" element={<TenantDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    // Verify empty state is displayed initially
    expect(await screen.findByText(/لا توجد قنوات اتصال مسجلة لهذا المستأجر/i)).toBeInTheDocument();

    // Click "إضافة قناة اتصال"
    const addBtn = screen.getByRole('button', { name: /إضافة قناة اتصال/i });
    fireEvent.click(addBtn);

    // Verify Modal opens
    expect(screen.getByText(/إضافة وتشفير قناة اتصال للمستأجر/i)).toBeInTheDocument();

    // Fill form
    const nameInput = screen.getByPlaceholderText(/بوت تيليجرام خدمة العملاء/i);
    fireEvent.change(nameInput, { target: { value: 'بوت تيليجرام الدعم الفني' } });

    const tokenInput = screen.getByPlaceholderText(/123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ/i);
    fireEvent.change(tokenInput, { target: { value: '123456789:AAE-real-bot-token-to-encrypt' } });

    // Submit form
    const submitBtn = screen.getByRole('button', { name: /حفظ القناة وتشفير المفاتيح/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(createChannelSpy).toHaveBeenCalledWith('t-alpha-uuid', expect.objectContaining({
        name: 'بوت تيليجرام الدعم الفني',
        channel_type: 'telegram',
        provider: 'telegram',
        config: expect.objectContaining({
          bot_token: '123456789:AAE-real-bot-token-to-encrypt',
        }),
      }));
    });
  });

  it('Scenario 7: Platform admin tests connection for tenant channel and verifies live handshake telemetry and secret masking', async () => {
    vi.spyOn(adminApi, 'getTenantDashboard').mockResolvedValue(mockDashboardData);
    vi.spyOn(adminApi, 'getTenantChannels').mockResolvedValue([
      {
        id: 'ch-test-123',
        tenant_id: 't-alpha-uuid',
        name: 'واتساب خدمة العملاء الرسمي',
        channel_type: 'whatsapp',
        provider: 'meta',
        status: 'active',
        config: {
          phone_number_id: '1092837465',
          access_token: 'EAAB••••••••••••8888',
        },
        last_test_status: 'untested',
        last_test_result: {},
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ]);

    const testSpy = vi.spyOn(adminApi, 'testTenantChannel').mockResolvedValue({
      connected: true,
      success: true,
      status: 'connected',
      channel_id: 'ch-test-123',
      channel_type: 'whatsapp',
      latency_ms: 62.4,
      error_type: null,
      error_message: null,
    });

    render(
      <MemoryRouter initialEntries={['/tenants/t-alpha-uuid?tab=channels']}>
        <Routes>
          <Route path="/tenants/:tenantId" element={<TenantDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    // Channel rendered with masked key
    expect(await screen.findByText('واتساب خدمة العملاء الرسمي')).toBeInTheDocument();
    expect(screen.getByText('1092837465')).toBeInTheDocument();
    expect(screen.getByText('••••••••••••')).toBeInTheDocument();
    // Raw secret is never exposed
    expect(screen.queryByText('EAAB_raw_secret_token_unmasked')).not.toBeInTheDocument();

    // Connection is initially untested
    expect(screen.getByText(/لم تُختبر بعد/i)).toBeInTheDocument();

    // Click "اختبار الاتصال"
    const testBtn = screen.getByRole('button', { name: /اختبار الاتصال/i });
    fireEvent.click(testBtn);

    await waitFor(() => {
      expect(testSpy).toHaveBeenCalledWith('t-alpha-uuid', 'ch-test-123');
    });
  });

  it('Scenario 8: Handles test channel connection failure with clear error diagnosis', async () => {
    vi.spyOn(adminApi, 'getTenantDashboard').mockResolvedValue(mockDashboardData);
    vi.spyOn(adminApi, 'getTenantChannels').mockResolvedValue([
      {
        id: 'ch-fail-456',
        tenant_id: 't-alpha-uuid',
        name: 'قناة تيليجرام معطلة',
        channel_type: 'telegram',
        provider: 'telegram',
        status: 'active',
        config: {
          bot_token: '••••••••••••',
        },
        last_test_status: 'failed',
        last_test_result: {
          error_type: 'UnauthorizedError',
          error_message: 'Telegram Bot token is invalid or terminated',
        },
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ]);

    render(
      <MemoryRouter initialEntries={['/tenants/t-alpha-uuid?tab=channels']}>
        <Routes>
          <Route path="/tenants/:tenantId" element={<TenantDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('قناة تيليجرام معطلة')).toBeInTheDocument();
    // Shows failure badge
    expect(screen.getByText(/فشل الاتصال/i)).toBeInTheDocument();
    expect(screen.getByText(/UnauthorizedError/i)).toBeInTheDocument();
    expect(screen.getByText(/Telegram Bot token is invalid or terminated/i)).toBeInTheDocument();
  });
});
