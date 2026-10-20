import React, { useEffect, useState } from 'react';
import {
  Bot,
  Plus,
  RefreshCw,
  Search,
  CheckCircle2,
  Power,
  Edit2,
  ShieldAlert,
  Sparkles,
} from 'lucide-react';
import { agentsApi } from '../api/agents';
import { Agent } from '../api/types';
import { Badge } from '../components/common/Badge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import { Modal } from '../components/common/Modal';

export const AgentsPage: React.FC = () => {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'inactive'>('all');

  // Create Modal
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [createName, setCreateName] = useState('');
  const [createType, setCreateType] = useState('react');
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Edit / Toggle Status Modal
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);
  const [editName, setEditName] = useState('');
  const [editStatus, setEditStatus] = useState('active');
  const [editLoading, setEditLoading] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  const loadAgents = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await agentsApi.listAgents();
      setAgents(data);
    } catch (err: any) {
      setError(err?.message || 'تعذر استرجاع قائمة الموظفين الرقميين');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAgents();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createName.trim()) {
      setCreateError('يرجى تحديد اسم الموظف الرقمي');
      return;
    }
    setCreateLoading(true);
    setCreateError(null);
    try {
      await agentsApi.createAgent({
        name: createName.trim(),
        agent_type: createType,
      });
      setIsCreateOpen(false);
      setCreateName('');
      loadAgents();
    } catch (err: any) {
      setCreateError(err?.message || 'فشل إنشاء الموظف الرقمي');
    } finally {
      setCreateLoading(false);
    }
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingAgent) return;
    setEditLoading(true);
    setEditError(null);
    try {
      await agentsApi.updateAgent(editingAgent.id, {
        name: editName.trim() || undefined,
        status: editStatus,
      });
      setEditingAgent(null);
      loadAgents();
    } catch (err: any) {
      setEditError(err?.message || 'فشل تحديث بيانات الموظف الرقمي');
    } finally {
      setEditLoading(false);
    }
  };

  const handleToggleStatus = async (agent: Agent) => {
    const newStatus = agent.status === 'active' ? 'inactive' : 'active';
    try {
      await agentsApi.updateAgent(agent.id, { status: newStatus });
      setAgents((prev) =>
        prev.map((a) => (a.id === agent.id ? { ...a, status: newStatus } : a))
      );
    } catch (err: any) {
      alert(`فشل تغيير حالة الموظف: ${err?.message || 'خطأ غير متوقع'}`);
    }
  };

  const filteredAgents = agents.filter((agent) => {
    const matchesSearch =
      agent.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      agent.agent_type.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesStatus =
      statusFilter === 'all' ? true : agent.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  if (loading) {
    return <LoadingState message="جاري استرجاع فريق الموظفين الرقميين..." />;
  }

  if (error) {
    return (
      <ErrorState
        title="تعذر تحميل الموظفين الرقميين"
        message={error}
        onRetry={loadAgents}
      />
    );
  }

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl sm:text-2xl font-extrabold text-white tracking-tight flex items-center gap-2">
            <Bot className="w-6 h-6 text-emerald-400" />
            <span>الموظفون الرقميون والوكلاء</span>
          </h2>
          <p className="text-xs sm:text-sm text-slate-400 mt-1">
            إدارة وكلاء الذكاء الاصطناعي وتعيين تخصصاتهم ومراقبة جاهزيتهم لتنفيذ الأعمال
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
            <span>إضافة موظف رقمي</span>
          </button>
          <button
            onClick={loadAgents}
            className="p-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 hover:text-white border border-slate-800 transition"
            title="تحديث القائمة"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 flex flex-col md:flex-row gap-4 justify-between items-center">
        <div className="relative w-full md:w-80">
          <Search className="w-4 h-4 absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="البحث بالاسم أو التخصص..."
            className="w-full pr-10 pl-4 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-xs sm:text-sm focus:outline-none focus:border-emerald-500 transition"
          />
        </div>

        <div className="flex items-center gap-2 w-full md:w-auto">
          <span className="text-xs text-slate-400">الحالة:</span>
          {(['all', 'active', 'inactive'] as const).map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
                statusFilter === s
                  ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800/60 border border-transparent'
              }`}
            >
              {s === 'all' ? 'الكل' : s === 'active' ? 'النشطة' : 'المتوقفة'}
            </button>
          ))}
        </div>
      </div>

      {/* Agents Grid */}
      {filteredAgents.length === 0 ? (
        <EmptyState
          icon={Bot}
          title="لم يتم العثور على أي موظف رقمي"
          description={
            searchTerm || statusFilter !== 'all'
              ? 'جرّب تعديل معايير البحث أو التصفية الحالية'
              : 'قم بإضافة أول وكيل ذكي لشركتك للبدء في أتمتة الأعمال'
          }
          action={
            !searchTerm && statusFilter === 'all' ? (
              <button
                onClick={() => setIsCreateOpen(true)}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-500 text-slate-950 font-bold text-xs"
              >
                <Plus className="w-4 h-4" />
                <span>إضافة موظف رقمي الآن</span>
              </button>
            ) : undefined
          }
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredAgents.map((agent) => {
            const isActive = agent.status === 'active';
            return (
              <div
                key={agent.id}
                className="bg-slate-900 border border-slate-800 rounded-2xl p-5 hover:border-slate-700 transition flex flex-col justify-between group shadow-sm hover:shadow-md"
              >
                <div className="space-y-4">
                  {/* Top line: Icon, Type, Status */}
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-emerald-600/20 to-teal-400/20 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shadow-inner">
                        <Bot className="w-6 h-6" />
                      </div>
                      <div>
                        <h3 className="text-base font-bold text-white group-hover:text-emerald-400 transition">
                          {agent.name}
                        </h3>
                        <span className="text-xs text-slate-400 font-mono">
                          ID: {agent.id.slice(0, 8)}...
                        </span>
                      </div>
                    </div>
                    <Badge variant={isActive ? 'success' : 'neutral'}>
                      {isActive ? 'نشط ويعمل' : 'متوقف'}
                    </Badge>
                  </div>

                  {/* Agent Capabilities / Spec */}
                  <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 space-y-2 text-xs">
                    <div className="flex items-center justify-between text-slate-400">
                      <span>محرك التفكير:</span>
                      <span className="text-emerald-400 font-semibold font-mono flex items-center gap-1">
                        <Sparkles className="w-3 h-3" />
                        {agent.agent_type.toUpperCase()}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-slate-400">
                      <span>صلاحية العزل:</span>
                      <span className="text-slate-300 font-medium flex items-center gap-1">
                        <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                        نطاق المستأجر فقط
                      </span>
                    </div>
                  </div>
                </div>

                {/* Bottom Actions */}
                <div className="pt-4 mt-4 border-t border-slate-800 flex items-center justify-between gap-2">
                  <button
                    onClick={() => {
                      setEditingAgent(agent);
                      setEditName(agent.name);
                      setEditStatus(agent.status);
                      setEditError(null);
                    }}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-300 hover:text-white hover:bg-slate-800 transition"
                  >
                    <Edit2 className="w-3.5 h-3.5" />
                    <span>تعديل</span>
                  </button>

                  <button
                    onClick={() => handleToggleStatus(agent)}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
                      isActive
                        ? 'text-amber-400 hover:bg-amber-950/40 border border-amber-900/40'
                        : 'text-emerald-400 hover:bg-emerald-950/40 border border-emerald-900/40'
                    }`}
                  >
                    <Power className="w-3.5 h-3.5" />
                    <span>{isActive ? 'إيقاف مؤقت' : 'تفعيل وتشغيل'}</span>
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Create Agent Modal */}
      <Modal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        title="إضافة موظف رقمي جديد"
        description="عيّن موظف ذكاء اصطناعي جديد وادرجه ضمن فريق العمل الرقمي لشركتك."
      >
        <form onSubmit={handleCreate} className="space-y-4">
          {createError && (
            <div className="p-3 rounded-lg bg-rose-950/50 border border-rose-800 text-rose-300 text-xs flex items-center gap-2">
              <ShieldAlert className="w-4 h-4 flex-shrink-0" />
              <span>{createError}</span>
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              اسم الموظف الرقمي <span className="text-rose-400">*</span>
            </label>
            <input
              type="text"
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              placeholder="مثال: منسق الدعم الفني، مدقق العقود"
              required
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              طبيعة المحرك والتخصص
            </label>
            <select
              value={createType}
              onChange={(e) => setCreateType(e.target.value)}
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500 transition"
            >
              <option value="react">وكيل تفكير وتخطيط وتنفيذ (ReAct Agent)</option>
              <option value="assistant">مساعد عام لإدارة الأعمال (Business Assistant)</option>
              <option value="analyst">محلل بيانات وأداء (Data Analyst)</option>
            </select>
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
              {createLoading ? 'جاري الإنشاء...' : 'إضافة الموظف'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Edit Agent Modal */}
      <Modal
        isOpen={!!editingAgent}
        onClose={() => setEditingAgent(null)}
        title="تعديل بيانات الموظف الرقمي"
        description="تحديث اسم الموظف وحالته التشغيلية."
      >
        <form onSubmit={handleUpdate} className="space-y-4">
          {editError && (
            <div className="p-3 rounded-lg bg-rose-950/50 border border-rose-800 text-rose-300 text-xs flex items-center gap-2">
              <ShieldAlert className="w-4 h-4 flex-shrink-0" />
              <span>{editError}</span>
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              اسم الموظف الرقمي
            </label>
            <input
              type="text"
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              required
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500 transition"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              الحالة التشغيلية
            </label>
            <select
              value={editStatus}
              onChange={(e) => setEditStatus(e.target.value)}
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500 transition"
            >
              <option value="active">نشط (جاهز لتنفيذ المهام)</option>
              <option value="inactive">متوقف مؤقتاً</option>
            </select>
          </div>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
            <button
              type="button"
              onClick={() => setEditingAgent(null)}
              className="px-4 py-2 rounded-xl text-slate-400 hover:text-white text-xs sm:text-sm font-medium transition"
            >
              إلغاء
            </button>
            <button
              type="submit"
              disabled={editLoading}
              className="px-5 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs sm:text-sm transition disabled:opacity-50"
            >
              {editLoading ? 'جاري الحفظ...' : 'حفظ التعديلات'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
