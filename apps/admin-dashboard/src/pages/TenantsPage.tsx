import React, { useEffect, useState } from 'react';
import { adminApi } from '../api/admin';
import { TenantItem } from '../api/types';
import { Badge } from '../components/common/Badge';
import { Modal } from '../components/common/Modal';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import {
  Building2,
  Search,
  Filter,
  Plus,
  Edit2,
  Sliders,
  RefreshCw,
  AlertTriangle,
  Bot,
  ListTodo,
} from 'lucide-react';

export const TenantsPage: React.FC = () => {
  const [tenants, setTenants] = useState<TenantItem[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('');

  // Modals
  const [statusModalTenant, setStatusModalTenant] = useState<TenantItem | null>(null);
  const [newStatus, setNewStatus] = useState<string>('active');

  const [budgetModalTenant, setBudgetModalTenant] = useState<TenantItem | null>(null);
  const [dailyLimit, setDailyLimit] = useState<number | ''>('');
  const [monthlyLimit, setMonthlyLimit] = useState<number | ''>('');
  const [isHardLimit, setIsHardLimit] = useState<boolean>(true);

  const [isProvisionOpen, setIsProvisionOpen] = useState<boolean>(false);
  const [provisionData, setProvisionData] = useState({
    tenant_name: '',
    slug: '',
    owner_name: '',
    owner_email: '',
    owner_password: '',
    agent_name: '',
  });

  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const fetchTenants = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await adminApi.listTenants(50, 0, statusFilter || undefined);
      setTenants(res.tenants || []);
      setTotal(res.total || 0);
    } catch (err: any) {
      setError(err?.message || 'تعذر جلب قائمة المستأجرين');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchTenants();
  }, [statusFilter]);

  // Handle Status Update
  const handleUpdateStatus = async () => {
    if (!statusModalTenant) return;
    setIsSubmitting(true);
    setActionError(null);
    try {
      await adminApi.updateTenantStatus(statusModalTenant.id, newStatus);
      setStatusModalTenant(null);
      await fetchTenants();
    } catch (err: any) {
      setActionError(err?.message || 'فشل تحديث حالة المستأجر');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Handle Budget Update
  const handleUpdateBudget = async () => {
    if (!budgetModalTenant) return;
    setIsSubmitting(true);
    setActionError(null);
    try {
      await adminApi.updateTenantBudget(budgetModalTenant.id, {
        daily_token_limit: dailyLimit === '' ? null : Number(dailyLimit),
        monthly_token_limit: monthlyLimit === '' ? null : Number(monthlyLimit),
        is_hard_limit: isHardLimit,
      });
      setBudgetModalTenant(null);
      await fetchTenants();
    } catch (err: any) {
      setActionError(err?.message || 'فشل تحديث حصة المستأجر');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Handle Provisioning
  const handleProvision = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setActionError(null);
    try {
      await adminApi.provisionTenant(provisionData);
      setIsProvisionOpen(false);
      setProvisionData({
        tenant_name: '',
        slug: '',
        owner_name: '',
        owner_email: '',
        owner_password: '',
        agent_name: '',
      });
      await fetchTenants();
    } catch (err: any) {
      setActionError(err?.message || 'فشل إنشاء المستأجر الجديد');
    } finally {
      setIsSubmitting(false);
    }
  };

  const filteredTenants = tenants.filter((t) => {
    const matchesSearch =
      searchTerm === '' ||
      t.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      t.slug.toLowerCase().includes(searchTerm.toLowerCase()) ||
      t.id.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesSearch;
  });

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-2xl font-black text-white tracking-tight flex items-center gap-2">
            <Building2 className="w-6 h-6 text-emerald-400" />
            إدارة المستأجرين والشركات
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            إدارة حسابات الشركات المسجلة، مراقبة حصص الاستهلاك، والتحكم بالحالات التشغيلية
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setIsProvisionOpen(true)}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 px-4 py-2 text-xs font-bold text-white hover:from-emerald-500 hover:to-teal-500 shadow-lg shadow-emerald-950/50 transition"
          >
            <Plus className="w-4 h-4" />
            <span>تسجيل مستأجر جديد</span>
          </button>
          <button
            onClick={fetchTenants}
            className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-3.5 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 border border-slate-800 transition"
            title="تحديث"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4 backdrop-blur">
        <div className="relative w-full sm:w-80">
          <div className="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none text-slate-400">
            <Search className="w-4 h-4" />
          </div>
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="بحث بالاسم أو المعرف..."
            className="w-full rounded-lg border border-slate-800 bg-slate-950 pr-9 pl-4 py-2 text-xs text-white placeholder-slate-500 focus:border-emerald-500 focus:outline-none"
          />
        </div>

        <div className="flex items-center gap-3 w-full sm:w-auto">
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Filter className="w-4 h-4" />
            <span>تصفية الحالة:</span>
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-white focus:border-emerald-500 focus:outline-none"
          >
            <option value="">كافة الحالات ({total})</option>
            <option value="active">نشط (Active)</option>
            <option value="suspended">معلق (Suspended)</option>
            <option value="pending">قيد الانتظار (Pending)</option>
          </select>
        </div>
      </div>

      {/* Main Content Area */}
      {isLoading ? (
        <LoadingState message="جاري استرجاع بيانات المستأجرين..." />
      ) : error ? (
        <ErrorState message={error} onRetry={fetchTenants} />
      ) : filteredTenants.length === 0 ? (
        <EmptyState
          title="لم يتم العثور على أي مستأجر"
          description="جرّب تعديل كلمات البحث أو تصفية الحالات."
          icon={Building2}
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/40">
          <table className="w-full text-right border-collapse text-xs">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/80 text-slate-400">
                <th className="py-3.5 px-4 font-semibold">المستأجر</th>
                <th className="py-3.5 px-4 font-semibold">الحالة</th>
                <th className="py-3.5 px-4 font-semibold">الوكلاء والمهام</th>
                <th className="py-3.5 px-4 font-semibold">حصة الرموز (AI Budget)</th>
                <th className="py-3.5 px-4 font-semibold">مستوى التنبيه</th>
                <th className="py-3.5 px-4 font-semibold text-left">الإجراءات</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {filteredTenants.map((tenant) => (
                <tr
                  key={tenant.id}
                  className="hover:bg-slate-800/30 transition duration-150"
                >
                  {/* Name and Slug */}
                  <td className="py-3.5 px-4">
                    <div className="font-bold text-white text-sm">{tenant.name}</div>
                    <div className="text-[11px] text-slate-400 font-mono flex items-center gap-2">
                      <span>{tenant.slug}</span>
                      <span className="text-slate-600">|</span>
                      <span className="truncate max-w-[120px]" title={tenant.id}>
                        {tenant.id}
                      </span>
                    </div>
                  </td>

                  {/* Status */}
                  <td className="py-3.5 px-4">
                    <Badge status={tenant.status} />
                  </td>

                  {/* Agents and Tasks */}
                  <td className="py-3.5 px-4">
                    <div className="flex items-center gap-3">
                      <span className="flex items-center gap-1 text-slate-300">
                        <Bot className="w-3.5 h-3.5 text-blue-400" />
                        {tenant.agent_count}
                      </span>
                      <span className="flex items-center gap-1 text-slate-300">
                        <ListTodo className="w-3.5 h-3.5 text-emerald-400" />
                        {tenant.task_count}
                      </span>
                      {tenant.failed_task_count > 0 && (
                        <span className="text-[10px] text-rose-400 font-medium bg-rose-950/60 px-1.5 py-0.5 rounded border border-rose-900">
                          {tenant.failed_task_count} فشل
                        </span>
                      )}
                    </div>
                  </td>

                  {/* Budget */}
                  <td className="py-3.5 px-4">
                    {tenant.budget?.configured ? (
                      <div className="space-y-0.5">
                        <div className="text-slate-200">
                          اليومي: {(tenant.budget.current_day_tokens ?? 0).toLocaleString()} /{' '}
                          {tenant.budget.daily_limit ? tenant.budget.daily_limit.toLocaleString() : 'بلا حد'}
                        </div>
                        <div className="text-[11px] text-slate-400">
                          الشهري: {(tenant.budget.current_month_tokens ?? 0).toLocaleString()} /{' '}
                          {tenant.budget.monthly_limit ? tenant.budget.monthly_limit.toLocaleString() : 'بلا حد'}
                        </div>
                      </div>
                    ) : (
                      <span className="text-slate-400 italic">غير محدد</span>
                    )}
                  </td>

                  {/* Alert Level */}
                  <td className="py-3.5 px-4">
                    {tenant.budget?.alert_level === 'exceeded' ? (
                      <Badge status="exceeded" label="تجاوز الحصة" />
                    ) : tenant.budget?.alert_level === 'critical' ? (
                      <Badge status="critical" label="حرج (>90%)" />
                    ) : tenant.budget?.alert_level === 'warning' ? (
                      <Badge status="warning" label="تحذير (>75%)" />
                    ) : (
                      <span className="text-slate-400">طبيعي</span>
                    )}
                  </td>

                  {/* Actions */}
                  <td className="py-3.5 px-4 text-left">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => {
                          setActionError(null);
                          setStatusModalTenant(tenant);
                          setNewStatus(tenant.status);
                        }}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 px-2.5 py-1.5 text-xs text-slate-200 hover:bg-slate-700 transition"
                        title="تعديل الحالة"
                      >
                        <Edit2 className="w-3.5 h-3.5" />
                        <span>الحالة</span>
                      </button>

                      <button
                        onClick={() => {
                          setActionError(null);
                          setBudgetModalTenant(tenant);
                          setDailyLimit(tenant.budget.daily_limit || '');
                          setMonthlyLimit(tenant.budget.monthly_limit || '');
                        }}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 px-2.5 py-1.5 text-xs text-slate-200 hover:bg-slate-700 transition"
                        title="تعديل حصة الرموز"
                      >
                        <Sliders className="w-3.5 h-3.5 text-purple-400" />
                        <span>الحصة</span>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Update Status Modal */}
      <Modal
        isOpen={!!statusModalTenant}
        onClose={() => setStatusModalTenant(null)}
        title={`تعديل حالة المستأجر: ${statusModalTenant?.name}`}
        footer={
          <>
            <button
              onClick={() => setStatusModalTenant(null)}
              className="rounded-lg bg-slate-800 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-700 transition"
            >
              إلغاء
            </button>
            <button
              onClick={handleUpdateStatus}
              disabled={isSubmitting}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-xs font-bold text-white hover:bg-emerald-500 transition disabled:opacity-50"
            >
              {isSubmitting ? 'جاري الحفظ...' : 'حفظ التغييرات'}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          {actionError && (
            <div className="flex items-center gap-2 rounded-lg bg-rose-950/60 p-3 text-xs text-rose-300 border border-rose-900">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              <span>{actionError}</span>
            </div>
          )}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-2">
              الحالة التشغيلية الجديدة
            </label>
            <select
              value={newStatus}
              onChange={(e) => setNewStatus(e.target.value)}
              className="w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white focus:border-emerald-500 focus:outline-none"
            >
              <option value="active">نشط (Active) — مسموح بكافة العمليات</option>
              <option value="suspended">معلق (Suspended) — حظر تنفيذ المهام</option>
              <option value="pending">قيد المراجعة (Pending)</option>
            </select>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            ملاحظة: تعديل الحالة سيتم تسجيله في سجل التدقيق الإداري الصارم
            (Audit Log) وفق ضوابط الامتثال المعتمدة.
          </p>
        </div>
      </Modal>

      {/* Update Budget Modal */}
      <Modal
        isOpen={!!budgetModalTenant}
        onClose={() => setBudgetModalTenant(null)}
        title={`تعديل حصة الرموز (AI Budget): ${budgetModalTenant?.name}`}
        footer={
          <>
            <button
              onClick={() => setBudgetModalTenant(null)}
              className="rounded-lg bg-slate-800 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-700 transition"
            >
              إلغاء
            </button>
            <button
              onClick={handleUpdateBudget}
              disabled={isSubmitting}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-xs font-bold text-white hover:bg-emerald-500 transition disabled:opacity-50"
            >
              {isSubmitting ? 'جاري الحفظ...' : 'تطبيق الحصة'}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          {actionError && (
            <div className="flex items-center gap-2 rounded-lg bg-rose-950/60 p-3 text-xs text-rose-300 border border-rose-900">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              <span>{actionError}</span>
            </div>
          )}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              الحد اليومي للرموز (Daily Tokens)
            </label>
            <input
              type="number"
              min="0"
              value={dailyLimit}
              onChange={(e) => setDailyLimit(e.target.value === '' ? '' : Number(e.target.value))}
              placeholder="مثال: 500000 (اتركه فارغاً لبلا حد)"
              className="w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white focus:border-emerald-500 focus:outline-none"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              الحد الشهري للرموز (Monthly Tokens)
            </label>
            <input
              type="number"
              min="0"
              value={monthlyLimit}
              onChange={(e) => setMonthlyLimit(e.target.value === '' ? '' : Number(e.target.value))}
              placeholder="مثال: 15000000 (اتركه فارغاً لبلا حد)"
              className="w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white focus:border-emerald-500 focus:outline-none"
            />
          </div>

          <div className="flex items-center gap-2 pt-2">
            <input
              type="checkbox"
              id="hardLimitCheck"
              checked={isHardLimit}
              onChange={(e) => setIsHardLimit(e.target.checked)}
              className="rounded border-slate-700 bg-slate-950 text-emerald-500 focus:ring-0"
            />
            <label htmlFor="hardLimitCheck" className="text-xs text-slate-300 cursor-pointer">
              فرض حد صارم (Hard Limit) — رفض الطلبات فور تجاوز الحصة
            </label>
          </div>
        </div>
      </Modal>

      {/* Provision New Tenant Modal */}
      <Modal
        isOpen={isProvisionOpen}
        onClose={() => setIsProvisionOpen(false)}
        title="تسجيل وتأسيس مستأجر جديد (Atomic Provisioning)"
        footer={
          <>
            <button
              onClick={() => setIsProvisionOpen(false)}
              className="rounded-lg bg-slate-800 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-700 transition"
            >
              إلغاء
            </button>
            <button
              onClick={handleProvision}
              disabled={isSubmitting || !provisionData.tenant_name || !provisionData.owner_email || !provisionData.owner_name}
              className="rounded-lg bg-gradient-to-r from-emerald-600 to-teal-600 px-4 py-2 text-xs font-bold text-white hover:from-emerald-500 hover:to-teal-500 transition disabled:opacity-50"
            >
              {isSubmitting ? 'جاري التأسيس...' : 'إنشاء وتفعيل المستأجر'}
            </button>
          </>
        }
      >
        <form onSubmit={handleProvision} className="space-y-4">
          {actionError && (
            <div className="flex items-center gap-2 rounded-lg bg-rose-950/60 p-3 text-xs text-rose-300 border border-rose-900">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              <span>{actionError}</span>
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                اسم الشركة / المستأجر *
              </label>
              <input
                type="text"
                required
                value={provisionData.tenant_name}
                onChange={(e) => setProvisionData({ ...provisionData, tenant_name: e.target.value })}
                placeholder="شركة الأفق الذكي"
                className="w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white focus:border-emerald-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                المعرف الفريد (Slug)
              </label>
              <input
                type="text"
                value={provisionData.slug}
                onChange={(e) => setProvisionData({ ...provisionData, slug: e.target.value })}
                placeholder="alofoq (اختياري)"
                className="w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white focus:border-emerald-500 focus:outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                اسم المالك المسؤول *
              </label>
              <input
                type="text"
                required
                value={provisionData.owner_name}
                onChange={(e) => setProvisionData({ ...provisionData, owner_name: e.target.value })}
                placeholder="خالد العمري"
                className="w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white focus:border-emerald-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                بريد المالك الإلكتروني *
              </label>
              <input
                type="email"
                required
                value={provisionData.owner_email}
                onChange={(e) => setProvisionData({ ...provisionData, owner_email: e.target.value })}
                placeholder="owner@alofoq.sa"
                className="w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white focus:border-emerald-500 focus:outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                كلمة مرور المالك الأولية
              </label>
              <input
                type="password"
                value={provisionData.owner_password}
                onChange={(e) => setProvisionData({ ...provisionData, owner_password: e.target.value })}
                placeholder="•••••••• (اتركه لإنشاء كلمة قوية تلقائياً)"
                className="w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white focus:border-emerald-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                اسم الموظف الرقمي الأولي
              </label>
              <input
                type="text"
                value={provisionData.agent_name}
                onChange={(e) => setProvisionData({ ...provisionData, agent_name: e.target.value })}
                placeholder="سارة - المساعد الذكي"
                className="w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white focus:border-emerald-500 focus:outline-none"
              />
            </div>
          </div>

          <div className="rounded-xl bg-slate-950/50 p-3 border border-slate-800 text-[11px] text-slate-400">
            سيتم إنشاء المستأجر، المالك، BusinessBrain، والموظف الرقمي الأولي في معاملة ذرية واحدة (Single Atomic DB Transaction).
          </div>
        </form>
      </Modal>
    </div>
  );
};
