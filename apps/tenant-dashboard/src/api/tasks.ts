import { apiClient } from './client';
import { Task } from './types';

export const tasksApi = {
  async listTasks(status?: string, agentId?: string): Promise<Task[]> {
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    if (agentId) params.append('agent_id', agentId);
    const qs = params.toString() ? `?${params.toString()}` : '';
    return apiClient<Task[]>(`/api/v1/tasks${qs}`);
  },

  async getTask(taskId: string): Promise<Task> {
    return apiClient<Task>(`/api/v1/tasks/${taskId}`);
  },

  async createTask(data: {
    title: string;
    objective: string;
    agent_id?: string | null;
    priority?: string;
  }): Promise<Task> {
    return apiClient<Task>('/api/v1/tasks', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async retryTask(taskId: string, reason?: string): Promise<Task> {
    return apiClient<Task>(`/api/v1/tasks/${taskId}/retry`, {
      method: 'POST',
      body: JSON.stringify({ reason: reason || 'Manual retry from tenant dashboard' }),
    });
  },

  async cancelTask(taskId: string, reason?: string): Promise<Task> {
    return apiClient<Task>(`/api/v1/tasks/${taskId}/cancel`, {
      method: 'POST',
      body: JSON.stringify({ reason: reason || 'Cancelled from tenant dashboard' }),
    });
  },
};
