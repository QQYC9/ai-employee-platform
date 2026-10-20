import { apiClient } from './client';
import { Agent } from './types';

export const agentsApi = {
  async listAgents(): Promise<Agent[]> {
    return apiClient<Agent[]>('/api/v1/agents');
  },

  async getAgent(agentId: string): Promise<Agent> {
    return apiClient<Agent>(`/api/v1/agents/${agentId}`);
  },

  async createAgent(data: { name: string; agent_type?: string }): Promise<Agent> {
    return apiClient<Agent>('/api/v1/agents', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async updateAgent(
    agentId: string,
    data: { name?: string; status?: string }
  ): Promise<Agent> {
    return apiClient<Agent>(`/api/v1/agents/${agentId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },
};
