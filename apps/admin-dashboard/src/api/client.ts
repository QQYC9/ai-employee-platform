export class ApiError extends Error {
  status: number;
  data: any;

  constructor(message: string, status: number, data?: any) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

const TOKEN_KEY = 'ai_employee_token';
const REFRESH_KEY = 'ai_employee_refresh';
const USER_KEY = 'ai_employee_user';

export const authStorage = {
  getToken: () => localStorage.getItem(TOKEN_KEY),
  setToken: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  getRefreshToken: () => localStorage.getItem(REFRESH_KEY),
  setRefreshToken: (token: string) => localStorage.setItem(REFRESH_KEY, token),
  getUser: () => {
    const raw = localStorage.getItem(USER_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  },
  setUser: (user: any) => localStorage.setItem(USER_KEY, JSON.stringify(user)),
  clear: () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USER_KEY);
  },
};

let isRefreshing = false;
let refreshSubscribers: ((token: string) => void)[] = [];

function onRefreshed(token: string) {
  refreshSubscribers.forEach((cb) => cb(token));
  refreshSubscribers = [];
}

const API_BASE = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE_URL ? import.meta.env.VITE_API_BASE_URL : '').replace(/\/$/, '');

export function resolveApiUrl(endpoint: string): string {
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/api/v1/${endpoint}`;
  return `${API_BASE}${cleanEndpoint}`;
}

export async function apiClient<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const token = authStorage.getToken();
  const headers = new Headers(options.headers || {});

  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const url = resolveApiUrl(endpoint);

  let response = await fetch(url, {
    ...options,
    headers,
  });

  // Handle Token Refresh on 401 Unauthorized
  if (response.status === 401 && !endpoint.includes('/auth/login') && !endpoint.includes('/auth/refresh')) {
    const refreshToken = authStorage.getRefreshToken();
    if (refreshToken) {
      if (!isRefreshing) {
        isRefreshing = true;
        try {
          const refreshRes = await fetch(resolveApiUrl('/api/v1/auth/refresh'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refreshToken }),
          });

          if (refreshRes.ok) {
            const data = await refreshRes.json();
            authStorage.setToken(data.access_token);
            if (data.refresh_token) {
              authStorage.setRefreshToken(data.refresh_token);
            }
            onRefreshed(data.access_token);
          } else {
            authStorage.clear();
            window.location.href = '/login';
            throw new ApiError('انتهت صلاحية الجلسة، يرجى تسجيل الدخول مجددًا', 401);
          }
        } catch (err) {
          authStorage.clear();
          window.location.href = '/login';
          throw err;
        } finally {
          isRefreshing = false;
        }
      }

      // Retry request with new token
      return new Promise((resolve, reject) => {
        refreshSubscribers.push(async (newToken: string) => {
          try {
            headers.set('Authorization', `Bearer ${newToken}`);
            const retryRes = await fetch(url, { ...options, headers });
            if (!retryRes.ok) {
              const errData = await retryRes.json().catch(() => null);
              reject(new ApiError(errData?.detail || 'حدث خطأ في الخادم', retryRes.status, errData));
            } else {
              resolve(await retryRes.json());
            }
          } catch (e) {
            reject(e);
          }
        });
      });
    } else {
      authStorage.clear();
      window.location.href = '/login';
      throw new ApiError('غير مصرح لك، يرجى تسجيل الدخول', 401);
    }
  }

  if (!response.ok) {
    let errorDetail = 'حدث خطأ أثناء معالجة الطلب';
    let data = null;
    try {
      data = await response.json();
      if (typeof data.detail === 'string') {
        errorDetail = data.detail;
      } else if (Array.isArray(data.detail)) {
        errorDetail = data.detail.map((d: any) => d.msg || JSON.stringify(d)).join(', ');
      }
    } catch {
      // response is not json
    }
    throw new ApiError(errorDetail, response.status, data);
  }

  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}
