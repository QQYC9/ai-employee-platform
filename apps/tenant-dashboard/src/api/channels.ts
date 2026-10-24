import { apiClient } from './client';
import { Channel } from './types';

export const channelsApi = {
  async listChannels(status?: string, channelType?: string): Promise<Channel[]> {
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    if (channelType) params.append('channel_type', channelType);
    const qs = params.toString() ? `?${params.toString()}` : '';
    return apiClient<Channel[]>(`/api/v1/channels${qs}`);
  },

  async getChannel(channelId: string): Promise<Channel> {
    return apiClient<Channel>(`/api/v1/channels/${channelId}`);
  },

  async registerChannel(data: {
    name: string;
    channel_type: string;
    provider?: string | null;
    config?: Record<string, any>;
  }): Promise<Channel> {
    return apiClient<Channel>('/api/v1/channels', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async updateChannel(
    channelId: string,
    data: {
      name?: string;
      status?: string;
      provider?: string | null;
      config?: Record<string, any>;
    }
  ): Promise<Channel> {
    return apiClient<Channel>(`/api/v1/channels/${channelId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  async deleteChannel(channelId: string): Promise<void> {
    return apiClient<void>(`/api/v1/channels/${channelId}`, {
      method: 'DELETE',
    });
  },

  async testChannel(channelId: string): Promise<{
    connected: boolean;
    status: string;
    latency_ms: number;
    error?: string | null;
    details?: Record<string, any>;
  }> {
    return apiClient(`/api/v1/channels/${channelId}/test`, {
      method: 'POST',
    });
  },
};
