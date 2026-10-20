import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Bot,
  ListTodo,
  Radio,
  Coins,
  Plus,
  RefreshCw,
  CheckCircle2,
  Clock,
  AlertTriangle,
  ArrowRight,
  ShieldCheck,
  Zap,
} from 'lucide-react';
import { tenantApi } from '../api/tenant';
import { tasksApi } from '../api/tasks';
import { agentsApi } from '../api/agents';
import { TenantDashboardData, Task } from '../api/types';
import { StatCard } from '../components/common/StatCard';
import { Badge } from '../components/common/Badge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { Modal } from '../components/common/Modal';

export const DashboardPage: React.FC = () => {
  const [data, setData] = useState<TenantDashboardData | null>(null);
  const [recentTasks, setRecentTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Quick Action Modals
  const [isTaskModalOpen, setIsTaskModalOpen] = useState(false);
  const [isAgentModalOpen, setIsAgentModalOpen] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Form states
  const [taskTitle, setTaskTitle] = useState('');
  const [taskObjective, setTaskObjective] = useState('');
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [agentName, setAgentName] = useState('');
  const [agentType, setAgentType] = useState('react');

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [dashData, tasksData] = await Promise.all([
        tenantApi.getDashboard(),
        tasksApi.listTasks(),
      ]);
      setData(dashData);
      setRecentTasks(tasksData.slice(0, 5));
    } catch (err: any) {
      setError(err?.message || 'تعذر تحميل بيانات لوحة التحكم');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleCreateTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!taskTitle.trim() || !taskObjective.trim()) {
      setActionError('يرجى ملء عنوان المهمة والهدف المطلوب');
      return;
    }
    setActionLoading(true);
    setActionError(null);
    try {
      await tasksApi.createTask({
        title: taskTitle.trim(),
        objective: taskObjective.trim(),
        agent_id: selectedAgentId || null,
        priority: 'medium',
      });
      setIsTaskModalOpen(false);
      setTaskTitle('');
      setTaskObjective('');
      setSelectedAgentId('');
      loadData();
    } catch (err: any) {
      setActionError(err?.message || 'فشل إنشاء المهمة');
    } finally {
      setActionLoading(false);
    }
  };

  const handleCreateAgent = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agentName.trim()) {
      setActionError('يرجى إدخال اسم الموظف الرقمي');
      return;
    }
    setActionLoading(true);
    setActionError(null);
    try {
      await agentsApi.createAgent({
        name: agentName.trim(),
        agent_type: agentType,
      });
      setIsAgentModalOpen(false);
      setAgentName('');
      loadData();
    } catch (err: any) {
      setActionError(err?.message || 'فشل إضافة الموظف الرقمي');
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return <LoadingState message="جاري استرجاع مؤشرات أداء الشركة والموظفين..." />;
  }

  if (error || !data) {
    return (
      <ErrorState
        title="تعذر تحميل لوحة العمليات"
        message={error || 'حدث خطأ أثناء تحميل بيانات المستأجر'}
        onRetry={loadData}
      />
    );
  }

  const totalAgents = data.agents?.total ?? data.agents?.items?.length ?? 0;
  const activeAgents = data.agents?.items
    ? data.agents.items.filter((a) => (a.status || '').toLowerCase() === 'active').length
    : (data.agents?.by_status?.active ?? 0);
  const successRate = data.tasks?.success_rate_pct ?? 100;
  const currentTokens = data.budget?.current_month_tokens || 0;
  const monthlyLimit = data.budget?.monthly_limit;
  const budgetUsagePercent = monthlyLimit ? Math.min(100, Math.round((currentTokens / monthlyLimit) * 100)) : 0;

  return (
    <div className="space-y-8 animate-fadeIn">
      {/* Welcome Banner */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-slate-900 via-slate-900/90 to-emerald-950/40 border border-slate-800 p-6 sm:p-8">
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="space-y-2">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold">
              <ShieldCheck className="w-4 h-4" />
              <span>مساحة عمل خاصة ومعزولة: {data.tenant.name}</span>
            </div>
            <h2 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
              أهلاً بك في منصة إدارة الموظفين الرقميين
            </h2>
            <p className="text-sm text-slate-400 max-w-2xl">
              تابع أداء وكلائك الأذكياء، وجدول المهام، وراقب قنوات التواصل واستهلاك الذكاء الاصطناعي بشكل فوري وآمن.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={() => {
                setActionError(null);
                setIsTaskModalOpen(true);
              }}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-sm shadow-lg shadow-emerald-500/20 transition hover:scale-[1.02] active:scale-[0.98]"
            >
              <Plus className="w-4 h-4" />
              <span>إسناد مهمة جديدة</span>
            </button>
            <button
              onClick={() => {
                setActionError(null);
                setIsAgentModalOpen(true);
              }}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-white font-medium text-sm transition"
            >
              <Bot className="w-4 h-4 text-emerald-400" />
              <span>إضافة موظف رقمي</span>
            </button>
            <button
              onClick={loadData}
              className="p-2.5 rounded-xl bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700/80 transition"
              title="تحديث البيانات"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* KPI Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6">
        <StatCard
          title="الموظفون الرقميون"
          value={totalAgents}
          subtitle={`${activeAgents} موظف في وضع التشغيل`}
          icon={Bot}
          color="emerald"
        />
        <StatCard
          title="إجمالي المهام"
          value={data.tasks.total}
          subtitle={`نسبة الإنجاز ${successRate}%`}
          icon={ListTodo}
          color="blue"
          badge={
            <Badge variant={successRate >= 90 ? 'success' : 'warning'}>
              {data.tasks.completed} مكتملة
            </Badge>
          }
        />
        <StatCard
          title="استهلاك الرموز (Tokens)"
          value={currentTokens.toLocaleString()}
          subtitle={monthlyLimit ? `من أصل ${monthlyLimit.toLocaleString()}` : 'بدون سقف شهري'}
          icon={Coins}
          color="purple"
          badge={
            <Badge variant={budgetUsagePercent > 90 ? 'danger' : budgetUsagePercent > 70 ? 'warning' : 'neutral'}>
              {budgetUsagePercent}%
            </Badge>
          }
        />
        <StatCard
          title="قنوات التواصل"
          value={data.channels.total}
          subtitle="واتساب والواجهات البرمجية"
          icon={Radio}
          color="amber"
        />
      </div>

      {/* Two Column Layout: Budget & Health / Recent Tasks */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Budget & System Health (1/3) */}
        <div className="space-y-6">
          {/* AI Quota & Limits */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Coins className="w-4 h-4 text-emerald-400" />
                <span>حصة الذكاء الاصطناعي</span>
              </h3>
              <Link
                to="/usage"
                className="text-xs text-emerald-400 hover:underline flex items-center gap-1 font-semibold"
              >
                <span>التفاصيل</span>
                <ArrowRight className="w-3 h-3 rotate-180" />
              </Link>
            </div>

            <div className="space-y-2">
              <div className="flex justify-between text-xs text-slate-400 font-mono">
                <span>المستهلك هذا الشهر</span>
                <span className="text-white font-bold">{currentTokens.toLocaleString()} رمز</span>
              </div>
              <div className="w-full h-2.5 bg-slate-800 rounded-full overflow-hidden">
                <div
                  className={`h-full transition-all duration-500 rounded-full ${
                    budgetUsagePercent > 90
                      ? 'bg-rose-500'
                      : budgetUsagePercent > 75
                      ? 'bg-amber-500'
                      : 'bg-emerald-500'
                  }`}
                  style={{ width: `${Math.min(100, budgetUsagePercent)}%` }}
                />
              </div>
              <div className="flex justify-between text-[11px] text-slate-400">
                <span>0</span>
                <span>{monthlyLimit ? `${monthlyLimit.toLocaleString()} الحد الأقصى` : 'حساب مفتوح'}</span>
              </div>
            </div>

            <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-xs">
              <span className="text-slate-400">حالة الميزانية:</span>
              <Badge
                variant={
                  data.budget?.alert_level === 'exceeded' || data.budget?.alert_level === 'critical'
                    ? 'danger'
                    : data.budget?.alert_level === 'warning'
                    ? 'warning'
                    : 'success'
                }
              >
                {data.budget?.alert_level === 'exceeded' || data.budget?.alert_level === 'critical'
                  ? 'تم تجاوز الحد'
                  : data.budget?.alert_level === 'warning'
                  ? 'اقترب من الحد'
                  : 'طبيعي ومستقر'}
              </Badge>
            </div>
          </div>

          {/* Outbox & Queue Status */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <Zap className="w-4 h-4 text-teal-400" />
              <span>جاهزية صندوق العمليات (Outbox)</span>
            </h3>

            <div className="grid grid-cols-2 gap-3 text-center">
              <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800">
                <span className="text-[11px] text-slate-400 block mb-1">الرسائل المعالجة</span>
                <span className="text-lg font-bold text-emerald-400">
                  {data.outbox.by_status?.processed || 0}
                </span>
              </div>
              <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800">
                <span className="text-[11px] text-slate-400 block mb-1">رسائل عالقة / خطأ</span>
                <span className={`text-lg font-bold ${data.outbox.dead_letter > 0 ? 'text-rose-400' : 'text-slate-400'}`}>
                  {data.outbox.dead_letter}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2 text-xs text-slate-400 bg-slate-950/40 p-2.5 rounded-lg border border-slate-800/60">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
              <span>النظام يعمل في وضع المعالجة المستمرة والتسليم الموثوق.</span>
            </div>
          </div>
        </div>

        {/* Right Column: Recent Tasks (2/3) */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-2xl p-5 sm:p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-base sm:text-lg font-bold text-white flex items-center gap-2">
                <ListTodo className="w-5 h-5 text-emerald-400" />
                <span>المهام الأخيرة</span>
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">آخر الأنشطة والمهام المسندة لموظفيك</p>
            </div>
            <Link
              to="/tasks"
              className="inline-flex items-center gap-1.5 text-xs sm:text-sm font-semibold text-emerald-400 hover:text-emerald-300 transition"
            >
              <span>عرض كل المهام</span>
              <ArrowRight className="w-4 h-4 rotate-180" />
            </Link>
          </div>

          {recentTasks.length === 0 ? (
            <div className="text-center py-12 border border-dashed border-slate-800 rounded-xl bg-slate-950/30">
              <Clock className="w-8 h-8 text-slate-600 mx-auto mb-2" />
              <p className="text-sm text-slate-400 font-medium">لا توجد مهام مسجلة حتى الآن</p>
              <button
                onClick={() => setIsTaskModalOpen(true)}
                className="mt-3 inline-flex items-center gap-1.5 text-xs text-emerald-400 hover:underline font-semibold"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>أنشئ أول مهمة لموظفيك</span>
              </button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-right text-xs sm:text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400">
                    <th className="pb-3 font-semibold">عنوان المهمة</th>
                    <th className="pb-3 font-semibold">الحالة</th>
                    <th className="pb-3 font-semibold hidden sm:table-cell">الأولوية</th>
                    <th className="pb-3 font-semibold hidden md:table-cell">التاريخ</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-normal">
                  {recentTasks.map((task) => (
                    <tr key={task.id} className="hover:bg-slate-800/30 transition">
                      <td className="py-3 pr-1">
                        <div className="font-semibold text-white truncate max-w-xs">
                          {task.title}
                        </div>
                        <div className="text-[11px] text-slate-400 truncate max-w-sm">
                          {task.objective}
                        </div>
                      </td>
                      <td className="py-3">
                        <Badge
                          variant={
                            task.status === 'completed'
                              ? 'success'
                              : task.status === 'failed'
                              ? 'danger'
                              : task.status === 'in_progress' || task.status === 'running'
                              ? 'info'
                              : 'warning'
                          }
                        >
                          {task.status === 'completed'
                            ? 'مكتملة'
                            : task.status === 'failed'
                            ? 'فاشلة'
                            : task.status === 'in_progress' || task.status === 'running'
                            ? 'قيد التنفيذ'
                            : 'قيد الانتظار'}
                        </Badge>
                      </td>
                      <td className="py-3 hidden sm:table-cell text-slate-300">
                        {task.priority === 'high' ? 'عالية' : task.priority === 'urgent' ? 'طارئة' : 'عادية'}
                      </td>
                      <td className="py-3 hidden md:table-cell text-slate-400 font-mono text-xs">
                        {task.created_at ? new Date(task.created_at).toLocaleDateString('ar-SA') : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Digital Employees Quick Grid */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 sm:p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-base sm:text-lg font-bold text-white flex items-center gap-2">
              <Bot className="w-5 h-5 text-emerald-400" />
              <span>فريق الموظفين الرقميين</span>
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">الوكلاء المتخصصون الجاهزون لتنفيذ الأعمال</p>
          </div>
          <Link
            to="/agents"
            className="inline-flex items-center gap-1.5 text-xs sm:text-sm font-semibold text-emerald-400 hover:text-emerald-300 transition"
          >
            <span>إدارة الفريق</span>
            <ArrowRight className="w-4 h-4 rotate-180" />
          </Link>
        </div>

        {data.agents.items.length === 0 ? (
          <div className="text-center py-8 border border-dashed border-slate-800 rounded-xl">
            <p className="text-sm text-slate-400">لم يتم تعيين موظفين رقميين لشركتك بعد</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {data.agents.items.map((agent) => (
              <div
                key={agent.id}
                className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 hover:border-slate-700 transition flex items-center justify-between"
              >
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
                    <Bot className="w-5 h-5" />
                  </div>
                  <div>
                    <h4 className="text-sm font-bold text-white">{agent.name}</h4>
                    <span className="text-[11px] text-slate-400 font-mono">
                      {agent.agent_type || 'مساعد ذكي'}
                    </span>
                  </div>
                </div>
                <Badge variant={agent.status === 'active' ? 'success' : 'neutral'}>
                  {agent.status === 'active' ? 'نشط' : 'متوقف'}
                </Badge>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create Task Modal */}
      <Modal
        isOpen={isTaskModalOpen}
        onClose={() => setIsTaskModalOpen(false)}
        title="إسناد مهمة جديدة للموظف الرقمي"
        description="حدد تفاصيل المهمة والهدف المطلوب وسيقوم الوكيل بتنفيذها تلقائياً."
      >
        <form onSubmit={handleCreateTask} className="space-y-4">
          {actionError && (
            <div className="p-3 rounded-lg bg-rose-950/50 border border-rose-800 text-rose-300 text-xs flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              <span>{actionError}</span>
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              عنوان المهمة <span className="text-rose-400">*</span>
            </label>
            <input
              type="text"
              value={taskTitle}
              onChange={(e) => setTaskTitle(e.target.value)}
              placeholder="مثال: تحليل تقرير المبيعات الأسبوعي"
              required
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              الهدف والتفاصيل <span className="text-rose-400">*</span>
            </label>
            <textarea
              value={taskObjective}
              onChange={(e) => setTaskObjective(e.target.value)}
              placeholder="صف بالتفصيل ما ترغب في أن ينجزه الوكيل، وأي مخرجات محددة مطلوبة..."
              rows={4}
              required
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition resize-none"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              تعيين إلى موظف رقمي محدد (اختياري)
            </label>
            <select
              value={selectedAgentId}
              onChange={(e) => setSelectedAgentId(e.target.value)}
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500 transition"
            >
              <option value="">توجيه تلقائي لأفضل موظف متاح</option>
              {data.agents.items.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name} ({agent.agent_type})
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
            <button
              type="button"
              onClick={() => setIsTaskModalOpen(false)}
              className="px-4 py-2 rounded-xl text-slate-400 hover:text-white text-xs sm:text-sm font-medium transition"
            >
              إلغاء
            </button>
            <button
              type="submit"
              disabled={actionLoading}
              className="px-5 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs sm:text-sm transition disabled:opacity-50"
            >
              {actionLoading ? 'جاري الإسناد...' : 'تأكيد وإسناد المهمة'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Create Agent Modal */}
      <Modal
        isOpen={isAgentModalOpen}
        onClose={() => setIsAgentModalOpen(false)}
        title="إضافة موظف رقمي جديد"
        description="أنشئ وكيل ذكاء اصطناعي جديد ضمن نطاق شركتك لإسناد مهام محددة إليه."
      >
        <form onSubmit={handleCreateAgent} className="space-y-4">
          {actionError && (
            <div className="p-3 rounded-lg bg-rose-950/50 border border-rose-800 text-rose-300 text-xs flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              <span>{actionError}</span>
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              اسم الموظف الرقمي <span className="text-rose-400">*</span>
            </label>
            <input
              type="text"
              value={agentName}
              onChange={(e) => setAgentName(e.target.value)}
              placeholder="مثال: منسق خدمة العملاء، مساعد المبيعات"
              required
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              نمط وسلوك الوكيل (Agent Type)
            </label>
            <select
              value={agentType}
              onChange={(e) => setAgentType(e.target.value)}
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500 transition"
            >
              <option value="react">وكيل تفاعلي تحليلي (ReAct Engine)</option>
              <option value="assistant">مساعد عام لإدارة الأعمال (General Assistant)</option>
              <option value="specialist">وكيل مهام متخصصة (Task Specialist)</option>
            </select>
          </div>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
            <button
              type="button"
              onClick={() => setIsAgentModalOpen(false)}
              className="px-4 py-2 rounded-xl text-slate-400 hover:text-white text-xs sm:text-sm font-medium transition"
            >
              إلغاء
            </button>
            <button
              type="submit"
              disabled={actionLoading}
              className="px-5 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs sm:text-sm transition disabled:opacity-50"
            >
              {actionLoading ? 'جاري الإضافة...' : 'إضافة الموظف'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
