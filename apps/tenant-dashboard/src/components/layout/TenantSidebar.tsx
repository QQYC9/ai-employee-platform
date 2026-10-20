import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Bot,
  ListTodo,
  Radio,
  Coins,
  Building2,
  ChevronLeft,
  Sparkles,
} from 'lucide-react';

interface TenantSidebarProps {
  isOpen: boolean;
  onToggle: () => void;
  tenantName?: string;
  tenantSlug?: string;
}

export const TenantSidebar: React.FC<TenantSidebarProps> = ({
  isOpen,
  onToggle,
  tenantName = 'شركتي',
  tenantSlug,
}) => {
  const navItems = [
    {
      to: '/',
      label: 'نظرة عامة',
      icon: LayoutDashboard,
      description: 'ملخص العمليات ومؤشرات الأداء',
    },
    {
      to: '/agents',
      label: 'الموظفون الرقميون',
      icon: Bot,
      description: 'الوكلاء وحالات العمل والمهام',
    },
    {
      to: '/tasks',
      label: 'سجل المهام',
      icon: ListTodo,
      description: 'متابعة التنفيذ وإعادة المحاولة',
    },
    {
      to: '/channels',
      label: 'قنوات التواصل',
      icon: Radio,
      description: 'واتساب وواجهات الربط والرسائل',
    },
    {
      to: '/usage',
      label: 'الاستخدام والميزانية',
      icon: Coins,
      description: 'رصيد الرموز وحدود الاستهلاك',
    },
    {
      to: '/settings',
      label: 'إعدادات الشركة',
      icon: Building2,
      description: 'بيانات الشركة والملف التشغيلي',
    },
  ];

  return (
    <aside
      className={`fixed top-0 right-0 z-40 h-screen transition-all duration-300 ease-in-out border-l border-slate-800 bg-slate-950 flex flex-col ${
        isOpen ? 'w-64' : 'w-20'
      }`}
    >
      {/* Brand Header */}
      <div className="flex items-center justify-between h-16 px-4 border-b border-slate-800 bg-slate-950/80">
        <div className="flex items-center gap-3 overflow-hidden">
          <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-600 to-teal-400 flex items-center justify-center text-slate-950 font-black shadow-lg shadow-emerald-950/40">
            <Sparkles className="w-5 h-5 text-slate-950" />
          </div>
          {isOpen && (
            <div className="flex flex-col overflow-hidden text-right">
              <span className="text-sm font-black text-white truncate">
                {tenantName}
              </span>
              <span className="text-[11px] font-mono text-emerald-400 truncate">
                {tenantSlug ? `@${tenantSlug}` : 'بوابة العميل'}
              </span>
            </div>
          )}
        </div>

        <button
          onClick={onToggle}
          className="hidden md:flex p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
          title={isOpen ? 'طي القائمة' : 'توسيع القائمة'}
        >
          <ChevronLeft
            className={`w-4 h-4 transition-transform duration-300 ${
              !isOpen ? 'rotate-180' : ''
            }`}
          />
        </button>
      </div>

      {/* Nav List */}
      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-1.5">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-semibold transition group ${
                  isActive
                    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                    : 'text-slate-400 hover:text-white hover:bg-slate-900 border border-transparent'
                }`
              }
              title={!isOpen ? item.label : undefined}
            >
              <Icon className="w-5 h-5 flex-shrink-0 group-hover:scale-105 transition" />
              {isOpen && (
                <div className="flex flex-col text-right overflow-hidden">
                  <span className="truncate leading-tight">{item.label}</span>
                  <span className="text-[10px] text-slate-400 truncate mt-0.5 font-normal">
                    {item.description}
                  </span>
                </div>
              )}
            </NavLink>
          );
        })}
      </nav>

      {/* Footer Branding */}
      {isOpen && (
        <div className="p-4 border-t border-slate-800/80 bg-slate-950/40 text-center">
          <p className="text-[11px] text-slate-400">منصة الموظف الرقمي الذكي</p>
          <p className="text-[10px] text-emerald-500/80 font-mono mt-0.5">Enterprise Client Portal</p>
        </div>
      )}
    </aside>
  );
};
