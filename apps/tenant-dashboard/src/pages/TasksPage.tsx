import React, { useEffect, useState } from 'react';
import {
  ListTodo,
  Plus,
  RefreshCw,
  Search,
  AlertTriangle,
  RotateCcw,
  XCircle,
  Eye,
  Bot,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react';
import { tasksApi } from '../api/tasks';
import { agentsApi } from '../api/agents';
import { Task, Agent } from '../api/types';
import { Badge } from '../components/common/Badge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import { Modal } from '../components/common/Modal';

export const TasksPage: React.FC = () => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [agentFilter, setAgentFilter] = useState<string>('all');

  // Create Task Modal
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [objective, setObjective] = useState('');
  const [selectedAgent, setSelectedAgent] = useState('');
  const [priority, setPriority] = useState('medium');
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Details Modal
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);

  // Action states (Retry / Cancel)
  const [actionTaskId, setActionTaskId] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [tasksData, agentsData] = await Promise.all([
        tasksApi.listTasks(),
        agentsApi.listAgents(),
      ]);
      setTasks(tasksData);
      setAgents(agentsData);
    } catch (err: any) {
      setError(err?.message || 'تعذر استرجاع المهام');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !objective.trim()) {
      setCreateError('يرجى تحديد عنوان المهمة والهدف المطلوب');
      return;
    }
    setCreateLoading(true);
    setCreateError(null);
    try {
      await tasksApi.createTask({
        title: title.trim(),
        objective: objective.trim(),
        agent_id: selectedAgent || null,
        priority,
      });
      setIsCreateOpen(false);
      setTitle('');
      setObjective('');
      setSelectedAgent('');
      setPriority('medium');
      loadData();
    } catch (err: any) {
      setCreateError(err?.message || 'فشل إسناد المهمة');
    } finally {
      setCreateLoading(false);
    }
  };

  const handleRetry = async (task: Task) => {
    if (!confirm(`هل أنت متأكد من إعادة محاولة تنفيذ المهمة: "${task.title}"؟`)) {
      return;
    }
    setActionTaskId(task.id);
    setActionLoading(true);
    setActionError(null);
    try {
      await tasksApi.retryTask(task.id, 'إعادة محاولة يدوية من لوحة تحكم المستأجر');
      setActionSuccess(`تمت إعادة جدولة المهمة "${task.title}" بنجاح.`);
      loadData();
      if (selectedTask?.id === task.id) {
        setSelectedTask(null);
      }
    } catch (err: any) {
      setActionError(`فشلت إعادة المحاولة: ${err?.message || 'خطأ غير معروف'}`);
    } finally {
      setActionLoading(false);
      setActionTaskId(null);
      setTimeout(() => setActionSuccess(null), 5000);
    }
  };

  const handleCancel = async (task: Task) => {
    if (!confirm(`هل أنت متأكد من إلغاء المهمة: "${task.title}"؟`)) {
      return;
    }
    setActionTaskId(task.id);
    setActionLoading(true);
    setActionError(null);
    try {
      await tasksApi.cancelTask(task.id, 'إلغاء يدوي من لوحة تحكم المستأجر');
      setActionSuccess(`تم إلغاء المهمة "${task.title}" بنجاح.`);
      loadData();
      if (selectedTask?.id === task.id) {
        setSelectedTask(null);
      }
    } catch (err: any) {
      setActionError(`فشل إلغاء المهمة: ${err?.message || 'خطأ غير معروف'}`);
    } finally {
      setActionLoading(false);
      setActionTaskId(null);
      setTimeout(() => setActionSuccess(null), 5000);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status.toLowerCase()) {
      case 'completed':
        return <Badge variant="success">مكتملة</Badge>;
      case 'failed':
        return <Badge variant="danger">فاشلة</Badge>;
      case 'in_progress':
      case 'running':
        return <Badge variant="info">قيد التنفيذ</Badge>;
      case 'pending':
        return <Badge variant="warning">قيد الانتظار</Badge>;
      case 'cancelled':
        return <Badge variant="neutral">ملغاة</Badge>;
      default:
        return <Badge variant="neutral">{status}</Badge>;
    }
  };

  const filteredTasks = tasks.filter((t) => {
    const matchesSearch =
      t.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
      t.objective.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesStatus =
      statusFilter === 'all' ? true : t.status.toLowerCase() === statusFilter.toLowerCase();
    const matchesAgent =
      agentFilter === 'all' ? true : t.agent_id === agentFilter;
    return matchesSearch && matchesStatus && matchesAgent;
  });

  const getAgentName = (agentId?: string | null) => {
    if (!agentId) return 'توجيه ذكي';
    const a = agents.find((ag) => ag.id === agentId);
    return a ? a.name : 'موظف رقمي';
  };

  if (loading) {
    return <LoadingState message="جاري استرجاع سجل العمليات والمهام..." />;
  }

  if (error) {
    return (
      <ErrorState
        title="تعذر تحميل سجل المهام"
        message={error}
        onRetry={loadData}
      />
    );
  }

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl sm:text-2xl font-extrabold text-white tracking-tight flex items-center gap-2">
            <ListTodo className="w-6 h-6 text-emerald-400" />
            <span>سجل ومتابعة المهام</span>
          </h2>
          <p className="text-xs sm:text-sm text-slate-400 mt-1">
            متابعة مراحل التنفيذ، مراجعة النتائج، وإعادة محاولة المهام المتعثرة
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => {
              setCreateError(null);
              setIsCreateOpen(true);
            }}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs sm:text-sm shadow-lg shadow-emerald-500/20 transition hover:scale-[1.02]"
          >
            <Plus className="w-4 h-4" />
            <span>إسناد مهمة جديدة</span>
          </button>
          <button
            onClick={loadData}
            className="p-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 hover:text-white border border-slate-800 transition"
            title="تحديث المهام"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Action Notification Toasts */}
      {actionSuccess && (
        <div className="p-3.5 rounded-xl bg-emerald-950/70 border border-emerald-800 text-emerald-300 text-xs sm:text-sm flex items-center gap-2 animate-fadeIn">
          <CheckCircle2 className="w-5 h-5 flex-shrink-0 text-emerald-400" />
          <span>{actionSuccess}</span>
        </div>
      )}
      {actionError && (
        <div className="p-3.5 rounded-xl bg-rose-950/70 border border-rose-800 text-rose-300 text-xs sm:text-sm flex items-center gap-2 animate-fadeIn">
          <AlertCircle className="w-5 h-5 flex-shrink-0 text-rose-400" />
          <span>{actionError}</span>
        </div>
      )}

      {/* Filter and Search Bar */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 flex flex-col lg:flex-row gap-4 justify-between items-center">
        <div className="relative w-full lg:w-96">
          <Search className="w-4 h-4 absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="البحث في العنوان أو الهدف المطلوب..."
            className="w-full pr-10 pl-4 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-xs sm:text-sm focus:outline-none focus:border-emerald-500 transition"
          />
        </div>

        <div className="flex flex-wrap items-center gap-3 w-full lg:w-auto">
          {/* Status Pills */}
          <div className="flex items-center gap-1.5 overflow-x-auto pb-1 sm:pb-0">
            {[
              { id: 'all', label: 'الكل' },
              { id: 'completed', label: 'المكتملة' },
              { id: 'running', label: 'قيد التنفيذ' },
              { id: 'failed', label: 'الفاشلة' },
              { id: 'pending', label: 'قيد الانتظار' },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setStatusFilter(tab.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition whitespace-nowrap ${
                  statusFilter === tab.id
                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                    : 'text-slate-400 hover:text-white hover:bg-slate-800/60 border border-transparent'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Agent Selector Filter */}
          {agents.length > 0 && (
            <select
              value={agentFilter}
              onChange={(e) => setAgentFilter(e.target.value)}
              className="px-3 py-1.5 rounded-xl bg-slate-950 border border-slate-800 text-slate-300 text-xs focus:outline-none focus:border-emerald-500"
            >
              <option value="all">كل الموظفين</option>
              {agents.map((ag) => (
                <option key={ag.id} value={ag.id}>
                  {ag.name}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      {/* Tasks Table */}
      {filteredTasks.length === 0 ? (
        <EmptyState
          icon={ListTodo}
          title="لم يتم العثور على أي مهمة مطابقة"
          description={
            searchTerm || statusFilter !== 'all' || agentFilter !== 'all'
              ? 'جرّب تغيير فلاتر التصفية أو البحث'
              : 'قم بإسناد مهمة جديدة للموظف الرقمي للبدء'
          }
          action={
            !searchTerm && statusFilter === 'all' && agentFilter === 'all' ? (
              <button
                onClick={() => setIsCreateOpen(true)}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-500 text-slate-950 font-bold text-xs"
              >
                <Plus className="w-4 h-4" />
                <span>إسناد أول مهمة</span>
              </button>
            ) : undefined
          }
        />
      ) : (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-right text-xs sm:text-sm">
              <thead className="bg-slate-950/60 border-b border-slate-800 text-slate-400 font-semibold">
                <tr>
                  <th className="py-3.5 px-4">تفاصيل المهمة</th>
                  <th className="py-3.5 px-4">الموظف الرقمي</th>
                  <th className="py-3.5 px-4">الأولوية</th>
                  <th className="py-3.5 px-4">الحالة</th>
                  <th className="py-3.5 px-4 hidden md:table-cell">التاريخ</th>
                  <th className="py-3.5 px-4 text-center">الإجراءات</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {filteredTasks.map((task) => {
                  const isRunning = task.status === 'running' || task.status === 'in_progress';
                  const isFailed = task.status === 'failed';
                  const isPending = task.status === 'pending';
                  const isBusy = actionLoading && actionTaskId === task.id;

                  return (
                    <tr key={task.id} className="hover:bg-slate-800/30 transition">
                      {/* Title & Objective */}
                      <td className="py-3.5 px-4">
                        <div className="font-bold text-white truncate max-w-xs sm:max-w-md">
                          {task.title}
                        </div>
                        <div className="text-xs text-slate-400 truncate max-w-xs sm:max-w-md mt-0.5">
                          {task.objective}
                        </div>
                        {task.error && (
                          <div className="text-[11px] text-rose-400 flex items-center gap-1 mt-1 font-mono truncate max-w-xs sm:max-w-md">
                            <AlertTriangle className="w-3 h-3 flex-shrink-0" />
                            <span>{task.error}</span>
                          </div>
                        )}
                      </td>

                      {/* Agent */}
                      <td className="py-3.5 px-4">
                        <div className="flex items-center gap-1.5 text-slate-300">
                          <Bot className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                          <span className="truncate max-w-[120px]">
                            {getAgentName(task.agent_id)}
                          </span>
                        </div>
                      </td>

                      {/* Priority */}
                      <td className="py-3.5 px-4">
                        <Badge
                          variant={
                            task.priority === 'urgent'
                              ? 'danger'
                              : task.priority === 'high'
                              ? 'warning'
                              : 'neutral'
                          }
                        >
                          {task.priority === 'urgent'
                            ? 'طارئة'
                            : task.priority === 'high'
                            ? 'عالية'
                            : 'عادية'}
                        </Badge>
                      </td>

                      {/* Status */}
                      <td className="py-3.5 px-4">{getStatusBadge(task.status)}</td>

                      {/* Date */}
                      <td className="py-3.5 px-4 hidden md:table-cell text-slate-400 font-mono text-xs">
                        {task.created_at
                          ? new Date(task.created_at).toLocaleString('ar-SA', {
                              dateStyle: 'short',
                              timeStyle: 'short',
                            })
                          : '—'}
                      </td>

                      {/* Actions */}
                      <td className="py-3.5 px-4">
                        <div className="flex items-center justify-center gap-1.5">
                          {/* Details Button */}
                          <button
                            onClick={() => setSelectedTask(task)}
                            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
                            title="عرض التفاصيل"
                          >
                            <Eye className="w-4 h-4" />
                          </button>

                          {/* Retry button if failed */}
                          {isFailed && (
                            <button
                              onClick={() => handleRetry(task)}
                              disabled={isBusy}
                              className="p-1.5 rounded-lg text-amber-400 hover:text-amber-300 hover:bg-amber-950/40 border border-amber-900/40 transition disabled:opacity-50"
                              title="إعادة المحاولة"
                            >
                              <RotateCcw className={`w-4 h-4 ${isBusy ? 'animate-spin' : ''}`} />
                            </button>
                          )}

                          {/* Cancel button if running or pending */}
                          {(isRunning || isPending) && (
                            <button
                              onClick={() => handleCancel(task)}
                              disabled={isBusy}
                              className="p-1.5 rounded-lg text-rose-400 hover:text-rose-300 hover:bg-rose-950/40 border border-rose-900/40 transition disabled:opacity-50"
                              title="إلغاء المهمة"
                            >
                              <XCircle className={`w-4 h-4 ${isBusy ? 'animate-spin' : ''}`} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Task Details Modal */}
      <Modal
        isOpen={!!selectedTask}
        onClose={() => setSelectedTask(null)}
        title="تفاصيل المهمة"
        description={selectedTask ? `المعرف: ${selectedTask.id}` : ''}
      >
        {selectedTask && (
          <div className="space-y-4">
            <div>
              <span className="text-xs font-semibold text-slate-400 block mb-1">
                عنوان المهمة:
              </span>
              <p className="text-sm font-bold text-white bg-slate-950 p-3 rounded-xl border border-slate-800">
                {selectedTask.title}
              </p>
            </div>

            <div>
              <span className="text-xs font-semibold text-slate-400 block mb-1">
                الهدف والتعليمات:
              </span>
              <p className="text-xs sm:text-sm text-slate-200 bg-slate-950 p-3 rounded-xl border border-slate-800 whitespace-pre-wrap leading-relaxed">
                {selectedTask.objective}
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="p-3 rounded-xl bg-slate-950 border border-slate-800">
                <span className="text-slate-400 block mb-1">الحالة:</span>
                <div>{getStatusBadge(selectedTask.status)}</div>
              </div>
              <div className="p-3 rounded-xl bg-slate-950 border border-slate-800">
                <span className="text-slate-400 block mb-1">الموظف الرقمي:</span>
                <span className="font-semibold text-white">
                  {getAgentName(selectedTask.agent_id)}
                </span>
              </div>
            </div>

            {/* Error Message if any */}
            {selectedTask.error && (
              <div className="p-3.5 rounded-xl bg-rose-950/50 border border-rose-800 text-rose-300 text-xs space-y-1">
                <span className="font-bold flex items-center gap-1">
                  <AlertCircle className="w-4 h-4" />
                  تفاصيل الخطأ:
                </span>
                <p className="font-mono">{selectedTask.error}</p>
              </div>
            )}

            {/* Result if completed */}
            {selectedTask.result && (
              <div>
                <span className="text-xs font-semibold text-slate-400 block mb-1">
                  النتيجة والمخرجات:
                </span>
                <pre className="text-xs text-emerald-300 bg-slate-950 p-3 rounded-xl border border-slate-800 font-mono overflow-x-auto max-h-48">
                  {JSON.stringify(selectedTask.result, null, 2)}
                </pre>
              </div>
            )}

            <div className="flex items-center justify-between pt-3 border-t border-slate-800">
              <div className="flex items-center gap-2">
                {selectedTask.status === 'failed' && (
                  <button
                    onClick={() => handleRetry(selectedTask)}
                    disabled={actionLoading}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-amber-500/20 text-amber-400 border border-amber-500/30 hover:bg-amber-500/30 text-xs font-semibold transition"
                  >
                    <RotateCcw className="w-3.5 h-3.5" />
                    <span>إعادة المحاولة الآن</span>
                  </button>
                )}
                {(selectedTask.status === 'running' || selectedTask.status === 'in_progress' || selectedTask.status === 'pending') && (
                  <button
                    onClick={() => handleCancel(selectedTask)}
                    disabled={actionLoading}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-rose-500/20 text-rose-400 border border-rose-500/30 hover:bg-rose-500/30 text-xs font-semibold transition"
                  >
                    <XCircle className="w-3.5 h-3.5" />
                    <span>إلغاء المهمة</span>
                  </button>
                )}
              </div>

              <button
                type="button"
                onClick={() => setSelectedTask(null)}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-white text-xs font-semibold transition"
              >
                إغلاق
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* Create Task Modal */}
      <Modal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        title="إسناد مهمة جديدة"
        description="حدد عنوان المهمة والهدف المطلوب وسيقوم النظام بتوجيهها للموظف الرقمي المناسب."
      >
        <form onSubmit={handleCreate} className="space-y-4">
          {createError && (
            <div className="p-3 rounded-lg bg-rose-950/50 border border-rose-800 text-rose-300 text-xs flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              <span>{createError}</span>
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              عنوان المهمة <span className="text-rose-400">*</span>
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="مثال: تحليل وتلخيص عقود التوريد الجديدة"
              required
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              الهدف والتعليمات بالتفصيل <span className="text-rose-400">*</span>
            </label>
            <textarea
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              placeholder="صف بدقة المطلوب إنجازه، المعايير المتبعة، وأي قيود أو متطلبات خاصة..."
              rows={4}
              required
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition resize-none"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                تعيين إلى موظف رقمي
              </label>
              <select
                value={selectedAgent}
                onChange={(e) => setSelectedAgent(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500 transition"
              >
                <option value="">توجيه تلقائي (الأنسب)</option>
                {agents.map((ag) => (
                  <option key={ag.id} value={ag.id}>
                    {ag.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                درجة الأولوية
              </label>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500 transition"
              >
                <option value="low">منخفضة (Low)</option>
                <option value="medium">متوسطة (Medium)</option>
                <option value="high">عالية (High)</option>
                <option value="urgent">طارئة وفورية (Urgent)</option>
              </select>
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
            <button
              type="button"
              onClick={() => setIsCreateOpen(false)}
              className="px-4 py-2 rounded-xl text-slate-400 hover:text-white text-xs sm:text-sm font-medium transition"
            >
              إلغاء
            </button>
            <button
              type="submit"
              disabled={createLoading}
              className="px-5 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs sm:text-sm transition disabled:opacity-50"
            >
              {createLoading ? 'جاري الإسناد...' : 'إسناد المهمة'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
