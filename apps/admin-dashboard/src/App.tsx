import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { AdminLayout } from './components/layout/AdminLayout';
import { LoginPage } from './pages/LoginPage';
import { DashboardPage } from './pages/DashboardPage';
import { TenantsPage } from './pages/TenantsPage';
import { TenantDetailPage } from './pages/TenantDetailPage';
import { AgentsTasksPage } from './pages/AgentsTasksPage';
import { MonitoringPage } from './pages/MonitoringPage';
import { PlatformIntegrationsPage } from './pages/PlatformIntegrationsPage';
import { SettingsPage } from './pages/SettingsPage';
import { LoadingState } from './components/common/LoadingState';

const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <LoadingState message="جاري التحقق من الجلسة..." />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
};

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />

          <Route
            path="/"
            element={
              <ProtectedRoute>
                <AdminLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<DashboardPage />} />
            <Route path="tenants" element={<TenantsPage />} />
            <Route path="tenants/:tenantId" element={<TenantDetailPage />} />
            <Route path="agents-tasks" element={<AgentsTasksPage />} />
            <Route path="monitoring" element={<MonitoringPage />} />
            <Route path="integrations" element={<PlatformIntegrationsPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
};

export default App;
