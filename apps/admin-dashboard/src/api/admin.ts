import { apiClient } from './client';
import {
  AuditLogsResponse,
  OperationalHealth,
  PlatformMetrics,
  PlatformSummary,
  TenantsResponse,
  PlatformIntegrationItem,
  PlatformIntegrationCreatePayload,
  PlatformIntegrationUpdatePayload,
  PlatformIntegrationTestResult,
  TenantChannelItem,
  CreateTenantChannelPayload,
  UpdateTenantChannelPayload,
  TenantChannelTestResult,
  TenantTasksResponse,
  TenantCapabilitiesResponse,
  TenantErrorsResponse,
  ExecutionTracesResponse,
  ExecutionStepItem,
} from './types';

export const adminApi = {
  async getPlatformOverview(): Promise<PlatformSummary> {
    return apiClient<PlatformSummary>('/api/v1/admin/platform/overview');
  },

  async listTenants(
    limit: number = 50,
    offset: number = 0,
    status?: string,
    search?: string
  ): Promise<TenantsResponse> {
    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString(),
    });
    if (status) params.append('status', status);
    if (search && search.trim()) params.append('search', search.trim());
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

  async getTenantDashboard(tenantId: string): Promise<any> {
    return apiClient<any>(`/api/v1/admin/tenant/dashboard?tenant_id=${tenantId}`);
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

  async listPlatformIntegrations(): Promise<PlatformIntegrationItem[]> {
    return apiClient<PlatformIntegrationItem[]>('/api/v1/admin/integrations');
  },

  async createPlatformIntegration(data: PlatformIntegrationCreatePayload): Promise<PlatformIntegrationItem> {
    return apiClient<PlatformIntegrationItem>('/api/v1/admin/integrations', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async getPlatformIntegration(id: string): Promise<PlatformIntegrationItem> {
    return apiClient<PlatformIntegrationItem>(`/api/v1/admin/integrations/${id}`);
  },

  async updatePlatformIntegration(id: string, data: PlatformIntegrationUpdatePayload): Promise<PlatformIntegrationItem> {
    return apiClient<PlatformIntegrationItem>(`/api/v1/admin/integrations/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  async testPlatformIntegration(id: string): Promise<PlatformIntegrationTestResult> {
    return apiClient<PlatformIntegrationTestResult>(`/api/v1/admin/integrations/${id}/test`, {
      method: 'POST',
    });
  },

  async deletePlatformIntegration(id: string): Promise<{ status: string; id: string }> {
    return apiClient<{ status: string; id: string }>(`/api/v1/admin/integrations/${id}`, {
      method: 'DELETE',
    });
  },

  async getTenantTasks(
    tenantId: string,
    status?: string,
    limit: number = 50,
    offset: number = 0
  ): Promise<TenantTasksResponse> {
    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString(),
    });
    if (status) params.append('status', status);
    return apiClient<TenantTasksResponse>(`/api/v1/admin/platform/tenants/${tenantId}/tasks?${params.toString()}`);
  },

  async getTenantTraces(
    tenantId: string,
    limit: number = 50,
    offset: number = 0
  ): Promise<ExecutionTracesResponse> {
    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString(),
    });
    return apiClient<ExecutionTracesResponse>(`/api/v1/admin/platform/tenants/${tenantId}/traces?${params.toString()}`);
  },

  async getTenantTraceSteps(
    tenantId: string,
    traceId: string,
    format: 'tree' | 'flat' = 'tree'
  ): Promise<ExecutionStepItem[]> {
    return apiClient<ExecutionStepItem[]>(`/api/v1/admin/platform/tenants/${tenantId}/traces/${traceId}/steps?format=${format}`);
  },

  async getTenantCapabilities(tenantId: string): Promise<TenantCapabilitiesResponse> {
    return apiClient<TenantCapabilitiesResponse>(`/api/v1/admin/platform/tenants/${tenantId}/capabilities`);
  },

  async getTenantErrors(tenantId: string, limit: number = 50): Promise<TenantErrorsResponse> {
    return apiClient<TenantErrorsResponse>(`/api/v1/admin/platform/tenants/${tenantId}/errors?limit=${limit}`);
  },

  async getTenantIntegrations(tenantId: string): Promise<any[]> {
    return apiClient<any[]>(`/api/v1/admin/platform/tenants/${tenantId}/integrations`);
  },

  async updateTenantIntegrationStatus(
    tenantId: string,
    integrationId: string,
    status: 'active' | 'inactive' | 'disabled' | 'deleted'
  ): Promise<any> {
    return apiClient(`/api/v1/admin/platform/tenants/${tenantId}/integrations/${integrationId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
  },

  async createTenantIntegration(
    tenantId: string,
    payload: {
      name: string;
      provider: string;
      model: string;
      api_key?: string;
      base_url?: string;
      temperature?: number;
      max_tokens?: number;
      is_default?: boolean;
      extra_params?: Record<string, any>;
    }
  ): Promise<any> {
    return apiClient(`/api/v1/admin/platform/tenants/${tenantId}/integrations`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async testTenantIntegration(
    tenantId: string,
    integrationId: string
  ): Promise<{
    success: boolean;
    provider: string;
    model: string;
    latency_ms?: number;
    error_type?: string | null;
    error_message?: string | null;
  }> {
    return apiClient(`/api/v1/admin/platform/tenants/${tenantId}/integrations/${integrationId}/test`, {
      method: 'POST',
    });
  },

  async getTenantChannels(tenantId: string, status?: string, channelType?: string): Promise<TenantChannelItem[]> {
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    if (channelType) params.append('channel_type', channelType);
    const qs = params.toString() ? `?${params.toString()}` : '';
    return apiClient<TenantChannelItem[]>(`/api/v1/admin/platform/tenants/${tenantId}/channels${qs}`);
  },

  async createTenantChannel(
    tenantId: string,
    payload: CreateTenantChannelPayload
  ): Promise<TenantChannelItem> {
    return apiClient<TenantChannelItem>(`/api/v1/admin/platform/tenants/${tenantId}/channels`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async updateTenantChannel(
    tenantId: string,
    channelId: string,
    payload: UpdateTenantChannelPayload
  ): Promise<TenantChannelItem> {
    return apiClient<TenantChannelItem>(`/api/v1/admin/platform/tenants/${tenantId}/channels/${channelId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  async testTenantChannel(
    tenantId: string,
    channelId: string
  ): Promise<TenantChannelTestResult> {
    return apiClient<TenantChannelTestResult>(`/api/v1/admin/platform/tenants/${tenantId}/channels/${channelId}/test`, {
      method: 'POST',
    });
  },

  async deleteTenantChannel(
    tenantId: string,
    channelId: string
  ): Promise<{ status: string; channel_id: string }> {
    return apiClient<{ status: string; channel_id: string }>(`/api/v1/admin/platform/tenants/${tenantId}/channels/${channelId}`, {
      method: 'DELETE',
    });
  },

  async emergencyCancelTask(
    tenantId: string,
    taskId: string,
    reason: string
  ): Promise<any> {
    return apiClient(`/api/v1/admin/platform/tenants/${tenantId}/tasks/${taskId}/emergency-cancel`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    });
  },

  async emergencyUpdateAgentStatus(
    tenantId: string,
    agentId: string,
    status: 'active' | 'disabled',
    reason: string
  ): Promise<any> {
    return apiClient(`/api/v1/admin/platform/tenants/${tenantId}/agents/${agentId}/emergency-status`, {
      method: 'POST',
      body: JSON.stringify({ status, reason }),
    });
  },

  async emergencyUpdateChannelStatus(
    tenantId: string,
    channelId: string,
    status: 'active' | 'disabled',
    reason: string
  ): Promise<any> {
    return apiClient(`/api/v1/admin/platform/tenants/${tenantId}/channels/${channelId}/emergency-status`, {
      method: 'POST',
      body: JSON.stringify({ status, reason }),
    });
  },
};
