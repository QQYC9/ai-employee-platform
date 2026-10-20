import React from 'react';

export interface BadgeProps {
  status?: string;
  variant?: 'success' | 'danger' | 'warning' | 'info' | 'neutral' | string;
  label?: string;
  children?: React.ReactNode;
  className?: string;
}

export const Badge: React.FC<BadgeProps> = ({
  status,
  variant,
  label,
  children,
  className = '',
}) => {
  const normKey = ((variant || status || '') as string).toLowerCase().trim();

  let styles = 'bg-slate-800 text-slate-300 border-slate-700';
  let defaultLabel = label || status || '';

  switch (normKey) {
    case 'active':
    case 'completed':
    case 'healthy':
    case 'success':
    case 'normal':
    case 'none':
      styles = 'bg-emerald-950/70 text-emerald-300 border-emerald-800/80';
      if (!label && !children) defaultLabel = 'نشط / مكتمل';
      break;

    case 'pending':
    case 'in_progress':
    case 'running':
    case 'processing':
    case 'waiting_approval':
    case 'info':
      styles = 'bg-blue-950/70 text-blue-300 border-blue-800/80 animate-pulse';
      if (!label && !children) defaultLabel = 'قيد المعالجة';
      break;

    case 'warning':
    case 'degraded':
      styles = 'bg-amber-950/70 text-amber-300 border-amber-800/80';
      if (!label && !children) defaultLabel = 'تحذير';
      break;

    case 'failed':
    case 'cancelled':
    case 'suspended':
    case 'unhealthy':
    case 'critical':
    case 'exceeded':
    case 'error':
    case 'danger':
      styles = 'bg-rose-950/70 text-rose-300 border-rose-800/80';
      if (!label && !children) defaultLabel = 'فشل / معلق';
      break;

    case 'inactive':
    case 'neutral':
    case 'unknown':
      styles = 'bg-slate-900 text-slate-400 border-slate-800';
      if (!label && !children) defaultLabel = 'غير نشط';
      break;

    default:
      styles = 'bg-slate-900 text-slate-300 border-slate-800';
      break;
  }

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border ${styles} ${className}`}
    >
      {children || label || defaultLabel}
    </span>
  );
};
