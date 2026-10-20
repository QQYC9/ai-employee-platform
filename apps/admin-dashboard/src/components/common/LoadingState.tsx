import React from 'react';
import { Loader2 } from 'lucide-react';

interface LoadingStateProps {
  message?: string;
  minHeight?: string;
}

export const LoadingState: React.FC<LoadingStateProps> = ({
  message = 'جاري تحميل البيانات...',
  minHeight = 'min-h-[300px]',
}) => {
  return (
    <div className={`flex flex-col items-center justify-center gap-3 p-8 ${minHeight} text-slate-400`}>
      <Loader2 className="w-8 h-8 text-emerald-400 animate-spin" />
      <span className="text-sm font-medium">{message}</span>
    </div>
  );
};
