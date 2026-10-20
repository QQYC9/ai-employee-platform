import React, { useEffect, useState } from 'react';
import { adminApi } from '../api/admin';
import { PlatformSummary, OperationalHealth } from '../api/types';
import { StatCard } from '../components/common/StatCard';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { Badge } from '../components/common/Badge';
import {
  Building2,
  Bot,
  CheckCircle2,
  Zap,
  Activity,
  Mail,
  RefreshCw,
  Clock,
} from 'lucide-react';

export const DashboardPage: React.FC = () => {
  const [summary, setSummary] = useState<PlatformSummary | null>(null);
  const [health, setHealth] = useState<OperationalHealth | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [sumRes, healthRes] = await Promise.all([
        adminApi.getPlatformOverview(),
        adminApi.getOperationalHealth(),
      ]);
      setSummary(sumRes);
      setHealth(healthRes);
    } catch (err: any) {
      setError(err?.message || 'تعذر تحميل بيانات لوحة التحكم');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  if (isLoading) {
    return <LoadingState message="جاري استرجاع مؤشرات المنصة وسجلات التشغيل..." />;
  }

  if (error || !summary) {
    return <ErrorState message={error || 'لا توجد بيانات متاحة'} onRetry={fetchData} />;
  }

  const finishedTasks = (summary.tasks.completed || 0) + (summary.tasks.failed || 0);

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-2xl font-black text-white tracking-tight">
            لوحة المعلومات الرئيسية
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            مؤشرات تشغيلية حية مجمعة عبر كافة المستأجرين والوكلاء ونماذج الذكاء الاصطناعي
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400 flex items-center gap-1">
            <Clock className="w-3.5 h-3.5" />
            تحديث: {new Date(summary.generated_at).toLocaleTimeString('ar-EG')}
          </span>
          <button
            onClick={fetchData}
            className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-3.5 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 border border-slate-800 transition"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>تحديث البيانات</span>
          </button>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <StatCard
          title="إجمالي المستأجرين"
          value={summary.tenants.total}
          subtitle={`نشط: ${summary.tenants.by_status?.active || 0} | معلق: ${summary.tenants.by_status?.suspended || 0}`}
          icon={Building2}
          color="emerald"
        />
        <StatCard
          title="الوكلاء الرقميون"
          value={summary.agents.total}
          subtitle={`نشط: ${summary.agents.by_status?.active || 0} | جاهز: ${summary.agents.by_status?.idle || 0}`}
          icon={Bot}
          color="blue"
        />
        <StatCard
          title="نسبة نجاح المهام"
          value={`${summary.tasks.success_rate_pct}%`}
          subtitle={`مكتملة: ${summary.tasks.completed} من أصل ${finishedTasks} منتهية`}
          icon={CheckCircle2}
          color={summary.tasks.success_rate_pct >= 90 ? 'emerald' : 'amber'}
          trend={{
            value: `${summary.tasks.failed} فاشلة`,
            isPositive: summary.tasks.failed === 0,
          }}
        />
        <StatCard
          title="استهلاك الرموز (Tokens)"
          value={summary.ai_usage.total_tokens.toLocaleString()}
          subtitle={`طلبات: ${summary.ai_usage.total_requests} | متوسط: ${summary.ai_usage.avg_duration_ms} ms`}
          icon={Zap}
          color="purple"
        />
      </div>

      {/* Services Health & Diagnostics */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-2.5">
            <Activity className="w-5 h-5 text-emerald-400" />
            <h3 className="text-base font-bold text-white">
              حالة الخدمات والبنية التحتية
            </h3>
          </div>
          <span className="text-xs text-slate-400">
            فحص تشغيلي مباشر عبر Backend
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Database */}
          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-semibold text-slate-300">قاعدة البيانات (PostgreSQL)</span>
              <Badge status={health?.components?.database?.status || health?.database?.status || 'unknown'} />
            </div>
            <p className="text-xs text-slate-400">
              {(health?.components?.database?.details?.connected || health?.database?.details?.connected)
                ? 'الاتصال مستقر بقاعدة ai_employee_staging'
                : 'تعذر إثبات الاتصال'}
            </p>
          </div>

          {/* Outbox Queue */}
          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-semibold text-slate-300">طابور صندوق الصادر (Outbox)</span>
              <Badge status={health?.components?.outbox?.status || health?.outbox?.status || 'unknown'} />
            </div>
            <div className="flex items-center justify-between text-xs text-slate-400 mt-1">
              <span>قيد الانتظار: {health?.components?.outbox?.details?.pending ?? health?.outbox?.details?.pending ?? 0}</span>
              <span className="text-rose-400 font-medium">Dead Letter: {health?.components?.outbox?.details?.dead_letter ?? health?.outbox?.details?.dead_letter ?? 0}</span>
              <span className="text-amber-400">عالق: {health?.components?.outbox?.details?.stuck_processing ?? health?.outbox?.details?.stuck_processing ?? 0}</span>
            </div>
          </div>

          {/* Stalled Tasks */}
          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-semibold text-slate-300">مراقبة المهام العالقة</span>
              <Badge status={health?.components?.stalled_tasks?.status || health?.stalled_tasks?.status || 'unknown'} />
            </div>
            <p className="text-xs text-slate-400">
              مهام متوقفة لأكثر من ساعة: {health?.components?.stalled_tasks?.details?.count ?? health?.stalled_tasks?.details?.count ?? 0}
            </p>
          </div>
        </div>
      </div>

      {/* Visual Charts & Operational Details Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Task Breakdown Chart */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur flex flex-col justify-between">
          <div>
            <h3 className="text-base font-bold text-white mb-2">
              توزيع حالات المهام التشغيلية
            </h3>
            <p className="text-xs text-slate-400 mb-6">
              إجمالي المهام المسجلة في النظام: {summary.tasks.total} مهمة
            </p>

            <div className="space-y-4">
              <div>
                <div className="flex justify-between text-xs font-semibold mb-1">
                  <span className="text-emerald-400">مكتملة ({summary.tasks.completed})</span>
                  <span className="text-slate-400">
                    {summary.tasks.total ? Math.round((summary.tasks.completed / summary.tasks.total) * 100) : 0}%
                  </span>
                </div>
                <div className="w-full h-2.5 rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className="h-full bg-emerald-500 rounded-full transition-all duration-500"
                    style={{
                      width: `${summary.tasks.total ? (summary.tasks.completed / summary.tasks.total) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>

              <div>
                <div className="flex justify-between text-xs font-semibold mb-1">
                  <span className="text-blue-400">قيد التنفيذ ({summary.tasks.in_progress})</span>
                  <span className="text-slate-400">
                    {summary.tasks.total ? Math.round((summary.tasks.in_progress / summary.tasks.total) * 100) : 0}%
                  </span>
                </div>
                <div className="w-full h-2.5 rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className="h-full bg-blue-500 rounded-full transition-all duration-500"
                    style={{
                      width: `${summary.tasks.total ? (summary.tasks.in_progress / summary.tasks.total) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>

              <div>
                <div className="flex justify-between text-xs font-semibold mb-1">
                  <span className="text-amber-400">قيد الانتظار ({summary.tasks.pending})</span>
                  <span className="text-slate-400">
                    {summary.tasks.total ? Math.round((summary.tasks.pending / summary.tasks.total) * 100) : 0}%
                  </span>
                </div>
                <div className="w-full h-2.5 rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className="h-full bg-amber-500 rounded-full transition-all duration-500"
                    style={{
                      width: `${summary.tasks.total ? (summary.tasks.pending / summary.tasks.total) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>

              <div>
                <div className="flex justify-between text-xs font-semibold mb-1">
                  <span className="text-rose-400">فاشلة / أخطاء ({summary.tasks.failed})</span>
                  <span className="text-slate-400">
                    {summary.tasks.total ? Math.round((summary.tasks.failed / summary.tasks.total) * 100) : 0}%
                  </span>
                </div>
                <div className="w-full h-2.5 rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className="h-full bg-rose-500 rounded-full transition-all duration-500"
                    style={{
                      width: `${summary.tasks.total ? (summary.tasks.failed / summary.tasks.total) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>
            </div>
          </div>

          <div className="mt-6 pt-4 border-t border-slate-800 text-xs text-slate-400 flex items-center justify-between">
            <span>مهام بها سجلات أخطاء مسجلة:</span>
            <span className="font-bold text-slate-200">{summary.tasks.tasks_with_errors}</span>
          </div>
        </div>

        {/* AI & Communication Summary */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur flex flex-col justify-between">
          <div>
            <h3 className="text-base font-bold text-white mb-2">
              استهلاك الذكاء الاصطناعي والقنوات
            </h3>
            <p className="text-xs text-slate-400 mb-6">
              تفاصيل استدعاءات النماذج وقنوات التواصل النشطة
            </p>

            <div className="grid grid-cols-2 gap-4 mb-6">
              <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
                <span className="text-xs text-slate-400 block mb-1">رموز الإدخال (Prompt)</span>
                <span className="text-lg font-bold text-white">
                  {(summary.ai_usage?.prompt_tokens ?? 0).toLocaleString()}
                </span>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
                <span className="text-xs text-slate-400 block mb-1">رموز الإكمال (Completion)</span>
                <span className="text-lg font-bold text-white">
                  {(summary.ai_usage?.completion_tokens ?? 0).toLocaleString()}
                </span>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
                <span className="text-xs text-slate-400 block mb-1">أخطاء استدعاء AI</span>
                <span className="text-lg font-bold text-rose-400">
                  {summary.ai_usage?.error_requests ?? 0}
                </span>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
                <span className="text-xs text-slate-400 block mb-1">تحويلات بديلة (Fallbacks)</span>
                <span className="text-lg font-bold text-purple-400">
                  {summary.ai_usage?.fallback_requests ?? 0}
                </span>
              </div>
            </div>
          </div>

          <div className="pt-4 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5">
              <Mail className="w-4 h-4 text-emerald-400" />
              إجمالي قنوات التواصل المربوطة: {summary.channels.total}
            </span>
            <span>
              سجلات التدقيق في آخر 24 ساعة: <strong className="text-white">{summary.audit.recent_events_24h}</strong>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
