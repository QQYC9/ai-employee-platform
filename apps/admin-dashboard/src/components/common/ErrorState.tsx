import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface ErrorStateProps {
  message?: string;
  onRetry?: () => void;
  status?: number;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  message = 'تعذر تحميل البيانات، يرجى المحاولة مرة أخرى',
  onRetry,
  status,
}) => {
  return (
    <div className="flex flex-col items-center justify-center gap-3 p-8 min-h-[300px] text-center rounded-xl border border-rose-900/50 bg-rose-950/20 backdrop-blur">
      <div className="p-3 rounded-full bg-rose-950/60 border border-rose-800 text-rose-400">
        <AlertTriangle className="w-8 h-8" />
      </div>
      <div className="space-y-1">
        <h4 className="text-base font-bold text-white">
          {status ? `خطأ (${status})` : 'حدث خطأ'}
        </h4>
        <p className="text-sm text-rose-300 max-w-md">{message}</p>
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-2 inline-flex items-center gap-2 rounded-lg bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 border border-slate-700 transition"
        >
          <RefreshCw className="w-4 h-4" />
          <span>إعادة المحاولة</span>
        </button>
      )}
    </div>
  );
};
