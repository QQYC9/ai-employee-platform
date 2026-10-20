import { apiClient } from './client';
import {
  BusinessBrain,
  Tenant,
  TenantBudgetStatus,
  TenantDashboardData,
  TenantMetrics,
} from './types';

export const tenantApi = {
  async getDashboard(): Promise<TenantDashboardData> {
    return apiClient<TenantDashboardData>('/api/v1/admin/tenant/dashboard');
  },

  async getTenant(): Promise<Tenant> {
    return apiClient<Tenant>('/api/v1/tenants/me');
  },

  async updateTenant(name: string): Promise<Tenant> {
    return apiClient<Tenant>('/api/v1/tenants/me', {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    });
  },

  async getBusinessBrain(): Promise<BusinessBrain> {
    return apiClient<BusinessBrain>('/api/v1/tenants/me/brain');
  },

  async updateBusinessBrain(data: Partial<BusinessBrain>): Promise<BusinessBrain> {
    return apiClient<BusinessBrain>('/api/v1/tenants/me/brain', {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  async getBudget(): Promise<TenantBudgetStatus> {
    return apiClient<TenantBudgetStatus>('/api/v1/admin/tenant/budget');
  },

  async getMetrics(timeWindowDays: number = 30): Promise<TenantMetrics> {
    return apiClient<TenantMetrics>(
      `/api/v1/admin/tenant/metrics?time_window_days=${timeWindowDays}`
    );
  },
};
