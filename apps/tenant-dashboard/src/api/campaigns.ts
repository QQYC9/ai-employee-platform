import { apiClient } from './client';
import { Campaign, CampaignRecipient } from './types';

export interface CreateCampaignInput {
  name: string;
  message_template: string;
  goal?: string;
  channel_id?: string;
  audience_filter?: Record<string, any>;
  scheduled_at?: string;
  requires_approval?: boolean;
  rate_limit_per_minute?: number;
  batch_size?: number;
  metadata_json?: Record<string, any>;
}

export interface UpdateCampaignInput {
  name?: string;
  message_template?: string;
  goal?: string;
  channel_id?: string;
  audience_filter?: Record<string, any>;
  scheduled_at?: string;
  requires_approval?: boolean;
  rate_limit_per_minute?: number;
  batch_size?: number;
  metadata_json?: Record<string, any>;
}

export interface ProactiveTriggerInput {
  customer_id: string;
  channel_id: string;
  notification_type: 'appointment_reminder' | 'service_followup' | 'inactivity_reengagement' | 'custom';
  content?: string;
  appointment_time?: string;
  service_name?: string;
  feedback_url?: string;
  offer_details?: string;
  requires_approval?: boolean;
}

export interface ListCampaignsResponse {
  items: Campaign[];
  limit: number;
  offset: number;
  total: number;
}

export interface ListRecipientsResponse {
  items: CampaignRecipient[];
  limit: number;
  offset: number;
  total: number;
}

export const campaignsApi = {
  async listCampaigns(status?: string, limit = 50, offset = 0): Promise<ListCampaignsResponse> {
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    params.append('limit', String(limit));
    params.append('offset', String(offset));
    return apiClient<ListCampaignsResponse>(`/api/v1/campaigns?${params.toString()}`);
  },

  async getCampaign(id: string): Promise<Campaign> {
    return apiClient<Campaign>(`/api/v1/campaigns/${id}`);
  },

  async createCampaign(data: CreateCampaignInput): Promise<Campaign> {
    return apiClient<Campaign>('/api/v1/campaigns', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async updateCampaign(id: string, data: UpdateCampaignInput): Promise<Campaign> {
    return apiClient<Campaign>(`/api/v1/campaigns/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  async scheduleCampaign(id: string, scheduledAt: string): Promise<Campaign> {
    return apiClient<Campaign>(`/api/v1/campaigns/${id}/schedule`, {
      method: 'POST',
      body: JSON.stringify({ scheduled_at: scheduledAt }),
    });
  },

  async startCampaign(id: string): Promise<Campaign> {
    return apiClient<Campaign>(`/api/v1/campaigns/${id}/start`, {
      method: 'POST',
    });
  },

  async pauseCampaign(id: string): Promise<Campaign> {
    return apiClient<Campaign>(`/api/v1/campaigns/${id}/pause`, {
      method: 'POST',
    });
  },

  async resumeCampaign(id: string): Promise<Campaign> {
    return apiClient<Campaign>(`/api/v1/campaigns/${id}/resume`, {
      method: 'POST',
    });
  },

  async cancelCampaign(id: string): Promise<Campaign> {
    return apiClient<Campaign>(`/api/v1/campaigns/${id}/cancel`, {
      method: 'POST',
    });
  },

  async listRecipients(id: string, status?: string, limit = 50, offset = 0): Promise<ListRecipientsResponse> {
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    params.append('limit', String(limit));
    params.append('offset', String(offset));
    return apiClient<ListRecipientsResponse>(`/api/v1/campaigns/${id}/recipients?${params.toString()}`);
  },

  async triggerProactive(data: ProactiveTriggerInput): Promise<any> {
    return apiClient<any>('/api/v1/campaigns/proactive/trigger', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
};
