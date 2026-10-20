import React from 'react';
import { LucideIcon } from 'lucide-react';

export interface StatCardProps {
  title: string;
  value: string | number;
  icon: LucideIcon;
  subtitle?: string;
  subtext?: string;
  badge?: React.ReactNode;
  trend?: {
    value: string;
    isPositive: boolean;
  };
  color?: 'emerald' | 'blue' | 'purple' | 'amber' | 'rose' | 'slate' | string;
  colorScheme?: 'emerald' | 'blue' | 'purple' | 'amber' | 'rose' | 'slate';
}

export const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  icon: Icon,
  subtitle,
  subtext,
  badge,
  trend,
  color,
  colorScheme = 'emerald',
}) => {
  const chosenScheme = (color || colorScheme) as
    | 'emerald'
    | 'blue'
    | 'purple'
    | 'amber'
    | 'rose'
    | 'slate';

  const schemeStyles = {
    emerald: {
      bg: 'from-emerald-500/10 to-teal-500/5',
      border: 'border-emerald-500/20 hover:border-emerald-500/40',
      iconBg: 'bg-emerald-500/20 text-emerald-400',
    },
    blue: {
      bg: 'from-blue-500/10 to-cyan-500/5',
      border: 'border-blue-500/20 hover:border-blue-500/40',
      iconBg: 'bg-blue-500/20 text-blue-400',
    },
    purple: {
      bg: 'from-purple-500/10 to-indigo-500/5',
      border: 'border-purple-500/20 hover:border-purple-500/40',
      iconBg: 'bg-purple-500/20 text-purple-400',
    },
    amber: {
      bg: 'from-amber-500/10 to-yellow-500/5',
      border: 'border-amber-500/20 hover:border-amber-500/40',
      iconBg: 'bg-amber-500/20 text-amber-400',
    },
    rose: {
      bg: 'from-rose-500/10 to-pink-500/5',
      border: 'border-rose-500/20 hover:border-rose-500/40',
      iconBg: 'bg-rose-500/20 text-rose-400',
    },
    slate: {
      bg: 'from-slate-500/10 to-slate-700/5',
      border: 'border-slate-800 hover:border-slate-700',
      iconBg: 'bg-slate-800 text-slate-300',
    },
  };

  const style = schemeStyles[chosenScheme] || schemeStyles.emerald;

  return (
    <div
      className={`relative overflow-hidden rounded-2xl border bg-gradient-to-br ${style.bg} ${style.border} p-5 backdrop-blur shadow-lg transition duration-200`}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-400 tracking-wide">{title}</span>
        <div className="flex items-center gap-2">
          {badge}
          <div className={`p-2.5 rounded-xl ${style.iconBg}`}>
            <Icon className="w-5 h-5" />
          </div>
        </div>
      </div>

      <div className="mt-3 flex items-baseline gap-2">
        <span className="text-2xl font-black text-white tracking-tight">{value}</span>
        {trend && (
          <span
            className={`text-xs font-bold ${
              trend.isPositive ? 'text-emerald-400' : 'text-rose-400'
            }`}
          >
            {trend.value}
          </span>
        )}
      </div>

      {(subtitle || subtext) && (
        <p className="mt-1 text-xs text-slate-400 leading-relaxed">
          {subtitle || subtext}
        </p>
      )}
    </div>
  );
};
