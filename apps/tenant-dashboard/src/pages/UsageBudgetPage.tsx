import React, { useEffect, useState } from 'react';
import {
  Coins,
  RefreshCw,
  TrendingUp,
  Cpu,
  Layers,
  Calendar,
  Zap,
} from 'lucide-react';
import { tenantApi } from '../api/tenant';
import { TenantBudgetStatus, TenantMetrics } from '../api/types';
import { StatCard } from '../components/common/StatCard';
import { Badge } from '../components/common/Badge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';

export const UsageBudgetPage: React.FC = () => {
  const [budget, setBudget] = useState<TenantBudgetStatus | null>(null);
  const [metrics, setMetrics] = useState<TenantMetrics | null>(null);
  const [timeWindow, setTimeWindow] = useState<number>(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = async (days = timeWindow) => {
    setLoading(true);
    setError(null);
    try {
      const [budgetData, metricsData] = await Promise.all([
        tenantApi.getBudget(),
        tenantApi.getMetrics(days),
      ]);
      setBudget(budgetData);
      setMetrics(metricsData);
    } catch (err: any) {
      setError(err?.message || 'تعذر استرجاع بيانات الميزانية والاستهلاك');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData(timeWindow);
  }, [timeWindow]);

  if (loading) {
    return <LoadingState message="جاري استرجاع تفاصيل استهلاك الذكاء الاصطناعي والميزانية..." />;
  }

  if (error || !budget) {
    return (
      <ErrorState
        title="تعذر تحميل بيانات الاستهلاك"
        message={error || 'حدث خطأ أثناء الاتصال بالخادم'}
        onRetry={() => loadData(timeWindow)}
      />
    );
  }

  const currentMonthTokens = budget.current_month_tokens || 0;
  const monthlyLimit = budget.monthly_limit;
  const currentDayTokens = budget.current_day_tokens || 0;
  const dailyLimit = budget.daily_limit;

  const monthPercent = monthlyLimit ? Math.min(100, Math.round((currentMonthTokens / monthlyLimit) * 100)) : 0;
  const dayPercent = dailyLimit ? Math.min(100, Math.round((currentDayTokens / dailyLimit) * 100)) : 0;

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl sm:text-2xl font-extrabold text-white tracking-tight flex items-center gap-2">
            <Coins className="w-6 h-6 text-emerald-400" />
            <span>الاستخدام والميزانية وحصة الرموز</span>
          </h2>
          <p className="text-xs sm:text-sm text-slate-400 mt-1">
            مراقبة استهلاك نماذج الذكاء الاصطناعي وحدود الاستخدام اليومية والشهرية
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <select
            value={timeWindow}
            onChange={(e) => setTimeWindow(Number(e.target.value))}
            className="px-3.5 py-2 rounded-xl bg-slate-900 border border-slate-800 text-white text-xs sm:text-sm focus:outline-none focus:border-emerald-500 font-semibold"
          >
            <option value={7}>آخر 7 أيام</option>
            <option value={30}>آخر 30 يوماً</option>
            <option value={90}>آخر 90 يوماً</option>
          </select>

          <button
            onClick={() => loadData(timeWindow)}
            className="p-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 hover:text-white border border-slate-800 transition"
            title="تحديث البيانات"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Top Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6">
        <StatCard
          title="استهلاك اليوم"
          value={currentDayTokens.toLocaleString()}
          subtitle={dailyLimit ? `من أصل ${dailyLimit.toLocaleString()} رمز` : 'بدون سقف يومي'}
          icon={Coins}
          color="emerald"
          badge={
            <Badge variant={dayPercent > 90 ? 'danger' : dayPercent > 70 ? 'warning' : 'neutral'}>
              {dayPercent}%
            </Badge>
          }
        />
        <StatCard
          title="استهلاك الشهر الحالي"
          value={currentMonthTokens.toLocaleString()}
          subtitle={monthlyLimit ? `من أصل ${monthlyLimit.toLocaleString()} رمز` : 'بدون سقف شهري'}
          icon={TrendingUp}
          color="blue"
          badge={
            <Badge variant={monthPercent > 90 ? 'danger' : monthPercent > 70 ? 'warning' : 'neutral'}>
              {monthPercent}%
            </Badge>
          }
        />
        <StatCard
          title="إجمالي الطلبات (النافذة)"
          value={metrics?.summary.total_requests.toLocaleString() || '0'}
          subtitle={`${metrics?.summary.successful_requests.toLocaleString() || 0} ناجحة`}
          icon={Cpu}
          color="purple"
        />
        <StatCard
          title="متوسط زمن المعالجة"
          value={metrics ? `${Math.round(metrics.summary.avg_duration_ms || 0)} ms` : '—'}
          subtitle="استجابة نماذج الذكاء الاصطناعي"
          icon={Zap}
          color="amber"
        />
      </div>

      {/* Progress Limits Bars */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Monthly Limit Bar */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Calendar className="w-4 h-4 text-emerald-400" />
              <span>الحصة الشهرية (Monthly Quota)</span>
            </h3>
            <Badge
              variant={
                budget.alert_level === 'exceeded'
                  ? 'danger'
                  : budget.alert_level === 'warning'
                  ? 'warning'
                  : 'success'
              }
            >
              {budget.alert_level === 'exceeded'
                ? 'تم استنفاد الحصة'
                : budget.alert_level === 'warning'
                ? 'تنبيه: اقترب من الحد'
                : 'ضمن النطاق الآمن'}
            </Badge>
          </div>

          <div className="space-y-2">
            <div className="flex justify-between text-xs text-slate-400 font-mono">
              <span>المستهلك: {currentMonthTokens.toLocaleString()}</span>
              <span>الحد: {monthlyLimit ? monthlyLimit.toLocaleString() : 'غير مقيد'}</span>
            </div>
            <div className="w-full h-3 bg-slate-950 rounded-full overflow-hidden p-0.5 border border-slate-800">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  monthPercent > 90
                    ? 'bg-rose-500'
                    : monthPercent > 75
                    ? 'bg-amber-500'
                    : 'bg-emerald-500'
                }`}
                style={{ width: `${Math.min(100, monthPercent)}%` }}
              />
            </div>
            <div className="flex justify-between text-[11px] text-slate-400">
              <span>النسبة: {monthPercent}%</span>
              <span>{budget.is_hard_limit ? 'حد إلزامي صارم (Hard Limit)' : 'حد إرشادي مرن (Soft Limit)'}</span>
            </div>
          </div>
        </div>

        {/* Daily Limit Bar */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Zap className="w-4 h-4 text-teal-400" />
              <span>الحصة اليومية (Daily Quota)</span>
            </h3>
            <Badge variant={dayPercent > 90 ? 'danger' : dayPercent > 75 ? 'warning' : 'success'}>
              {dayPercent > 90 ? 'مرتفع' : dayPercent > 75 ? 'متوسط' : 'طبيعي'}
            </Badge>
          </div>

          <div className="space-y-2">
            <div className="flex justify-between text-xs text-slate-400 font-mono">
              <span>المستهلك اليوم: {currentDayTokens.toLocaleString()}</span>
              <span>الحد: {dailyLimit ? dailyLimit.toLocaleString() : 'غير مقيد'}</span>
            </div>
            <div className="w-full h-3 bg-slate-950 rounded-full overflow-hidden p-0.5 border border-slate-800">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  dayPercent > 90
                    ? 'bg-rose-500'
                    : dayPercent > 75
                    ? 'bg-amber-500'
                    : 'bg-teal-500'
                }`}
                style={{ width: `${Math.min(100, dayPercent)}%` }}
              />
            </div>
            <div className="flex justify-between text-[11px] text-slate-400">
              <span>النسبة: {dayPercent}%</span>
              <span>يتم تصفير العداد يومياً الساعة 00:00 UTC</span>
            </div>
          </div>
        </div>
      </div>

      {/* Providers & Models Breakdown */}
      {metrics && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Provider Breakdown */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <Layers className="w-5 h-5 text-emerald-400" />
              <span>الاستهلاك حسب مزود الذكاء الاصطناعي</span>
            </h3>

            {Object.keys(metrics.by_provider).length === 0 ? (
              <p className="text-xs text-slate-400 py-6 text-center">لا توجد بيانات مسجلة في هذه النافذة</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-right text-xs">
                  <thead className="border-b border-slate-800 text-slate-400">
                    <tr>
                      <th className="pb-2 font-semibold">المزود</th>
                      <th className="pb-2 font-semibold">الطلبات</th>
                      <th className="pb-2 font-semibold">الرموز (Tokens)</th>
                      <th className="pb-2 font-semibold">الأخطاء</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 font-mono">
                    {Object.entries(metrics.by_provider).map(([provider, stat]) => (
                      <tr key={provider} className="hover:bg-slate-800/20">
                        <td className="py-2.5 font-bold text-white capitalize">{provider}</td>
                        <td className="py-2.5 text-slate-300">{stat.requests.toLocaleString()}</td>
                        <td className="py-2.5 text-emerald-400">{stat.tokens.toLocaleString()}</td>
                        <td className="py-2.5 text-slate-400">
                          {stat.errors > 0 ? (
                            <span className="text-rose-400">{stat.errors}</span>
                          ) : (
                            '0'
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Models Breakdown */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <Cpu className="w-5 h-5 text-teal-400" />
              <span>الاستهلاك حسب النموذج (Model)</span>
            </h3>

            {Object.keys(metrics.by_model).length === 0 ? (
              <p className="text-xs text-slate-400 py-6 text-center">لا توجد تفاصيل نماذج مسجلة</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-right text-xs">
                  <thead className="border-b border-slate-800 text-slate-400">
                    <tr>
                      <th className="pb-2 font-semibold">النموذج</th>
                      <th className="pb-2 font-semibold">المزود</th>
                      <th className="pb-2 font-semibold">الرموز (Tokens)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 font-mono">
                    {Object.entries(metrics.by_model).map(([model, stat]) => (
                      <tr key={model} className="hover:bg-slate-800/20">
                        <td className="py-2.5 font-bold text-white">{model}</td>
                        <td className="py-2.5 text-slate-400 capitalize">{stat.provider}</td>
                        <td className="py-2.5 text-emerald-400">{stat.tokens.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Daily Trends Table */}
      {metrics && metrics.daily_trends && metrics.daily_trends.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-emerald-400" />
            <span>الاتجاه اليومي للاستهلاك (Daily Trends)</span>
          </h3>

          <div className="overflow-x-auto">
            <table className="w-full text-right text-xs">
              <thead className="border-b border-slate-800 text-slate-400 font-semibold">
                <tr>
                  <th className="pb-2.5 pr-2">التاريخ</th>
                  <th className="pb-2.5">عدد الطلبات</th>
                  <th className="pb-2.5">الرموز المستهلكة</th>
                  <th className="pb-2.5">الأخطاء</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono">
                {metrics.daily_trends.map((item) => (
                  <tr key={item.date} className="hover:bg-slate-800/20">
                    <td className="py-2.5 pr-2 font-semibold text-slate-200">{item.date}</td>
                    <td className="py-2.5 text-slate-300">{item.requests.toLocaleString()}</td>
                    <td className="py-2.5 text-emerald-400 font-bold">{item.tokens.toLocaleString()}</td>
                    <td className="py-2.5 text-slate-400">
                      {item.errors > 0 ? (
                        <span className="text-rose-400 font-bold">{item.errors}</span>
                      ) : (
                        '0'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
