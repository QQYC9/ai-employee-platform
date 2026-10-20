import React from 'react';
import { LucideIcon, Inbox } from 'lucide-react';

interface EmptyStateProps {
  title?: string;
  description?: string;
  icon?: LucideIcon;
  action?: {
    label: string;
    onClick: () => void;
  };
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title = 'لا توجد بيانات متاحة حالياً',
  description = 'لم يتم العثور على أي عناصر لعرضها في هذا القسم.',
  icon: Icon = Inbox,
  action,
}) => {
  return (
    <div className="flex flex-col items-center justify-center gap-3 p-12 text-center rounded-xl border border-slate-800 bg-slate-900/40">
      <div className="p-4 rounded-2xl bg-slate-800/80 border border-slate-700 text-slate-400">
        <Icon className="w-8 h-8" />
      </div>
      <div className="space-y-1">
        <h4 className="text-base font-semibold text-white">{title}</h4>
        <p className="text-sm text-slate-400 max-w-sm">{description}</p>
      </div>
      {action && (
        <button
          onClick={action.onClick}
          className="mt-3 inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 transition shadow-lg shadow-emerald-950/50"
        >
          {action.label}
        </button>
      )}
    </div>
  );
};
