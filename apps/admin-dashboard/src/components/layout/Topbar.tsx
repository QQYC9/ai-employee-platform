import React from 'react';
import { useAuth } from '../../context/AuthContext';
import { LogOut, User as UserIcon, Shield, Radio } from 'lucide-react';

interface TopbarProps {
  sidebarOpen: boolean;
  pageTitle?: string;
}

export const Topbar: React.FC<TopbarProps> = ({ sidebarOpen, pageTitle }) => {
  const { user, logout } = useAuth();

  return (
    <header
      className={`fixed top-0 left-0 z-30 h-16 border-b border-slate-800 bg-slate-950/80 backdrop-blur transition-all duration-300 flex items-center justify-between px-6 ${
        sidebarOpen ? 'right-64' : 'right-20'
      }`}
    >
      {/* Title */}
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-bold text-white tracking-tight">
          {pageTitle || 'لوحة تحكم المشرف العام'}
        </h1>
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-950/80 text-emerald-400 border border-emerald-800">
          <Radio className="w-3 h-3 animate-pulse" />
          <span>الخادم متصل</span>
        </span>
      </div>

      {/* User Actions */}
      <div className="flex items-center gap-4">
        {user && (
          <div className="flex items-center gap-3 border-l border-slate-800 pl-4">
            <div className="w-9 h-9 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-emerald-400 font-bold">
              {user.name ? user.name[0].toUpperCase() : <UserIcon className="w-4 h-4" />}
            </div>
            <div className="flex flex-col text-right">
              <span className="text-sm font-semibold text-white leading-tight">
                {user.name || 'مدير النظام'}
              </span>
              <span className="text-[11px] text-slate-400 flex items-center gap-1">
                <Shield className="w-3 h-3 text-emerald-400" />
                {user.role === 'platform_admin' ? 'مدير المنصة العام' : user.role}
              </span>
            </div>
          </div>
        )}

        <button
          onClick={logout}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium text-rose-400 hover:bg-rose-950/40 hover:text-rose-300 border border-rose-900/40 transition"
          title="تسجيل الخروج"
        >
          <LogOut className="w-4 h-4" />
          <span>خروج</span>
        </button>
      </div>
    </header>
  );
};
