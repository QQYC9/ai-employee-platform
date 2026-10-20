import React from 'react';

export interface BadgeProps {
  status: string;
  label?: string;
  size?: 'sm' | 'md';
}

export const Badge: React.FC<BadgeProps> = ({ status, label, size = 'sm' }) => {
  const norm = (status || '').toLowerCase().trim();

  let colorClasses = 'bg-slate-800 text-slate-300 border-slate-700';
  let dotColor = 'bg-slate-400';

  if (['healthy', 'active', 'completed', 'success', 'approved'].includes(norm)) {
    colorClasses = 'bg-emerald-950/70 text-emerald-300 border-emerald-800/80';
    dotColor = 'bg-emerald-400';
  } else if (['degraded', 'warning', 'waiting_approval', 'pending', 'queued'].includes(norm)) {
    colorClasses = 'bg-amber-950/70 text-amber-300 border-amber-800/80';
    dotColor = 'bg-amber-400 animate-pulse';
  } else if (['unhealthy', 'failed', 'error', 'critical', 'exceeded', 'suspended', 'dead_letter'].includes(norm)) {
    colorClasses = 'bg-rose-950/70 text-rose-300 border-rose-800/80';
    dotColor = 'bg-rose-400';
  } else if (['in_progress', 'processing'].includes(norm)) {
    colorClasses = 'bg-blue-950/70 text-blue-300 border-blue-800/80';
    dotColor = 'bg-blue-400 animate-ping';
  } else if (['fallback'].includes(norm)) {
    colorClasses = 'bg-purple-950/70 text-purple-300 border-purple-800/80';
    dotColor = 'bg-purple-400';
  }

  const sizeClasses = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-sm';

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-medium rounded-full border ${colorClasses} ${sizeClasses}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
      <span>{label || status}</span>
    </span>
  );
};
