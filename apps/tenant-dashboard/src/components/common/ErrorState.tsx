import React from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';

interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title = 'حدث خطأ في استرجاع البيانات',
  message,
  onRetry,
}) => {
  return (
    <div className="flex flex-col items-center justify-center p-8 rounded-2xl border border-rose-900/40 bg-rose-950/20 text-center max-w-md mx-auto my-6 space-y-4">
      <div className="p-3 rounded-2xl bg-rose-500/10 text-rose-400 border border-rose-500/20">
        <AlertCircle className="w-8 h-8" />
      </div>

      <div className="space-y-1">
        <h3 className="text-base font-bold text-white">{title}</h3>
        <p className="text-xs text-rose-300/90 leading-relaxed">{message}</p>
      </div>

      {onRetry && (
        <button
          onClick={onRetry}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-900 border border-slate-700 text-xs font-semibold text-slate-200 hover:bg-slate-800 transition"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>إعادة المحاولة</span>
        </button>
      )}
    </div>
  );
};
