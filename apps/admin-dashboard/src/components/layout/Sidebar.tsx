import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Building2,
  Bot,
  Activity,
  KeyRound,
  Settings,
  ShieldCheck,
  ChevronLeft,
} from 'lucide-react';

interface SidebarProps {
  isOpen: boolean;
  onToggle: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ isOpen, onToggle }) => {
  const navItems = [
    {
      to: '/',
      label: 'لوحة المعلومات',
      icon: LayoutDashboard,
      description: 'نظرة شاملة ومؤشرات المنصة',
    },
    {
      to: '/tenants',
      label: 'المستأجرون والعملاء',
      icon: Building2,
      description: 'إدارة الحصص والحالات والتفعيل',
    },
    {
      to: '/agents-tasks',
      label: 'الوكلاء والمهام',
      icon: Bot,
      description: 'متابعة الوكلاء وتنفيذ المهام',
    },
    {
      to: '/monitoring',
      label: 'مراقبة النظام',
      icon: Activity,
      description: 'صندوق الصادر والأخطاء والتدقيق',
    },
    {
      to: '/integrations',
      label: 'تكاملات ومزودو المنصة',
      icon: KeyRound,
      description: 'إدارة مفاتيح API ومزودي الذكاء الاصطناعي',
    },
    {
      to: '/settings',
      label: 'إعدادات المنصة',
      icon: Settings,
      description: 'تكوين البيئة وقيود الاستخدام',
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
          <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-600 to-teal-400 text-slate-950 font-bold shadow-lg shadow-emerald-950/50 flex-shrink-0">
            <Bot className="w-6 h-6" />
          </div>
          {isOpen && (
            <div className="flex flex-col truncate">
              <span className="font-extrabold text-white text-base tracking-wide truncate">
                AI Employee
              </span>
              <span className="text-[10px] text-emerald-400 font-semibold tracking-wider uppercase flex items-center gap-1">
                <ShieldCheck className="w-3 h-3" /> لوحة الإدارة العليا
              </span>
            </div>
          )}
        </div>
        <button
          onClick={onToggle}
          className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-900 border border-slate-800 transition"
          title={isOpen ? 'طي القائمة' : 'توسيع القائمة'}
        >
          <ChevronLeft
            className={`w-4 h-4 transition-transform duration-300 ${
              isOpen ? '' : 'rotate-180'
            }`}
          />
        </button>
      </div>

      {/* Navigation */}
      <div className="flex-1 py-6 px-3 space-y-1.5 overflow-y-auto">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-3 rounded-xl transition duration-150 group relative ${
                  isActive
                    ? 'bg-emerald-600/10 text-emerald-400 font-semibold border border-emerald-500/20 shadow-sm'
                    : 'text-slate-400 hover:text-slate-100 hover:bg-slate-900/60 border border-transparent'
                }`
              }
            >
              <Icon className="w-5 h-5 flex-shrink-0 transition group-hover:scale-110" />
              {isOpen && (
                <div className="flex flex-col text-right">
                  <span className="text-sm leading-tight">{item.label}</span>
                </div>
              )}
              {!isOpen && (
                <div className="absolute right-full mr-2 hidden px-2.5 py-1.5 bg-slate-900 text-white text-xs rounded-lg border border-slate-700 shadow-xl group-hover:block whitespace-nowrap z-50">
                  {item.label}
                </div>
              )}
            </NavLink>
          );
        })}
      </div>

      {/* Footer Info */}
      {isOpen && (
        <div className="p-4 border-t border-slate-900 text-center">
          <div className="rounded-xl bg-slate-900/50 p-3 border border-slate-800/80">
            <span className="text-[11px] text-slate-400 block">الإصدار: v0.1.0</span>
            <span className="text-[10px] text-emerald-400 font-medium">البيئة: Staging معزولة</span>
          </div>
        </div>
      )}
    </aside>
  );
};
