import { describe, it, expect, vi, beforeEach } from 'vitest';
import { apiClient, ApiError, authStorage } from '../api/client';

describe('API Client', () => {
  beforeEach(() => {
    authStorage.clear();
    vi.restoreAllMocks();
  });

  it('attaches Authorization header when token exists', async () => {
    authStorage.setToken('test-access-token');

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: 'ok' }),
    });
    global.fetch = fetchMock;

    await apiClient('/api/v1/health');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const headers = fetchMock.mock.calls[0][1]?.headers;
    expect(headers.get('Authorization')).toBe('Bearer test-access-token');
  });

  it('throws ApiError with message and status on failure', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: 'المورد المطلوب غير موجود' }),
    });

    await expect(apiClient('/api/v1/tasks/unknown-id')).rejects.toThrow(ApiError);
  });
});
