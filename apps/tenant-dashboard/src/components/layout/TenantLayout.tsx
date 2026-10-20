import React, { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { TenantSidebar } from './TenantSidebar';
import { TenantTopbar } from './TenantTopbar';
import { tenantApi } from '../../api/tenant';
import { Tenant } from '../../api/types';

export const TenantLayout: React.FC = () => {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const location = useLocation();

  useEffect(() => {
    async function loadTenant() {
      try {
        const t = await tenantApi.getTenant();
        setTenant(t);
      } catch {
        // Fallback gracefully
      }
    }
    loadTenant();
  }, []);

  // Close mobile drawer on route change
  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);

  const getPageTitle = () => {
    switch (location.pathname) {
      case '/':
        return 'نظرة عامة والعمليات';
      case '/agents':
        return 'الموظفون الرقميون والوكلاء';
      case '/tasks':
        return 'سجل ومتابعة المهام';
      case '/channels':
        return 'قنوات التواصل والرسائل';
      case '/usage':
        return 'الاستخدام وحصة الرموز';
      case '/settings':
        return 'إعدادات الشركة والملف التشغيلي';
      default:
        return 'لوحة عمليات الشركة';
    }
  };

  return (
    <div className="min-h-screen bg-[#090d16] text-slate-100 flex" dir="rtl">
      {/* Desktop Sidebar */}
      <div className="hidden md:block">
        <TenantSidebar
          isOpen={sidebarOpen}
          onToggle={() => setSidebarOpen(!sidebarOpen)}
          tenantName={tenant?.name}
          tenantSlug={tenant?.slug}
        />
      </div>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div className="fixed inset-0 z-50 md:hidden bg-slate-950/80 backdrop-blur-sm">
          <div className="w-64 h-full bg-slate-950 border-l border-slate-800 shadow-2xl">
            <TenantSidebar
              isOpen={true}
              onToggle={() => setMobileMenuOpen(false)}
              tenantName={tenant?.name}
              tenantSlug={tenant?.slug}
            />
          </div>
        </div>
      )}

      {/* Main Content Area */}
      <div
        className={`flex-1 flex flex-col min-w-0 transition-all duration-300 ${
          sidebarOpen ? 'md:mr-64' : 'md:mr-20'
        }`}
      >
        <TenantTopbar
          sidebarOpen={sidebarOpen}
          onMobileToggle={() => setMobileMenuOpen(!mobileMenuOpen)}
          pageTitle={getPageTitle()}
          tenantName={tenant?.name}
        />

        <main className="flex-1 p-4 sm:p-6 lg:p-8 mt-16 max-w-7xl mx-auto w-full">
          <Outlet />
        </main>
      </div>
    </div>
  );
};
