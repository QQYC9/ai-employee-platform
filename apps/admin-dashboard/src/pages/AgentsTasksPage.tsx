import React, { useEffect, useState } from 'react';
import { tasksApi } from '../api/tasks';
import { AgentItem, TaskItem } from '../api/types';
import { Badge } from '../components/common/Badge';
import { Modal } from '../components/common/Modal';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import {
  Bot,
  ListTodo,
  Search,
  Filter,
  RotateCcw,
  Ban,
  Eye,
  RefreshCw,
  AlertCircle,
  Clock,
  CheckCircle2,
} from 'lucide-react';

export const AgentsTasksPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'tasks' | 'agents'>('tasks');
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [agents, setAgents] = useState<AgentItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('');

  // Modals
  const [selectedTask, setSelectedTask] = useState<TaskItem | null>(null);
  const [retryTaskTarget, setRetryTaskTarget] = useState<TaskItem | null>(null);
  const [cancelTaskTarget, setCancelTaskTarget] = useState<TaskItem | null>(null);
  const [actionReason, setActionReason] = useState<string>('');

  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  const fetchData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [tasksRes, agentsRes] = await Promise.all([
        tasksApi.listTasks().catch(() => []),
        tasksApi.listAgents().catch(() => []),
      ]);
      setTasks(tasksRes);
      setAgents(agentsRes);
    } catch (err: any) {
      setError(err?.message || 'تعذر استرجاع بيانات المهام والوكلاء');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  // Handle Retry Task
  const handleRetry = async () => {
    if (!retryTaskTarget) return;
    setIsSubmitting(true);
    setActionError(null);
    try {
      await tasksApi.retryTask(retryTaskTarget.id, actionReason || undefined);
      setActionSuccess('تمت جدولة إعادة تشغيل المهمة بنجاح');
      setRetryTaskTarget(null);
      setActionReason('');
      await fetchData();
    } catch (err: any) {
      setActionError(err?.message || 'فشلت عملية إعادة محاولة المهمة');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Handle Cancel Task
  const handleCancel = async () => {
    if (!cancelTaskTarget) return;
    setIsSubmitting(true);
    setActionError(null);
    try {
      await tasksApi.cancelTask(cancelTaskTarget.id, actionReason || undefined);
      setActionSuccess('تم إيقاف المهمة بنجاح');
      setCancelTaskTarget(null);
      setActionReason('');
      await fetchData();
    } catch (err: any) {
      setActionError(err?.message || 'فشلت عملية إيقاف المهمة');
    } finally {
      setIsSubmitting(false);
    }
  };

  const filteredTasks = tasks.filter((t) => {
    const matchesSearch =
      searchTerm === '' ||
      t.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
      t.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      t.objective.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesStatus = statusFilter === '' || t.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const filteredAgents = agents.filter((a) => {
    return (
      searchTerm === '' ||
      a.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      a.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      a.agent_type.toLowerCase().includes(searchTerm.toLowerCase())
    );
  });

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-2xl font-black text-white tracking-tight flex items-center gap-2">
            <Bot className="w-6 h-6 text-blue-400" />
            الوكلاء والمهام التشغيلية
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            متابعة حالة الوكلاء الرقميين، استعراض تفاصيل المهام، وتنفيذ عمليات الإيقاف وإعادة المحاولة
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={fetchData}
            className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-3.5 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 border border-slate-800 transition"
            title="تحديث"
          >
            <RefreshCw className="w-4 h-4" />
            <span>تحديث</span>
          </button>
        </div>
      </div>

      {/* Tenant Scoping Security Notice */}
      <div className="flex items-start gap-2.5 rounded-xl border border-blue-900/40 bg-blue-950/20 px-4 py-3 text-xs text-blue-300">
        <Bot className="w-4 h-4 text-blue-400 flex-shrink-0 mt-0.5" />
        <div className="leading-relaxed">
          <strong className="text-white">نطاق الاستعلام التشغيلي:</strong> يعرض هذا القسم المهام والوكلاء المرتبطين بسياق المستأجر الحالي للمستخدم المصرح به، التزاماً بضوابط العزل التام للمستأجرين (Tenant Isolation) المطبقة في الـ Backend.
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-800 pb-3">
        <button
          onClick={() => setActiveTab('tasks')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition ${
            activeTab === 'tasks'
              ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-950/50'
              : 'text-slate-400 hover:text-white hover:bg-slate-900'
          }`}
        >
          <ListTodo className="w-4 h-4" />
          <span>قائمة المهام ({tasks.length})</span>
        </button>
        <button
          onClick={() => setActiveTab('agents')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition ${
            activeTab === 'agents'
              ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-950/50'
              : 'text-slate-400 hover:text-white hover:bg-slate-900'
          }`}
        >
          <Bot className="w-4 h-4" />
          <span>الوكلاء الرقميون ({agents.length})</span>
        </button>
      </div>

      {actionSuccess && (
        <div className="flex items-center justify-between gap-2 rounded-xl bg-emerald-950/60 p-3.5 text-xs text-emerald-300 border border-emerald-900">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4" />
            <span>{actionSuccess}</span>
          </div>
          <button onClick={() => setActionSuccess(null)} className="text-emerald-400 hover:text-white">✕</button>
        </div>
      )}

      {/* Search & Filter Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4 backdrop-blur">
        <div className="relative w-full sm:w-80">
          <div className="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none text-slate-400">
            <Search className="w-4 h-4" />
          </div>
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder={activeTab === 'tasks' ? 'بحث بعنوان المهمة أو المعرف...' : 'بحث باسم الوكيل أو المعرف...'}
            className="w-full rounded-lg border border-slate-800 bg-slate-950 pr-9 pl-4 py-2 text-xs text-white placeholder-slate-500 focus:border-emerald-500 focus:outline-none"
          />
        </div>

        {activeTab === 'tasks' && (
          <div className="flex items-center gap-3 w-full sm:w-auto">
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <Filter className="w-4 h-4" />
              <span>الحالة:</span>
            </div>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-white focus:border-emerald-500 focus:outline-none"
            >
              <option value="">كافة الحالات</option>
              <option value="completed">مكتملة (Completed)</option>
              <option value="in_progress">قيد التنفيذ (In Progress)</option>
              <option value="pending">قيد الانتظار (Pending)</option>
              <option value="failed">فاشلة (Failed)</option>
              <option value="waiting_approval">بانتظار الموافقة (Waiting Approval)</option>
              <option value="cancelled">ملغاة (Cancelled)</option>
            </select>
          </div>
        )}
      </div>

      {/* Content */}
      {isLoading ? (
        <LoadingState message="جاري استرجاع السجلات..." />
      ) : error ? (
        <ErrorState message={error} onRetry={fetchData} />
      ) : activeTab === 'tasks' ? (
        filteredTasks.length === 0 ? (
          <EmptyState
            title="لم يتم العثور على أي مهمة"
            description="لم يتم تسجيل أي مهمة تطابق شروط البحث الحالية."
            icon={ListTodo}
          />
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/40">
            <table className="w-full text-right border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-800 bg-slate-950/80 text-slate-400">
                  <th className="py-3.5 px-4 font-semibold">المهمة والهدف</th>
                  <th className="py-3.5 px-4 font-semibold">الحالة</th>
                  <th className="py-3.5 px-4 font-semibold">الأولوية</th>
                  <th className="py-3.5 px-4 font-semibold">التوقيت</th>
                  <th className="py-3.5 px-4 font-semibold text-left">الإجراءات المتاحة</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {filteredTasks.map((task) => (
                  <tr key={task.id} className="hover:bg-slate-800/30 transition duration-150">
                    <td className="py-3.5 px-4">
                      <div className="font-bold text-white text-sm">{task.title}</div>
                      <div className="text-[11px] text-slate-400 line-clamp-1 mt-0.5">
                        {task.objective}
                      </div>
                      <div className="text-[10px] text-slate-500 font-mono mt-1">
                        ID: {task.id}
                      </div>
                    </td>
                    <td className="py-3.5 px-4">
                      <Badge status={task.status} />
                    </td>
                    <td className="py-3.5 px-4">
                      <span className="font-mono text-slate-300 uppercase">{task.priority}</span>
                    </td>
                    <td className="py-3.5 px-4 text-slate-400">
                      <div className="flex items-center gap-1 text-[11px]">
                        <Clock className="w-3.5 h-3.5 text-slate-500" />
                        <span>{task.created_at ? new Date(task.created_at).toLocaleString('ar-EG') : 'غير متوفر'}</span>
                      </div>
                    </td>
                    <td className="py-3.5 px-4 text-left">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => setSelectedTask(task)}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 px-2.5 py-1.5 text-xs text-slate-200 hover:bg-slate-700 transition"
                          title="عرض التفاصيل والنتائج"
                        >
                          <Eye className="w-3.5 h-3.5 text-blue-400" />
                          <span>تفاصيل</span>
                        </button>

                        {task.status === 'failed' && (
                          <button
                            onClick={() => {
                              setRetryTaskTarget(task);
                              setActionReason('');
                              setActionError(null);
                            }}
                            className="inline-flex items-center gap-1.5 rounded-lg bg-amber-950/60 border border-amber-800/70 px-2.5 py-1.5 text-xs text-amber-300 hover:bg-amber-900 transition"
                            title="إعادة محاولة المهمة الفاشلة"
                          >
                            <RotateCcw className="w-3.5 h-3.5" />
                            <span>إعادة</span>
                          </button>
                        )}

                        {['in_progress', 'pending', 'waiting_approval'].includes(task.status) && (
                          <button
                            onClick={() => {
                              setCancelTaskTarget(task);
                              setActionReason('');
                              setActionError(null);
                            }}
                            className="inline-flex items-center gap-1.5 rounded-lg bg-rose-950/60 border border-rose-800/70 px-2.5 py-1.5 text-xs text-rose-300 hover:bg-rose-900 transition"
                            title="إيقاف المهمة"
                          >
                            <Ban className="w-3.5 h-3.5" />
                            <span>إيقاف</span>
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : (
        /* Agents Tab */
        filteredAgents.length === 0 ? (
          <EmptyState
            title="لا يوجد وكلاء رقميون"
            description="لم يتم العثور على وكلاء مسجلين."
            icon={Bot}
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {filteredAgents.map((agent) => (
              <div
                key={agent.id}
                className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 backdrop-blur flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2.5">
                      <div className="w-9 h-9 rounded-xl bg-blue-950 border border-blue-800 flex items-center justify-center text-blue-400">
                        <Bot className="w-5 h-5" />
                      </div>
                      <div>
                        <h4 className="text-sm font-bold text-white">{agent.name}</h4>
                        <span className="text-[10px] text-slate-400 font-mono">النوع: {agent.agent_type}</span>
                      </div>
                    </div>
                    <Badge status={agent.status} />
                  </div>
                  <div className="text-[11px] text-slate-500 font-mono truncate" title={agent.id}>
                    ID: {agent.id}
                  </div>
                </div>

                <div className="mt-4 pt-3 border-t border-slate-800/60 flex items-center justify-between text-xs text-slate-400">
                  <span>صلاحيات الوكيل: كاملة</span>
                  <span className="text-emerald-400">جاهز للتشغيل</span>
                </div>
              </div>
            ))}
          </div>
        )
      )}

      {/* Task Details Modal */}
      <Modal
        isOpen={!!selectedTask}
        onClose={() => setSelectedTask(null)}
        title={`تفاصيل المهمة: ${selectedTask?.title}`}
        size="lg"
        footer={
          <button
            onClick={() => setSelectedTask(null)}
            className="rounded-lg bg-slate-800 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-700 transition"
          >
            إغلاق
          </button>
        }
      >
        {selectedTask && (
          <div className="space-y-5 text-xs text-right">
            <div className="grid grid-cols-2 gap-4 rounded-xl border border-slate-800 bg-slate-950/60 p-4">
              <div>
                <span className="text-slate-400 block mb-1">معرف المهمة:</span>
                <span className="font-mono text-slate-200">{selectedTask.id}</span>
              </div>
              <div>
                <span className="text-slate-400 block mb-1">المستأجر:</span>
                <span className="font-mono text-slate-200">{selectedTask.tenant_id}</span>
              </div>
              <div>
                <span className="text-slate-400 block mb-1">الحالة:</span>
                <Badge status={selectedTask.status} />
              </div>
              <div>
                <span className="text-slate-400 block mb-1">الأولوية:</span>
                <span className="font-mono uppercase text-slate-200">{selectedTask.priority}</span>
              </div>
            </div>

            <div>
              <span className="text-slate-400 block mb-1 font-semibold">الهدف المحدد:</span>
              <p className="rounded-lg bg-slate-950 p-3 text-slate-300 leading-relaxed border border-slate-800">
                {selectedTask.objective}
              </p>
            </div>

            {selectedTask.error && (
              <div>
                <span className="text-rose-400 block mb-1 font-semibold flex items-center gap-1.5">
                  <AlertCircle className="w-4 h-4" />
                  سجل الخطأ المسجل (Execution Error):
                </span>
                <pre className="rounded-lg bg-rose-950/40 p-3 text-rose-300 font-mono text-[11px] overflow-x-auto border border-rose-900/60 leading-relaxed">
                  {selectedTask.error}
                </pre>
              </div>
            )}

            {selectedTask.result && (
              <div>
                <span className="text-emerald-400 block mb-1 font-semibold">نتيجة التنفيذ:</span>
                <pre className="rounded-lg bg-slate-950 p-3 text-slate-300 font-mono text-[11px] overflow-x-auto border border-slate-800 max-h-48 leading-relaxed">
                  {JSON.stringify(selectedTask.result, null, 2)}
                </pre>
              </div>
            )}

            {selectedTask.plan && (
              <div>
                <span className="text-slate-400 block mb-1 font-semibold">خطة الخطوات (Task Plan):</span>
                <pre className="rounded-lg bg-slate-950 p-3 text-slate-300 font-mono text-[11px] overflow-x-auto border border-slate-800 max-h-48 leading-relaxed">
                  {JSON.stringify(selectedTask.plan, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* Retry Modal */}
      <Modal
        isOpen={!!retryTaskTarget}
        onClose={() => setRetryTaskTarget(null)}
        title="تأكيد إعادة تشغيل المهمة الفاشلة"
        footer={
          <>
            <button
              onClick={() => setRetryTaskTarget(null)}
              className="rounded-lg bg-slate-800 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-700 transition"
            >
              إلغاء
            </button>
            <button
              onClick={handleRetry}
              disabled={isSubmitting}
              className="rounded-lg bg-amber-600 px-4 py-2 text-xs font-bold text-white hover:bg-amber-500 transition disabled:opacity-50"
            >
              {isSubmitting ? 'جاري إعادة المحاولة...' : 'تأكيد إعادة المحاولة'}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          {actionError && (
            <div className="rounded-lg bg-rose-950/60 p-3 text-xs text-rose-300 border border-rose-900">
              {actionError}
            </div>
          )}
          <p className="text-xs text-slate-300 leading-relaxed">
            سيتم إعادة تعيين حالة المهمة <strong>{retryTaskTarget?.title}</strong> وإدراجها مجدداً في دورة التنفيذ التشغيلية عبر المحرك الذكي.
          </p>
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              سبب إعادة المحاولة (اختياري):
            </label>
            <input
              type="text"
              value={actionReason}
              onChange={(e) => setActionReason(e.target.value)}
              placeholder="مثال: تصحيح إعدادات النموذج أو استقرار الشبكة"
              className="w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white focus:border-emerald-500 focus:outline-none"
            />
          </div>
        </div>
      </Modal>

      {/* Cancel Modal */}
      <Modal
        isOpen={!!cancelTaskTarget}
        onClose={() => setCancelTaskTarget(null)}
        title="تأكيد إيقاف المهمة"
        footer={
          <>
            <button
              onClick={() => setCancelTaskTarget(null)}
              className="rounded-lg bg-slate-800 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-700 transition"
            >
              تراجع
            </button>
            <button
              onClick={handleCancel}
              disabled={isSubmitting}
              className="rounded-lg bg-rose-600 px-4 py-2 text-xs font-bold text-white hover:bg-rose-500 transition disabled:opacity-50"
            >
              {isSubmitting ? 'جاري الإيقاف...' : 'إيقاف المهمة الآن'}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          {actionError && (
            <div className="rounded-lg bg-rose-950/60 p-3 text-xs text-rose-300 border border-rose-900">
              {actionError}
            </div>
          )}
          <p className="text-xs text-slate-300 leading-relaxed">
            هل أنت متأكد من رغبتك في إيقاف المهمة <strong>{cancelTaskTarget?.title}</strong>؟ سيتم نقل حالتها إلى ملغاة (cancelled).
          </p>
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              سبب الإلغاء:
            </label>
            <input
              type="text"
              value={actionReason}
              onChange={(e) => setActionReason(e.target.value)}
              placeholder="مثال: طلب المشرف أو مدخلات غير صحيحة"
              className="w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white focus:border-emerald-500 focus:outline-none"
            />
          </div>
        </div>
      </Modal>
    </div>
  );
};
