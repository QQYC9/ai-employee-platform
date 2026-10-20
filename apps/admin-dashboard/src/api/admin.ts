import { apiClient } from './client';
import {
  AuditLogsResponse,
  OperationalHealth,
  PlatformMetrics,
  PlatformSummary,
  TenantsResponse,
} from './types';

export const adminApi = {
  async getPlatformOverview(): Promise<PlatformSummary> {
    return apiClient<PlatformSummary>('/api/v1/admin/platform/overview');
  },

  async listTenants(
    limit: number = 50,
    offset: number = 0,
    status?: string
  ): Promise<TenantsResponse> {
    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString(),
    });
    if (status) params.append('status', status);
    return apiClient<TenantsResponse>(`/api/v1/admin/platform/tenants?${params.toString()}`);
  },

  async updateTenantBudget(
    tenantId: string,
    data: { daily_token_limit?: number | null; monthly_token_limit?: number | null; is_hard_limit?: boolean }
  ): Promise<any> {
    return apiClient(`/api/v1/admin/platform/tenants/${tenantId}/budget`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  async updateTenantStatus(tenantId: string, status: string): Promise<any> {
    return apiClient(`/api/v1/admin/platform/tenants/${tenantId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
  },

  async getPlatformMetrics(timeWindowDays: number = 30): Promise<PlatformMetrics> {
    return apiClient<PlatformMetrics>(`/api/v1/admin/platform/metrics?time_window_days=${timeWindowDays}`);
  },

  async listAuditLogs(
    options: { tenantId?: string; eventType?: string; limit?: number; offset?: number } = {}
  ): Promise<AuditLogsResponse> {
    const params = new URLSearchParams();
    if (options.tenantId) params.append('tenant_id', options.tenantId);
    if (options.eventType) params.append('event_type', options.eventType);
    if (options.limit) params.append('limit', options.limit.toString());
    if (options.offset) params.append('offset', options.offset.toString());
    return apiClient<AuditLogsResponse>(`/api/v1/admin/platform/audit-logs?${params.toString()}`);
  },

  async getOperationalHealth(): Promise<OperationalHealth> {
    return apiClient<OperationalHealth>('/api/v1/admin/monitoring/health');
  },

  async provisionTenant(data: {
    tenant_name: string;
    slug?: string;
    owner_email: string;
    owner_name: string;
    owner_password?: string;
    agent_name?: string;
    industry?: string;
  }): Promise<any> {
    const payload: Record<string, any> = {
      name: data.tenant_name,
      owner_name: data.owner_name,
      owner_email: data.owner_email,
      owner_password: data.owner_password || 'TemporaryPassword123!',
    };
    if (data.slug?.trim()) {
      payload.slug = data.slug.trim();
    }
    if (data.agent_name?.trim()) {
      payload.agent = {
        name: data.agent_name.trim(),
        agent_type: 'main',
      };
    }
    return apiClient('/api/v1/tenants/provision', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
};
