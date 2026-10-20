import React from 'react';
import { LucideIcon } from 'lucide-react';

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: LucideIcon;
  trend?: {
    value: string;
    isPositive?: boolean;
  };
  color?: 'emerald' | 'blue' | 'amber' | 'rose' | 'purple' | 'slate';
  badge?: {
    label: string;
    variant: 'healthy' | 'degraded' | 'warning' | 'critical';
  };
}

export const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  subtitle,
  icon: Icon,
  trend,
  color = 'emerald',
  badge,
}) => {
  const colorMap = {
    emerald: 'text-emerald-400 bg-emerald-950/60 border-emerald-800/50',
    blue: 'text-blue-400 bg-blue-950/60 border-blue-800/50',
    amber: 'text-amber-400 bg-amber-950/60 border-amber-800/50',
    rose: 'text-rose-400 bg-rose-950/60 border-rose-800/50',
    purple: 'text-purple-400 bg-purple-950/60 border-purple-800/50',
    slate: 'text-slate-400 bg-slate-900/60 border-slate-800/50',
  };

  return (
    <div className="relative overflow-hidden rounded-xl border border-slate-800 bg-slate-900/70 p-5 shadow-lg backdrop-blur hover:border-slate-700 transition duration-200">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-400">{title}</span>
        <div className={`rounded-lg p-2.5 border ${colorMap[color]}`}>
          <Icon className="w-5 h-5" />
        </div>
      </div>

      <div className="mt-4 flex items-baseline justify-between gap-2">
        <span className="text-2xl font-bold tracking-tight text-white">{value}</span>
        {badge && (
          <span
            className={`text-xs px-2 py-0.5 rounded-full font-medium ${
              badge.variant === 'healthy'
                ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                : badge.variant === 'warning'
                ? 'bg-amber-950 text-amber-400 border border-amber-800'
                : 'bg-rose-950 text-rose-400 border border-rose-800'
            }`}
          >
            {badge.label}
          </span>
        )}
      </div>

      {(subtitle || trend) && (
        <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">
          {trend && (
            <span
              className={`font-semibold ${
                trend.isPositive ? 'text-emerald-400' : 'text-rose-400'
              }`}
            >
              {trend.value}
            </span>
          )}
          {subtitle && <span>{subtitle}</span>}
        </div>
      )}
    </div>
  );
};
