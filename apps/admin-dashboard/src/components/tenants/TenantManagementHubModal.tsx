import React, { useEffect, useState } from 'react';
import {
  X,
  RefreshCw,
  ListTodo,
  AlertTriangle,
  Cpu,
  Layers,
  Activity,
  CheckCircle2,
  ShieldAlert,
  Key,
  Power,
  Building2,
} from 'lucide-react';
import { adminApi } from '../../api/admin';
import {
  TenantItem,
  TaskItem,
  TenantErrorsResponse,
  TenantCapabilitiesResponse,
  ExecutionTraceItem,
  ExecutionStepItem,
} from '../../api/types';
import { Badge } from '../common/Badge';
import { LoadingState } from '../common/LoadingState';
import { EmptyState } from '../common/EmptyState';

interface TenantManagementHubModalProps {
  tenant: TenantItem | null;
  isOpen: boolean;
  onClose: () => void;
  onTenantUpdated?: () => void;
}

type TabType = 'tasks' | 'errors' | 'capabilities' | 'integrations' | 'traces';

export const TenantManagementHubModal: React.FC<TenantManagementHubModalProps> = ({
  tenant,
  isOpen,
  onClose,
  onTenantUpdated,
}) => {
  const [activeTab, setActiveTab] = useState<TabType>('tasks');
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Tab 1: Tasks State
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [taskStatusFilter, setTaskStatusFilter] = useState<string>('');
  const [cancellingTaskId, setCancellingTaskId] = useState<string | null>(null);
  const [cancelReason, setCancelReason] = useState<string>('');
  const [isCancelling, setIsCancelling] = useState<boolean>(false);

  // Tab 2: Errors State
  const [errorsData, setErrorsData] = useState<TenantErrorsResponse | null>(null);

  // Tab 3: Capabilities State
  const [capabilitiesData, setCapabilitiesData] = useState<TenantCapabilitiesResponse | null>(null);

  // Tab 4: Integrations State
  const [integrations, setIntegrations] = useState<any[]>([]);
  const [updatingIntegrationId, setUpdatingIntegrationId] = useState<string | null>(null);

  // Tab 5: Traces State
  const [traces, setTraces] = useState<ExecutionTraceItem[]>([]);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [traceSteps, setTraceSteps] = useState<ExecutionStepItem[]>([]);
  const [loadingSteps, setLoadingSteps] = useState<boolean>(false);

  useEffect(() => {
    if (isOpen && tenant) {
      loadTabData(activeTab);
    }
  }, [isOpen, tenant, activeTab]);

  const loadTabData = async (tab: TabType) => {
    if (!tenant) return;
    setIsLoading(true);
    setError(null);
    setActionSuccess(null);

    try {
      if (tab === 'tasks') {
        const res = await adminApi.getTenantTasks(tenant.id, taskStatusFilter || undefined);
        setTasks(res.tasks || []);
      } else if (tab === 'errors') {
        const res = await adminApi.getTenantErrors(tenant.id);
        setErrorsData(res);
      } else if (tab === 'capabilities') {
        const res = await adminApi.getTenantCapabilities(tenant.id);
        setCapabilitiesData(res);
      } else if (tab === 'integrations') {
        const res = await adminApi.getTenantIntegrations(tenant.id);
        setIntegrations(res || []);
      } else if (tab === 'traces') {
        const res = await adminApi.getTenantTraces(tenant.id);
        setTraces(res.items || []);
        setSelectedTraceId(null);
        setTraceSteps([]);
      }
    } catch (err: any) {
      setError(err?.message || 'تعذر تحميل بيانات مركز المستأجر');
    } finally {
      setIsLoading(false);
    }
  };

  const handleCancelTask = async (taskId: string) => {
    if (!tenant || !cancelReason.trim()) return;
    if (cancelReason.trim().length < 15) {
      setError('سبب الإلغاء الطارئ يجب ألا يقل عن 15 حرفاً لضمان التدقيق الأمني');
      return;
    }

    setIsCancelling(true);
    setError(null);
    try {
      await adminApi.emergencyCancelTask(tenant.id, taskId, cancelReason.trim());
      setActionSuccess('تم إلغاء المهمة بنجاح وتوثيق سبب الإلغاء في سجل التدقيق.');
      setCancellingTaskId(null);
      setCancelReason('');
      await loadTabData('tasks');
      if (onTenantUpdated) onTenantUpdated();
    } catch (err: any) {
      setError(err?.message || 'فشل إلغاء المهمة');
    } finally {
      setIsCancelling(false);
    }
  };

  const handleToggleIntegrationStatus = async (integrationId: string, currentStatus: string) => {
    if (!tenant) return;
    const newStatus = currentStatus === 'active' ? 'disabled' : 'active';
    setUpdatingIntegrationId(integrationId);
    setError(null);
    try {
      await adminApi.updateTenantIntegrationStatus(tenant.id, integrationId, newStatus);
      setActionSuccess(`تم تحديث حالة التكامل إلى: ${newStatus}`);
      await loadTabData('integrations');
    } catch (err: any) {
      setError(err?.message || 'فشل تحديث حالة التكامل');
    } finally {
      setUpdatingIntegrationId(null);
    }
  };

  const handleViewTraceSteps = async (traceUuid: string) => {
    if (!tenant) return;
    setSelectedTraceId(traceUuid);
    setLoadingSteps(true);
    try {
      const steps = await adminApi.getTenantTraceSteps(tenant.id, traceUuid, 'tree');
      setTraceSteps(steps || []);
    } catch (err: any) {
      setError(err?.message || 'تعذر جلب خطوات التتبع');
    } finally {
      setLoadingSteps(false);
    }
  };

  if (!isOpen || !tenant) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-150">
      <div className="relative w-full max-w-6xl max-h-[92vh] rounded-2xl border border-slate-800 bg-slate-950 shadow-2xl flex flex-col overflow-hidden text-right">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800/80 bg-slate-900/60">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
              <Building2 className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-black text-white">{tenant.name}</h2>
                <Badge status={tenant.status} />
              </div>
              <p className="text-xs text-slate-400 mt-0.5 font-mono">
                المعرف: {tenant.id} | الاسم اللطيف: {tenant.slug}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => loadTabData(activeTab)}
              className="p-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800/80 transition"
              title="تحديث البيانات"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
            <button
              onClick={onClose}
              className="p-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800/80 transition"
              title="إغلاق"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="flex items-center gap-2 px-6 pt-3 border-b border-slate-800/80 bg-slate-900/30 overflow-x-auto">
          <button
            onClick={() => setActiveTab('tasks')}
            className={`flex items-center gap-2 px-4 py-2.5 text-xs font-bold rounded-t-xl transition border-b-2 ${
              activeTab === 'tasks'
                ? 'border-emerald-500 text-emerald-400 bg-slate-900/80'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <ListTodo className="w-4 h-4" />
            <span>المهام التشغيلية ({tenant.task_count})</span>
          </button>

          <button
            onClick={() => setActiveTab('errors')}
            className={`flex items-center gap-2 px-4 py-2.5 text-xs font-bold rounded-t-xl transition border-b-2 ${
              activeTab === 'errors'
                ? 'border-rose-500 text-rose-400 bg-slate-900/80'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <AlertTriangle className="w-4 h-4" />
            <span>مركز تشخيص الأخطاء</span>
            {tenant.failed_task_count > 0 && (
              <span className="px-1.5 py-0.2 bg-rose-950 text-rose-300 text-[10px] rounded-full border border-rose-800">
                {tenant.failed_task_count}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('capabilities')}
            className={`flex items-center gap-2 px-4 py-2.5 text-xs font-bold rounded-t-xl transition border-b-2 ${
              activeTab === 'capabilities'
                ? 'border-purple-500 text-purple-400 bg-slate-900/80'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Layers className="w-4 h-4" />
            <span>المهارات والقدرات</span>
          </button>

          <button
            onClick={() => setActiveTab('integrations')}
            className={`flex items-center gap-2 px-4 py-2.5 text-xs font-bold rounded-t-xl transition border-b-2 ${
              activeTab === 'integrations'
                ? 'border-blue-500 text-blue-400 bg-slate-900/80'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Key className="w-4 h-4" />
            <span>تكاملات المستأجر</span>
          </button>

          <button
            onClick={() => setActiveTab('traces')}
            className={`flex items-center gap-2 px-4 py-2.5 text-xs font-bold rounded-t-xl transition border-b-2 ${
              activeTab === 'traces'
                ? 'border-teal-500 text-teal-400 bg-slate-900/80'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Activity className="w-4 h-4" />
            <span>سجلات التتبع والخطوات</span>
          </button>
        </div>

        {/* Success / Error Alerts */}
        {actionSuccess && (
          <div className="mx-6 mt-4 p-3 rounded-xl bg-emerald-950/60 border border-emerald-800 text-emerald-300 text-xs flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span>{actionSuccess}</span>
            </div>
            <button onClick={() => setActionSuccess(null)} className="text-emerald-400 hover:text-white">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}
        {error && (
          <div className="mx-6 mt-4 p-3 rounded-xl bg-rose-950/60 border border-rose-800 text-rose-300 text-xs flex items-center justify-between">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-rose-400" />
              <span>{error}</span>
            </div>
            <button onClick={() => setError(null)} className="text-rose-400 hover:text-white">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Tab Content Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {isLoading ? (
            <LoadingState message="جاري استرجاع بيانات القسم..." />
          ) : (
            <>
              {/* TAB 1: TASKS */}
              {activeTab === 'tasks' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-slate-400">
                      استعراض ومراقبة مهام الذكاء الاصطناعي للمستأجر مع إمكانية الإلغاء الطارئ للمهام المتعثرة.
                    </p>
                    <select
                      value={taskStatusFilter}
                      onChange={(e) => {
                        setTaskStatusFilter(e.target.value);
                        adminApi.getTenantTasks(tenant.id, e.target.value || undefined).then((res) => {
                          setTasks(res.tasks || []);
                        });
                      }}
                      className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-1.5 text-xs text-white focus:outline-none"
                    >
                      <option value="">كافة الحالات</option>
                      <option value="completed">مكتملة (Completed)</option>
                      <option value="failed">فاشلة (Failed)</option>
                      <option value="in_progress">قيد التنفيذ (In Progress)</option>
                      <option value="pending">قيد الانتظار (Pending)</option>
                    </select>
                  </div>

                  {tasks.length === 0 ? (
                    <EmptyState
                      title="لا توجد مهام مسجلة"
                      description="لم يتم تنفيذ أي مهام لهذا المستأجر حتى الآن أو لا توجد نتائج مطابقة للتصفية."
                      icon={ListTodo}
                    />
                  ) : (
                    <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/40">
                      <table className="w-full text-right border-collapse text-xs">
                        <thead>
                          <tr className="border-b border-slate-800 bg-slate-950/80 text-slate-400">
                            <th className="py-3 px-4">المهمة</th>
                            <th className="py-3 px-4">الهدف</th>
                            <th className="py-3 px-4">الحالة</th>
                            <th className="py-3 px-4">الأولوية</th>
                            <th className="py-3 px-4">النتيجة / الخطأ</th>
                            <th className="py-3 px-4 text-left">إجراء الطوارئ</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/60">
                          {tasks.map((task) => (
                            <tr key={task.id} className="hover:bg-slate-800/30">
                              <td className="py-3 px-4 font-bold text-white">{task.title}</td>
                              <td className="py-3 px-4 text-slate-300 max-w-xs truncate">{task.objective}</td>
                              <td className="py-3 px-4">
                                <Badge status={task.status} />
                              </td>
                              <td className="py-3 px-4 text-slate-400 font-mono text-[11px]">{task.priority}</td>
                              <td className="py-3 px-4 max-w-xs">
                                {task.error ? (
                                  <span className="text-rose-400 truncate block" title={task.error}>
                                    {task.error}
                                  </span>
                                ) : task.result && Object.keys(task.result).length > 0 ? (
                                  <span className="text-slate-400 truncate block">
                                    {JSON.stringify(task.result)}
                                  </span>
                                ) : (
                                  <span className="text-slate-500 italic">لا توجد مخرجات</span>
                                )}
                              </td>
                              <td className="py-3 px-4 text-left">
                                {['pending', 'in_progress'].includes(task.status) && (
                                  <button
                                    onClick={() => setCancellingTaskId(task.id)}
                                    className="px-2.5 py-1 text-xs font-semibold rounded-lg bg-rose-950/80 border border-rose-800 text-rose-300 hover:bg-rose-900 transition flex items-center gap-1"
                                  >
                                    <ShieldAlert className="w-3.5 h-3.5" />
                                    <span>إلغاء طارئ</span>
                                  </button>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* Task Cancellation Prompt */}
                  {cancellingTaskId && (
                    <div className="p-4 rounded-xl border border-rose-900 bg-rose-950/40 space-y-3">
                      <div className="flex items-center justify-between text-rose-300 font-bold text-xs">
                        <span className="flex items-center gap-1.5">
                          <AlertTriangle className="w-4 h-4 text-rose-400" />
                          إلغاء طارئ للمهمة ({cancellingTaskId})
                        </span>
                        <button onClick={() => setCancellingTaskId(null)} className="text-slate-400 hover:text-white">
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                      <p className="text-xs text-slate-400">
                        يتطلب نظام التدقيق الأمني تدوين سبب صريح للإلغاء لا يقل عن 15 حرفاً لحفظه في سجلات الامتثال.
                      </p>
                      <input
                        type="text"
                        value={cancelReason}
                        onChange={(e) => setCancelReason(e.target.value)}
                        placeholder="سبب الإلغاء الطارئ (مثال: مهمة متعثرة تستهلك موارد مفرطة دون استجابة)..."
                        className="w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none"
                      />
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => setCancellingTaskId(null)}
                          className="px-3 py-1.5 rounded-lg bg-slate-800 text-xs text-slate-300 hover:bg-slate-700"
                        >
                          تراجع
                        </button>
                        <button
                          onClick={() => handleCancelTask(cancellingTaskId)}
                          disabled={isCancelling}
                          className="px-3 py-1.5 rounded-lg bg-rose-600 text-xs font-bold text-white hover:bg-rose-500 disabled:opacity-50"
                        >
                          {isCancelling ? 'جاري الإلغاء...' : 'تأكيد الإلغاء والتدقيق'}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* TAB 2: ERROR DIAGNOSTICS */}
              {activeTab === 'errors' && (
                <div className="space-y-6">
                  <div className="flex items-center justify-between p-4 rounded-xl border border-slate-800 bg-slate-900/50">
                    <div>
                      <h3 className="font-bold text-white text-sm">مركز تجميع وتشخيص الأعطال</h3>
                      <p className="text-xs text-slate-400 mt-0.5">
                        فحص وتشخيص فوري للأخطاء الحقيقية المسجلة عبر المهام، والتتبعات، واستهلاك مزودي الذكاء الاصطناعي، وصندوق الإرسال (Outbox).
                      </p>
                    </div>
                    <div className="text-center px-4 py-2 rounded-xl bg-slate-950 border border-slate-800">
                      <span className="block text-xl font-black text-rose-400">{errorsData?.total_errors ?? 0}</span>
                      <span className="text-[10px] text-slate-400">إجمالي الأخطاء</span>
                    </div>
                  </div>

                  {errorsData && errorsData.total_errors === 0 ? (
                    <EmptyState
                      title="سجل الأخطاء نظيف تماماً"
                      description="لا توجد أي أخطاء أو تعثرات تشغيلية مسجلة لهذا المستأجر."
                      icon={CheckCircle2}
                    />
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {/* Tasks Errors */}
                      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 space-y-3">
                        <h4 className="font-bold text-slate-200 text-xs flex items-center gap-2">
                          <ListTodo className="w-4 h-4 text-rose-400" />
                          أخطاء المهام ({errorsData?.tasks_errors.length ?? 0})
                        </h4>
                        {errorsData?.tasks_errors.length === 0 ? (
                          <p className="text-xs text-slate-500">لا توجد أخطاء في المهام</p>
                        ) : (
                          <div className="space-y-2">
                            {errorsData?.tasks_errors.map((err) => (
                              <div key={err.id} className="p-2.5 rounded-lg bg-slate-950 border border-slate-800/80 text-xs">
                                <div className="font-semibold text-white">{err.task_title}</div>
                                <div className="text-rose-400 mt-1">{err.error_message || 'خطأ غير محدد'}</div>
                                {err.occurred_at && (
                                  <div className="text-[10px] text-slate-500 mt-1 font-mono">{err.occurred_at}</div>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>

                      {/* Traces Errors */}
                      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 space-y-3">
                        <h4 className="font-bold text-slate-200 text-xs flex items-center gap-2">
                          <Activity className="w-4 h-4 text-amber-400" />
                          أخطاء مسارات التتبع ({errorsData?.traces_errors.length ?? 0})
                        </h4>
                        {errorsData?.traces_errors.length === 0 ? (
                          <p className="text-xs text-slate-500">لا توجد أخطاء في مسارات التتبع</p>
                        ) : (
                          <div className="space-y-2">
                            {errorsData?.traces_errors.map((err) => (
                              <div key={err.id} className="p-2.5 rounded-lg bg-slate-950 border border-slate-800/80 text-xs">
                                <div className="font-semibold text-white">المشغل: {err.trigger_type}</div>
                                <div className="text-amber-400 mt-1 font-mono text-[11px]">
                                  {JSON.stringify(err.error_summary || {})}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>

                      {/* AI Provider Errors */}
                      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 space-y-3">
                        <h4 className="font-bold text-slate-200 text-xs flex items-center gap-2">
                          <Cpu className="w-4 h-4 text-purple-400" />
                          أخطاء مزودي الذكاء الاصطناعي ({errorsData?.ai_errors.length ?? 0})
                        </h4>
                        {errorsData?.ai_errors.length === 0 ? (
                          <p className="text-xs text-slate-500">لا توجد أخطاء في واجهات المزودين</p>
                        ) : (
                          <div className="space-y-2">
                            {errorsData?.ai_errors.map((err) => (
                              <div key={err.id} className="p-2.5 rounded-lg bg-slate-950 border border-slate-800/80 text-xs">
                                <div className="font-semibold text-white">
                                  {err.provider} / {err.model}
                                </div>
                                <div className="text-purple-400 mt-0.5 text-[11px]">التصنيف: {err.error_category}</div>
                                <div className="text-rose-400 mt-1">{err.error_message}</div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>

                      {/* Outbox Dead Letter Errors */}
                      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 space-y-3">
                        <h4 className="font-bold text-slate-200 text-xs flex items-center gap-2">
                          <ShieldAlert className="w-4 h-4 text-red-400" />
                          رسائل صندوق الإرسال الميتة ({errorsData?.outbox_errors.length ?? 0})
                        </h4>
                        {errorsData?.outbox_errors.length === 0 ? (
                          <p className="text-xs text-slate-500">لا توجد رسائل متعثرة في Outbox</p>
                        ) : (
                          <div className="space-y-2">
                            {errorsData?.outbox_errors.map((err) => (
                              <div key={err.id} className="p-2.5 rounded-lg bg-slate-950 border border-slate-800/80 text-xs">
                                <div className="font-semibold text-white">{err.event_type}</div>
                                <div className="text-red-400 mt-1">{err.error_message}</div>
                                <div className="text-[10px] text-slate-500 mt-1 font-mono">
                                  المحاولات: {err.retry_count} | الحالة: {err.status}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* TAB 3: CAPABILITIES SEPARATION */}
              {activeTab === 'capabilities' && (
                <div className="space-y-6">
                  <p className="text-xs text-slate-400">
                    الفصل المعماري الصارم بين مهارات المستأجر الخاصة، ومكتبة المنصة المشتركة، وإصدارات التطوير الذاتي.
                  </p>

                  <div className="space-y-6">
                    {/* 1. Custom Tenant Capabilities */}
                    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 space-y-3">
                      <div className="flex items-center justify-between">
                        <h4 className="font-bold text-emerald-400 text-xs flex items-center gap-2">
                          <Cpu className="w-4 h-4" />
                          مهارات المستأجر الخاصة (Custom Tenant Capabilities)
                        </h4>
                        <span className="text-[11px] font-mono text-slate-400">
                          {capabilitiesData?.tenant_capabilities.length ?? 0} مهارة
                        </span>
                      </div>
                      {!capabilitiesData || capabilitiesData.tenant_capabilities.length === 0 ? (
                        <p className="text-xs text-slate-500">لا توجد مهارات خاصة إضافية لهذا المستأجر.</p>
                      ) : (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          {capabilitiesData.tenant_capabilities.map((cap) => (
                            <div key={cap.id} className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                              <div className="flex items-center justify-between">
                                <span className="font-bold text-white text-xs">{cap.name}</span>
                                <Badge status={cap.is_active ? 'active' : 'disabled'} />
                              </div>
                              <p className="text-[11px] text-slate-400 mt-1">{cap.description || 'لا يوجد وصف'}</p>
                              <div className="text-[10px] text-slate-500 font-mono mt-2">slug: {cap.slug}</div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* 2. Global Shared Approved Library */}
                    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 space-y-3">
                      <div className="flex items-center justify-between">
                        <h4 className="font-bold text-blue-400 text-xs flex items-center gap-2">
                          <Layers className="w-4 h-4" />
                          مكتبة المنصة المشتركة المعتمدة (Approved Global Library)
                        </h4>
                        <span className="text-[11px] font-mono text-slate-400">
                          {capabilitiesData?.shared_capabilities.length ?? 0} مهارة معتمدة
                        </span>
                      </div>
                      {!capabilitiesData || capabilitiesData.shared_capabilities.length === 0 ? (
                        <p className="text-xs text-slate-500">لا توجد مهارات عالمية مسجلة.</p>
                      ) : (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          {capabilitiesData.shared_capabilities.map((cap) => (
                            <div key={cap.id} className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                              <div className="flex items-center justify-between">
                                <span className="font-bold text-white text-xs">{cap.name}</span>
                                <span className="text-[10px] px-2 py-0.5 rounded bg-blue-950/80 text-blue-300 border border-blue-800">
                                  معتمد عالمياً
                                </span>
                              </div>
                              <p className="text-[11px] text-slate-400 mt-1">{cap.description || 'مهارة معيارية للمنصة'}</p>
                              <div className="text-[10px] text-slate-500 font-mono mt-2">slug: {cap.slug}</div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* 3. Self Development Proposals */}
                    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 space-y-3">
                      <div className="flex items-center justify-between">
                        <h4 className="font-bold text-purple-400 text-xs flex items-center gap-2">
                          <Activity className="w-4 h-4" />
                          إصدارات واقتراحات التطوير الذاتي (Self-Development Versions)
                        </h4>
                        <span className="text-[11px] font-mono text-slate-400">
                          {capabilitiesData?.self_development_versions.length ?? 0} إصدار
                        </span>
                      </div>
                      {!capabilitiesData || capabilitiesData.self_development_versions.length === 0 ? (
                        <p className="text-xs text-slate-500">لا توجد اقتراحات تطوير ذاتي معلقة.</p>
                      ) : (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          {capabilitiesData.self_development_versions.map((ver) => (
                            <div key={ver.id} className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                              <div className="flex items-center justify-between">
                                <span className="font-bold text-white text-xs">
                                  {ver.name} (الإصدار {ver.version_number})
                                </span>
                                <Badge status={ver.status} />
                              </div>
                              <p className="text-[11px] text-slate-400 mt-1">{ver.description || 'تطوير ذاتي مولد آلياً'}</p>
                              <div className="flex items-center gap-2 mt-2 text-[10px]">
                                <span className="text-amber-400 font-medium">مستوى الخطورة: {ver.risk_level}</span>
                                <span className="text-slate-600">|</span>
                                <span className="text-slate-500 font-mono">{ver.slug}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 4: TENANT INTEGRATIONS */}
              {activeTab === 'integrations' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="font-bold text-white text-sm">تكاملات الذكاء الاصطناعي للمستأجر</h3>
                      <p className="text-xs text-slate-400 mt-0.5">
                        التكاملات ومفاتيح الربط الخاصة بالمستأجر، مع ضمان تشفير الأسرار وحجبها التام.
                      </p>
                    </div>
                  </div>

                  {integrations.length === 0 ? (
                    <EmptyState
                      title="لا توجد تكاملات خاصة"
                      description="يعتمد هذا المستأجر حالياً على تكاملات المنصة العامة الافتراضية."
                      icon={Key}
                    />
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {integrations.map((intg) => (
                        <div key={intg.id} className="p-4 rounded-xl border border-slate-800 bg-slate-900/40 space-y-3">
                          <div className="flex items-center justify-between">
                            <div>
                              <span className="font-bold text-white text-sm">{intg.name}</span>
                              <div className="text-xs text-slate-400 font-mono mt-0.5">
                                المزود: {intg.provider} | النموذج: {intg.model}
                              </div>
                            </div>
                            <Badge status={intg.status || 'active'} />
                          </div>

                          <div className="p-2.5 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono flex items-center justify-between text-slate-300">
                            <span>مفتاح الـ API المشفر:</span>
                            <span className="text-emerald-400 font-bold">{intg.masked_api_key || '••••••••'}</span>
                          </div>

                          <div className="flex items-center justify-between pt-2 border-t border-slate-800/60">
                            <span className="text-[11px] text-slate-500">
                              {intg.is_default ? 'التكامل الافتراضي' : 'تكامل مخصص'}
                            </span>
                            <button
                              onClick={() => handleToggleIntegrationStatus(intg.id, intg.status || 'active')}
                              disabled={updatingIntegrationId === intg.id}
                              className={`px-3 py-1 text-xs font-semibold rounded-lg transition flex items-center gap-1.5 ${
                                intg.status === 'disabled'
                                  ? 'bg-emerald-950 border border-emerald-800 text-emerald-300 hover:bg-emerald-900'
                                  : 'bg-rose-950 border border-rose-800 text-rose-300 hover:bg-rose-900'
                              }`}
                            >
                              <Power className="w-3.5 h-3.5" />
                              <span>{intg.status === 'disabled' ? 'تفعيل التكامل' : 'تعطيل طارئ'}</span>
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* TAB 5: TRACES & EXECUTION STEPS */}
              {activeTab === 'traces' && (
                <div className="space-y-4">
                  <p className="text-xs text-slate-400">
                    سجلات تتبع مسارات التنفيذ (Execution Traces) وسلسلة الخطوات المنفذة مع المدد الزمنية بالملي ثانية.
                  </p>

                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {/* Traces List */}
                    <div className="space-y-2">
                      <h4 className="font-bold text-xs text-slate-300 mb-2">قائمة التتبعات</h4>
                      {traces.length === 0 ? (
                        <p className="text-xs text-slate-500">لا توجد مسارات تتبع مسجلة لهذا المستأجر.</p>
                      ) : (
                        <div className="space-y-2 max-h-96 overflow-y-auto">
                          {traces.map((tr) => (
                            <div
                              key={tr.id}
                              onClick={() => handleViewTraceSteps(tr.trace_id)}
                              className={`p-3 rounded-xl border cursor-pointer transition text-xs ${
                                selectedTraceId === tr.trace_id
                                  ? 'border-teal-500 bg-teal-950/20'
                                  : 'border-slate-800 bg-slate-900/40 hover:bg-slate-800/40'
                              }`}
                            >
                              <div className="flex items-center justify-between">
                                <span className="font-bold text-white">المشغل: {tr.trigger_type}</span>
                                <Badge status={tr.status} />
                              </div>
                              <div className="flex items-center gap-3 mt-2 text-[11px] text-slate-400 font-mono">
                                <span>المدة: {tr.duration_ms ?? '-'} ms</span>
                                <span>|</span>
                                <span className="truncate max-w-[150px]">{tr.started_at}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Step Details Tree */}
                    <div className="rounded-xl border border-slate-800 bg-slate-900/30 p-4 space-y-3">
                      <h4 className="font-bold text-xs text-slate-300">
                        سلسلة الخطوات (Execution Steps) {selectedTraceId ? `— ${selectedTraceId.slice(0, 8)}` : ''}
                      </h4>
                      {!selectedTraceId ? (
                        <p className="text-xs text-slate-500 italic">اختر مسار تتبع من القائمة لعرض تسلسل خطواته.</p>
                      ) : loadingSteps ? (
                        <LoadingState message="جاري استرجاع خطوات التتبع..." />
                      ) : traceSteps.length === 0 ? (
                        <p className="text-xs text-slate-500">لا توجد خطوات مسجلة لهذا المسار.</p>
                      ) : (
                        <div className="space-y-2 max-h-80 overflow-y-auto">
                          {traceSteps.map((step) => (
                            <div key={step.id} className="p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs">
                              <div className="flex items-center justify-between">
                                <span className="font-semibold text-white">
                                  #{step.step_order} {step.step_name}
                                </span>
                                <Badge status={step.status} />
                              </div>
                              <div className="flex items-center gap-2 mt-1.5 text-[11px] text-slate-400 font-mono">
                                <span>النوع: {step.step_type}</span>
                                <span>|</span>
                                <span>{step.duration_ms ?? '-'} ms</span>
                              </div>
                              {step.error_info && (
                                <div className="mt-2 p-2 rounded bg-rose-950/60 border border-rose-900 text-rose-300 text-[11px]">
                                  {JSON.stringify(step.error_info)}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
