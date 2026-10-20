import React from 'react';
import { useAuth } from '../../context/AuthContext';
import { LogOut, User as UserIcon, Shield, Radio, Menu } from 'lucide-react';

interface TenantTopbarProps {
  sidebarOpen: boolean;
  onMobileToggle: () => void;
  pageTitle?: string;
  tenantName?: string;
}

export const TenantTopbar: React.FC<TenantTopbarProps> = ({
  sidebarOpen,
  onMobileToggle,
  pageTitle,
  tenantName,
}) => {
  const { user, logout } = useAuth();

  const getRoleLabel = (role?: string) => {
    switch ((role || '').toLowerCase()) {
      case 'tenant_owner':
      case 'owner':
        return 'مالك الشركة';
      case 'tenant_admin':
      case 'admin':
        return 'مدير النظام';
      default:
        return 'مستخدم معتمد';
    }
  };

  return (
    <header
      className={`fixed top-0 left-0 z-30 h-16 border-b border-slate-800 bg-slate-950/80 backdrop-blur transition-all duration-300 flex items-center justify-between px-4 sm:px-6 ${
        sidebarOpen ? 'right-0 md:right-64' : 'right-0 md:right-20'
      }`}
    >
      {/* Title & Mobile Toggle */}
      <div className="flex items-center gap-3">
        <button
          onClick={onMobileToggle}
          className="md:hidden p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
          title="فتح القائمة"
        >
          <Menu className="w-5 h-5" />
        </button>

        <div>
          <h1 className="text-base sm:text-lg font-bold text-white tracking-tight flex items-center gap-2">
            <span>{pageTitle || 'لوحة عمليات الشركة'}</span>
            {tenantName && (
              <span className="hidden sm:inline-block text-xs font-normal text-slate-400 border-r border-slate-700 pr-2 mr-2">
                {tenantName}
              </span>
            )}
          </h1>
        </div>

        <span className="hidden lg:inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-950/80 text-emerald-400 border border-emerald-800">
          <Radio className="w-3 h-3 animate-pulse" />
          <span>الخدمات متصلة</span>
        </span>
      </div>

      {/* User Actions */}
      <div className="flex items-center gap-3 sm:gap-4">
        {user && (
          <div className="flex items-center gap-2.5 border-l border-slate-800 pl-3 sm:pl-4">
            <div className="w-8 h-8 sm:w-9 sm:h-9 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-emerald-400 font-bold text-xs sm:text-sm">
              {user.name ? user.name[0].toUpperCase() : <UserIcon className="w-4 h-4" />}
            </div>
            <div className="hidden sm:flex flex-col text-right">
              <span className="text-xs sm:text-sm font-semibold text-white leading-tight">
                {user.name}
              </span>
              <span className="text-[10px] sm:text-[11px] text-slate-400 flex items-center gap-1">
                <Shield className="w-3 h-3 text-emerald-400" />
                {getRoleLabel(user.role)}
              </span>
            </div>
          </div>
        )}

        <button
          onClick={logout}
          className="flex items-center gap-1.5 px-2.5 sm:px-3 py-1.5 rounded-lg text-xs sm:text-sm font-medium text-rose-400 hover:bg-rose-950/40 hover:text-rose-300 border border-rose-900/40 transition"
          title="تسجيل الخروج"
        >
          <LogOut className="w-4 h-4" />
          <span className="hidden xs:inline">خروج</span>
        </button>
      </div>
    </header>
  );
};
