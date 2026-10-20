import React from 'react';
import {
  Settings,
  Shield,
  Server,
  Lock,
  Cpu,
  CheckCircle2,
} from 'lucide-react';

export const SettingsPage: React.FC = () => {
  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-black text-white tracking-tight flex items-center gap-2">
          <Settings className="w-6 h-6 text-emerald-400" />
          إعدادات المنصة والبنية التحتية
        </h2>
        <p className="text-sm text-slate-400 mt-1">
          استعراض السياسات التشغيلية، بروتوكولات الأمان، ومحددات البيئة المعتمدة في Backend
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Security & Access Policies */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur space-y-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2.5">
              <Shield className="w-5 h-5 text-emerald-400" />
              <h3 className="text-base font-bold text-white">ضوابط الأمان والمصادقة</h3>
            </div>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
              سياسة نظام ثابتة
            </span>
          </div>

          <div className="space-y-3 text-xs">
            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800">
              <span className="text-slate-300">طريقة المصادقة الأساسية:</span>
              <span className="font-semibold text-emerald-400 flex items-center gap-1">
                <CheckCircle2 className="w-4 h-4" /> JWT Bearer Tokens
              </span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800">
              <span className="text-slate-300">فرض حظر ترويسة X-User-ID:</span>
              <span className="font-semibold text-emerald-400 flex items-center gap-1">
                <CheckCircle2 className="w-4 h-4" /> مفعل ومشدد (Production Strict)
              </span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800">
              <span className="text-slate-300">محدد معدل الطلبات (Rate Limiting):</span>
              <span className="font-semibold text-emerald-400 flex items-center gap-1">
                <CheckCircle2 className="w-4 h-4" /> مفعل عبر Redis
              </span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800">
              <span className="text-slate-300">عزل بيانات المستأجرين (Multi-Tenancy):</span>
              <span className="font-semibold text-emerald-400 flex items-center gap-1">
                <CheckCircle2 className="w-4 h-4" /> عزل كامل على مستوى الخادم وقاعدة البيانات
              </span>
            </div>
          </div>
        </div>

        {/* Runtime & Worker Configuration */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur space-y-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2.5">
              <Server className="w-5 h-5 text-blue-400" />
              <h3 className="text-base font-bold text-white">تكوين البيئة والعامل الخلفي</h3>
            </div>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
              بيئة التشغيل الحالية
            </span>
          </div>

          <div className="space-y-3 text-xs">
            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800">
              <span className="text-slate-300">بيئة التشغيل الحالية:</span>
              <span className="font-mono text-emerald-400 uppercase font-bold">Staging (معزولة)</span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800">
              <span className="text-slate-300">وضع العامل الخلفي (Outbox Worker):</span>
              <span className="font-semibold text-slate-200">Embedded Worker Thread</span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800">
              <span className="text-slate-300">فترة الاقتراع (Poll Interval):</span>
              <span className="font-mono text-slate-200">2 ثوانٍ</span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800">
              <span className="text-slate-300">حجم الدفعة (Batch Size):</span>
              <span className="font-mono text-slate-200">10 أحداث / دفعة</span>
            </div>
          </div>
        </div>

        {/* AI Engine & Providers Policy */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur space-y-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2.5">
              <Cpu className="w-5 h-5 text-purple-400" />
              <h3 className="text-base font-bold text-white">محرك الذكاء الاصطناعي والمزودين</h3>
            </div>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
              سياسة التشغيل
            </span>
          </div>

          <div className="space-y-3 text-xs">
            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800">
              <span className="text-slate-300">آلية التراجع عند الفشل (Fallback):</span>
              <span className="font-semibold text-emerald-400 flex items-center gap-1">
                <CheckCircle2 className="w-4 h-4" /> تلقائي عبر المزود الاحتياطي
              </span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800">
              <span className="text-slate-300">تتبع استهلاك الرموز (Token Accounting):</span>
              <span className="font-semibold text-emerald-400 flex items-center gap-1">
                <CheckCircle2 className="w-4 h-4" /> تدقيق دقيق ومباشر في AIUsageLog
              </span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800">
              <span className="text-slate-300">تسجيل المدخلات الحساسة:</span>
              <span className="font-semibold text-emerald-400">حجب وتشفير كامل</span>
            </div>
          </div>
        </div>

        {/* Storage & Encryption Architecture */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur space-y-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2.5">
              <Lock className="w-5 h-5 text-amber-400" />
              <h3 className="text-base font-bold text-white">التخزين والتشفير</h3>
            </div>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
              معايير مشددة
            </span>
          </div>

          <div className="space-y-3 text-xs">
            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800">
              <span className="text-slate-300">تشفير أسرار القنوات والرموز:</span>
              <span className="font-semibold text-emerald-400">AES-256 Fernet مفعل</span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800">
              <span className="text-slate-300">حجب المفاتيح والأسرار في واجهات الإدارة:</span>
              <span className="font-semibold text-emerald-400">محجوبة تلقائياً (Masked)</span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800">
              <span className="text-slate-300">سجل الترحيلات (Alembic Head):</span>
              <span className="font-mono text-slate-200">f6a7b8c9d0e1 (Phase 16)</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
