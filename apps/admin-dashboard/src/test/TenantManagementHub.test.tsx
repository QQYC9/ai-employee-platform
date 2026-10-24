import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { TenantManagementHubModal } from '../components/tenants/TenantManagementHubModal';
import { adminApi } from '../api/admin';
import { TenantItem } from '../api/types';

const mockTenant: TenantItem = {
  id: 't-test-uuid-1234',
  name: 'شركة تجربة السحاب',
  slug: 'cloud-experience-co',
  status: 'active',
  created_at: '2026-01-01T00:00:00Z',
  agent_count: 2,
  task_count: 3,
  failed_task_count: 1,
  budget: {
    configured: true,
    daily_limit: 50000,
    monthly_limit: 1000000,
    current_day_tokens: 1200,
    current_month_tokens: 45000,
    alert_level: 'none',
  },
};

describe('TenantManagementHubModal — Comprehensive Tenant Hub Verification', () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders modal header with tenant name, slug, and status badge', async () => {
    vi.spyOn(adminApi, 'getTenantTasks').mockResolvedValue({
      total: 0,
      limit: 50,
      offset: 0,
      tasks: [],
    });

    render(
      <TenantManagementHubModal
        tenant={mockTenant}
        isOpen={true}
        onClose={vi.fn()}
      />
    );

    expect(await screen.findByText('شركة تجربة السحاب')).toBeInTheDocument();
    expect(screen.getByText(/cloud-experience-co/i)).toBeInTheDocument();
    expect(screen.getByText(/t-test-uuid-1234/i)).toBeInTheDocument();
  });

  it('loads and displays tenant operational tasks with emergency cancellation', async () => {
    vi.spyOn(adminApi, 'getTenantTasks').mockResolvedValue({
      total: 1,
      limit: 50,
      offset: 0,
      tasks: [
        {
          id: 'task-uuid-888',
          tenant_id: mockTenant.id,
          title: 'تحليل مبيعات الربع الثالث',
          objective: 'استخراج الأرباح والتقارير المالية',
          status: 'in_progress',
          priority: 'high',
          plan: { steps: ['fetch_data', 'aggregate'] },
          result: {},
        },
      ],
    });

    vi.spyOn(adminApi, 'emergencyCancelTask').mockResolvedValue({
      status: 'cancelled',
      task_id: 'task-uuid-888',
    });

    render(
      <TenantManagementHubModal
        tenant={mockTenant}
        isOpen={true}
        onClose={vi.fn()}
      />
    );

    const taskTitle = await screen.findByText('تحليل مبيعات الربع الثالث');
    expect(taskTitle).toBeInTheDocument();
    expect(screen.getByText('استخراج الأرباح والتقارير المالية')).toBeInTheDocument();

    // Click Emergency Cancel button
    const emergencyBtn = screen.getByRole('button', { name: /إلغاء طارئ/i });
    fireEvent.click(emergencyBtn);

    // Prompt opens: verify audit reason validation (<15 chars fails)
    const reasonInput = screen.getByPlaceholderText(/سبب الإلغاء الطارئ/i);
    const confirmCancelBtn = screen.getByRole('button', { name: /تأكيد الإلغاء والتدقيق/i });

    // Try short reason
    fireEvent.change(reasonInput, { target: { value: 'Too short' } });
    fireEvent.click(confirmCancelBtn);

    const errorMsg = await screen.findByText(/سبب الإلغاء الطارئ يجب ألا يقل عن 15 حرفاً/i);
    expect(errorMsg).toBeInTheDocument();

    // Valid audit reason
    fireEvent.change(reasonInput, {
      target: { value: 'إلغاء طارئ بسبب تعليق الخادم واستهلاك الموارد' },
    });
    fireEvent.click(confirmCancelBtn);

    expect(adminApi.emergencyCancelTask).toHaveBeenCalledWith(
      mockTenant.id,
      'task-uuid-888',
      'إلغاء طارئ بسبب تعليق الخادم واستهلاك الموارد'
    );
  });

  it('navigates to Error Diagnostics tab and displays aggregated error center', async () => {
    vi.spyOn(adminApi, 'getTenantTasks').mockResolvedValue({ total: 0, limit: 50, offset: 0, tasks: [] });
    vi.spyOn(adminApi, 'getTenantErrors').mockResolvedValue({
      tenant_id: mockTenant.id,
      total_errors: 2,
      tasks_errors: [
        {
          id: 'err-1',
          task_title: 'مهمة مزامنة جهات الاتصال',
          status: 'failed',
          error_message: 'انتهت مهلة الاتصال بالـ CRM بعد 30 ثانية',
        },
      ],
      traces_errors: [],
      ai_errors: [
        {
          id: 'err-2',
          provider: 'groq',
          model: 'llama-3.3-70b',
          error_category: 'rate_limit_exceeded',
          error_message: 'RPM quota reached',
        },
      ],
      outbox_errors: [],
    });

    render(
      <TenantManagementHubModal
        tenant={mockTenant}
        isOpen={true}
        onClose={vi.fn()}
      />
    );

    // Switch tab
    const errorsTabBtn = await screen.findByRole('button', { name: /مركز تشخيص الأخطاء/i });
    fireEvent.click(errorsTabBtn);

    expect(await screen.findByText('انتهت مهلة الاتصال بالـ CRM بعد 30 ثانية')).toBeInTheDocument();
    expect(screen.getByText('RPM quota reached')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument(); // total errors
  });

  it('navigates to Capabilities tab and enforces 3-way separation', async () => {
    vi.spyOn(adminApi, 'getTenantTasks').mockResolvedValue({ total: 0, limit: 50, offset: 0, tasks: [] });
    vi.spyOn(adminApi, 'getTenantCapabilities').mockResolvedValue({
      tenant_id: mockTenant.id,
      tenant_capabilities: [
        {
          id: 'c-1',
          name: 'المحاسبة المخصصة للشركة',
          slug: 'custom-accounting-plugin',
          description: 'إضافة محاسبية خاصة بنظام Odoo',
          is_active: true,
          scope: 'tenant_custom',
        },
      ],
      shared_capabilities: [
        {
          id: 'c-2',
          name: 'محلل ملفات PDF المعتمد',
          slug: 'global-pdf-parser',
          description: 'محلل PDF القياسي للمنصة',
          is_active: true,
          scope: 'global_shared',
        },
      ],
      self_development_versions: [
        {
          id: 'v-1',
          version_number: 2,
          slug: 'custom-accounting-plugin',
          name: 'تطوير سرعة المحاسبة v2',
          description: 'تحسين كفاءة الاستعلامات',
          risk_level: 'low',
          status: 'active',
        },
      ],
    });

    render(
      <TenantManagementHubModal
        tenant={mockTenant}
        isOpen={true}
        onClose={vi.fn()}
      />
    );

    const capabilitiesTabBtn = await screen.findByRole('button', { name: /المهارات والقدرات/i });
    fireEvent.click(capabilitiesTabBtn);

    // Verify 3 sections
    expect(await screen.findByText('المحاسبة المخصصة للشركة')).toBeInTheDocument();
    expect(screen.getByText('محلل ملفات PDF المعتمد')).toBeInTheDocument();
    expect(screen.getByText('معتمد عالمياً')).toBeInTheDocument();
    expect(screen.getByText(/تطوير سرعة المحاسبة v2/i)).toBeInTheDocument();
  });

  it('navigates to Integrations tab and displays masked secret keys without plaintext leaks', async () => {
    vi.spyOn(adminApi, 'getTenantTasks').mockResolvedValue({ total: 0, limit: 50, offset: 0, tasks: [] });
    vi.spyOn(adminApi, 'getTenantIntegrations').mockResolvedValue([
      {
        id: 'int-99',
        name: 'Groq Tenant Custom',
        provider: 'groq',
        model: 'llama-3.3-70b-versatile',
        status: 'active',
        masked_api_key: 'gsk_****9999',
        is_default: true,
      },
    ]);

    render(
      <TenantManagementHubModal
        tenant={mockTenant}
        isOpen={true}
        onClose={vi.fn()}
      />
    );

    const integrationsTabBtn = await screen.findByRole('button', { name: /تكاملات المستأجر/i });
    fireEvent.click(integrationsTabBtn);

    expect(await screen.findByText('Groq Tenant Custom')).toBeInTheDocument();
    expect(screen.getByText('gsk_****9999')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /تعطيل طارئ/i })).toBeInTheDocument();
  });
});
