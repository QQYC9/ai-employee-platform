import { apiClient } from './client';
import { AgentItem, TaskItem } from './types';

export const tasksApi = {
  async listTasks(): Promise<TaskItem[]> {
    return apiClient<TaskItem[]>('/api/v1/tasks');
  },

  async getTask(taskId: string): Promise<TaskItem> {
    return apiClient<TaskItem>(`/api/v1/tasks/${taskId}`);
  },

  async retryTask(taskId: string, reason?: string): Promise<TaskItem> {
    return apiClient<TaskItem>(`/api/v1/tasks/${taskId}/retry`, {
      method: 'POST',
      body: JSON.stringify({ reason: reason || 'Manual retry from Super Admin dashboard' }),
    });
  },

  async cancelTask(taskId: string, reason?: string): Promise<TaskItem> {
    return apiClient<TaskItem>(`/api/v1/tasks/${taskId}/cancel`, {
      method: 'POST',
      body: JSON.stringify({ reason: reason || 'Cancelled from Super Admin dashboard' }),
    });
  },

  async listAgents(): Promise<AgentItem[]> {
    return apiClient<AgentItem[]>('/api/v1/agents');
  },

  async getAgent(agentId: string): Promise<AgentItem> {
    return apiClient<AgentItem>(`/api/v1/agents/${agentId}`);
  },
};
