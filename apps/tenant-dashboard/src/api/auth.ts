import { apiClient, authStorage } from './client';
import { TokenResponse, User } from './types';

export const authApi = {
  async login(email: string, password: string): Promise<TokenResponse> {
    const res = await apiClient<TokenResponse>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    authStorage.setToken(res.access_token);
    authStorage.setRefreshToken(res.refresh_token);
    authStorage.setUser(res.user);
    return res;
  },

  async getMe(): Promise<User> {
    const res = await apiClient<User>('/api/v1/auth/me');
    authStorage.setUser(res);
    return res;
  },

  logout() {
    authStorage.clear();
    window.location.href = '/login';
  },

  getCurrentUser(): User | null {
    return authStorage.getUser();
  },

  isAuthenticated(): boolean {
    return !!authStorage.getToken();
  },
};
