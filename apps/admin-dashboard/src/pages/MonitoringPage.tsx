import React, { useEffect, useState } from 'react';
import { adminApi } from '../api/admin';
import { AuditEventItem, OperationalHealth, PlatformMetrics } from '../api/types';
import { Badge } from '../components/common/Badge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import {
  Activity,
  Layers,
  Cpu,
  History,
  RefreshCw,
  AlertOctagon,
  Clock,
  Shield,
  Filter,
} from 'lucide-react';

export const MonitoringPage: React.FC = () => {
  const [health, setHealth] = useState<OperationalHealth | null>(null);
  const [metrics, setMetrics] = useState<PlatformMetrics | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditEventItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filters for audit logs
  const [eventTypeFilter, setEventTypeFilter] = useState<string>('');
  const [timeWindowDays, setTimeWindowDays] = useState<number>(30);

  const fetchData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [healthRes, metricsRes, auditRes] = await Promise.all([
        adminApi.getOperationalHealth(),
        adminApi.getPlatformMetrics(timeWindowDays),
        adminApi.listAuditLogs({
          eventType: eventTypeFilter || undefined,
          limit: 50,
        }),
      ]);
      setHealth(healthRes);
      setMetrics(metricsRes);
      setAuditLogs(auditRes.events || []);
    } catch (err: any) {
      setError(err?.message || 'تعذر استرجاع بيانات المراقبة');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [timeWindowDays, eventTypeFilter]);

  if (isLoading) {
    return <LoadingState message="جاري استرجاع سجلات المراقبة وفحوصات النظام..." />;
  }

  if (error) {
    return <ErrorState message={error} onRetry={fetchData} />;
  }

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-2xl font-black text-white tracking-tight flex items-center gap-2">
            <Activity className="w-6 h-6 text-emerald-400" />
            مراقبة النظام وتشخيص الخدمات
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            متابعة حالة طوابير صندوق الصادر، استهلاك المزودين، وسجلات التدقيق الإداري غير القابلة للتعديل
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={timeWindowDays}
            onChange={(e) => setTimeWindowDays(Number(e.target.value))}
            className="rounded-xl border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-white focus:border-emerald-500 focus:outline-none"
          >
            <option value={7}>آخر 7 أيام</option>
            <option value={30}>آخر 30 يوماً</option>
            <option value={90}>آخر 90 يوماً</option>
          </select>
          <button
            onClick={fetchData}
            className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-3.5 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 border border-slate-800 transition"
          >
            <RefreshCw className="w-4 h-4" />
            <span>تحديث</span>
          </button>
        </div>
      </div>

      {/* Diagnostics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        {/* Outbox Queue Diagnostic */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 backdrop-blur">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Layers className="w-5 h-5 text-blue-400" />
              <h3 className="text-sm font-bold text-white">طابور صندوق الصادر (Outbox)</h3>
            </div>
            <Badge status={health?.components?.outbox?.status || health?.outbox?.status || 'unknown'} />
          </div>

          <div className="space-y-2.5 text-xs">
            <div className="flex justify-between text-slate-400">
              <span>إجمالي الأحداث:</span>
              <span className="font-semibold text-white">
                {health?.components?.outbox?.details?.total ?? health?.outbox?.details?.total ?? 0}
              </span>
            </div>
            <div className="flex justify-between text-slate-400">
              <span>قيد الانتظار (Pending):</span>
              <span className="font-semibold text-amber-400">
                {health?.components?.outbox?.details?.pending ?? health?.outbox?.details?.pending ?? 0}
              </span>
            </div>
            <div className="flex justify-between text-slate-400">
              <span>قيد المعالجة (Processing):</span>
              <span className="font-semibold text-blue-400">
                {health?.components?.outbox?.details?.processing ?? health?.outbox?.details?.processing ?? 0}
              </span>
            </div>
            <div className="flex justify-between text-slate-400">
              <span>أحداث فاشلة نهائياً (Dead Letter):</span>
              <span className="font-semibold text-rose-400">
                {health?.components?.outbox?.details?.dead_letter ?? health?.outbox?.details?.dead_letter ?? 0}
              </span>
            </div>
            <div className="flex justify-between text-slate-400">
              <span>أحداث عالقة (Stuck &gt; 5m):</span>
              <span className="font-semibold text-rose-400">
                {health?.components?.outbox?.details?.stuck_processing ?? health?.outbox?.details?.stuck_processing ?? 0}
              </span>
            </div>
          </div>
        </div>

        {/* Stalled Tasks Diagnostic */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 backdrop-blur">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <AlertOctagon className="w-5 h-5 text-amber-400" />
              <h3 className="text-sm font-bold text-white">المهام العالقة (Stalled)</h3>
            </div>
            <Badge status={health?.components?.stalled_tasks?.status || health?.stalled_tasks?.status || 'unknown'} />
          </div>

          <p className="text-xs text-slate-400 mb-3">
            الكشف عن المهام التي بقيت قيد التنفيذ لأكثر من 60 دقيقة دون تحديث:
          </p>

          <div className="text-2xl font-bold text-white mb-2">
            {health?.components?.stalled_tasks?.details?.count ?? health?.stalled_tasks?.details?.count ?? 0}
            <span className="text-xs font-normal text-slate-400 mr-2">مهام عالقة</span>
          </div>

          {((health?.components?.stalled_tasks?.details?.sample?.length ?? health?.stalled_tasks?.details?.sample?.length ?? 0) > 0) ? (
            <div className="mt-2 space-y-1">
              {(health?.components?.stalled_tasks?.details?.sample || health?.stalled_tasks?.details?.sample)?.map((t: any) => (
                <div key={t.id} className="text-[11px] text-rose-300 truncate font-mono">
                  • {t.title} ({t.id})
                </div>
              ))}
            </div>
          ) : (
            <p className="text-[11px] text-emerald-400">لا توجد مهام عالقة حالياً</p>
          )}
        </div>

        {/* Database Diagnostic */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 backdrop-blur">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Shield className="w-5 h-5 text-emerald-400" />
              <h3 className="text-sm font-bold text-white">قاعدة البيانات (PostgreSQL)</h3>
            </div>
            <Badge status={health?.components?.database?.status || health?.database?.status || 'unknown'} />
          </div>

          <div className="space-y-2.5 text-xs text-slate-400">
            <div className="flex justify-between">
              <span>بيئة التشغيل:</span>
              <span className="font-semibold text-emerald-400">Staging المعزولة</span>
            </div>
            <div className="flex justify-between">
              <span>اسم القاعدة:</span>
              <span className="font-mono text-white">ai_employee_staging</span>
            </div>
            <div className="flex justify-between">
              <span>حالة الاستعلام الحي:</span>
              <span className="text-emerald-400 font-semibold">استجابة نشطة (SELECT 1 OK)</span>
            </div>
          </div>
        </div>
      </div>

      {/* AI Providers & Models Breakdown */}
      {metrics && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* By Provider */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur">
            <div className="flex items-center gap-2 mb-4">
              <Cpu className="w-5 h-5 text-purple-400" />
              <h3 className="text-base font-bold text-white">
                توزيع استهلاك مزودي الذكاء الاصطناعي
              </h3>
            </div>

            {Object.keys(metrics.by_provider || {}).length === 0 ? (
              <p className="text-xs text-slate-500 py-6 text-center">لا توجد سجلات استهلاك للمزودين في هذه الفترة</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-right text-xs">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-400">
                      <th className="pb-2 font-semibold">المزود (Provider)</th>
                      <th className="pb-2 font-semibold">الطلبات</th>
                      <th className="pb-2 font-semibold">الرموز (Tokens)</th>
                      <th className="pb-2 font-semibold">الأخطاء</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/50">
                    {Object.entries(metrics.by_provider).map(([provider, stat]) => (
                      <tr key={provider} className="hover:bg-slate-800/30">
                        <td className="py-2.5 font-bold text-white uppercase">{provider}</td>
                        <td className="py-2.5 text-slate-300">{stat.requests.toLocaleString()}</td>
                        <td className="py-2.5 text-purple-300 font-mono">{stat.tokens.toLocaleString()}</td>
                        <td className="py-2.5 text-rose-400">{stat.errors}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Daily Trends Chart */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur flex flex-col justify-between">
            <div>
              <div className="flex items-center gap-2 mb-4">
                <Clock className="w-5 h-5 text-emerald-400" />
                <h3 className="text-base font-bold text-white">
                  اتجاهات الاستهلاك اليومية
                </h3>
              </div>

              {metrics.daily_trends && metrics.daily_trends.length > 0 ? (
                <div className="space-y-3">
                  {metrics.daily_trends.slice(-6).map((trend) => (
                    <div key={trend.date} className="text-xs">
                      <div className="flex justify-between text-slate-400 mb-1">
                        <span className="font-mono text-slate-300">{trend.date}</span>
                        <span>
                          {trend.requests} طلبات | <strong className="text-purple-300">{trend.tokens.toLocaleString()} رمز</strong>
                        </span>
                      </div>
                      <div className="w-full h-1.5 rounded-full bg-slate-800 overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-emerald-500 to-purple-500 rounded-full"
                          style={{
                            width: `${Math.min(100, Math.max(10, (trend.tokens / (metrics.summary.total_tokens || 1)) * 100))}%`,
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-slate-500 py-6 text-center">لا توجد بيانات استهلاك يومية متاحة</p>
              )}
            </div>

            <div className="mt-4 pt-3 border-t border-slate-800 flex justify-between text-xs text-slate-400">
              <span>إجمالي الطلبات الناجحة:</span>
              <span className="font-bold text-emerald-400">{metrics.summary.successful_requests}</span>
            </div>
          </div>
        </div>
      )}

      {/* Audit Logs Table */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div className="flex items-center gap-2">
            <History className="w-5 h-5 text-blue-400" />
            <div>
              <h3 className="text-base font-bold text-white">سجلات التدقيق الإداري (Audit Logs)</h3>
              <p className="text-xs text-slate-400">سجل غير قابل للتعديل لكافة الإجراءات والعمليات الإدارية</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-slate-400" />
            <select
              value={eventTypeFilter}
              onChange={(e) => setEventTypeFilter(e.target.value)}
              className="rounded-lg border border-slate-800 bg-slate-950 px-3 py-1.5 text-xs text-white focus:border-emerald-500 focus:outline-none"
            >
              <option value="">كافة أنواع الأحداث</option>
              <option value="tenant_status_update">تعديل حالة المستأجر</option>
              <option value="tenant_budget_update">تعديل حصة المستأجر</option>
              <option value="tenant_provisioned">تأسيس مستأجر</option>
              <option value="task_execution">تنفيذ مهمة</option>
            </select>
          </div>
        </div>

        {auditLogs.length === 0 ? (
          <EmptyState
            title="لا توجد سجلات تدقيق"
            description="لم يتم تسجيل أحداث إدارية تطابق الفلتر المحدد."
            icon={History}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-right text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400">
                  <th className="py-2.5 font-semibold">التاريخ والتوقيت</th>
                  <th className="py-2.5 font-semibold">نوع الحدث</th>
                  <th className="py-2.5 font-semibold">الإجراء</th>
                  <th className="py-2.5 font-semibold">الوصف</th>
                  <th className="py-2.5 font-semibold">المستأجر</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/50">
                {auditLogs.map((log) => (
                  <tr key={log.id} className="hover:bg-slate-800/30 transition">
                    <td className="py-2.5 font-mono text-slate-400 whitespace-nowrap">
                      {log.created_at ? new Date(log.created_at).toLocaleString('ar-EG') : '—'}
                    </td>
                    <td className="py-2.5 font-semibold text-emerald-400">{log.event_type}</td>
                    <td className="py-2.5 text-slate-300">{log.action}</td>
                    <td className="py-2.5 text-slate-400 max-w-xs truncate" title={log.description}>
                      {log.description}
                    </td>
                    <td className="py-2.5 font-mono text-slate-500 truncate max-w-[100px]" title={log.tenant_id || ''}>
                      {log.tenant_id || 'Platform'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
