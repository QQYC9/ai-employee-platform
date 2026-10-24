import React, { useEffect, useState } from 'react';
import { adminApi } from '../api/admin';
import {
  PlatformIntegrationItem,
  PlatformIntegrationCreatePayload,
  PlatformIntegrationUpdatePayload,
} from '../api/types';
import { Badge } from '../components/common/Badge';
import { Modal } from '../components/common/Modal';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import {
  KeyRound,
  ShieldCheck,
  Zap,
  Plus,
  RefreshCw,
  Edit2,
  Trash2,
  CheckCircle2,
  XCircle,
  Clock,
  Layers,
  Sparkles,
  Server,
  Lock,
} from 'lucide-react';

export const PlatformIntegrationsPage: React.FC = () => {
  const [integrations, setIntegrations] = useState<PlatformIntegrationItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Testing connectivity state per integration
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ id: string; success: boolean; latency?: number; msg?: string } | null>(null);

  // Modals
  const [isCreateOpen, setIsCreateOpen] = useState<boolean>(false);
  const [editingIntegration, setEditingIntegration] = useState<PlatformIntegrationItem | null>(null);

  // Form State
  const [formData, setFormData] = useState<PlatformIntegrationCreatePayload>({
    name: '',
    provider: 'groq',
    model: '',
    api_key: '',
    base_url: '',
    temperature: 0.2,
    max_tokens: 4096,
    is_default: false,
  });

  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [modalError, setModalError] = useState<string | null>(null);

  const fetchIntegrations = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await adminApi.listPlatformIntegrations();
      setIntegrations(data || []);
    } catch (err: any) {
      setError(err?.message || 'فشل في تحميل تكاملات ومزودي المنصة');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchIntegrations();
  }, []);

  const handleTestConnection = async (integration: PlatformIntegrationItem) => {
    setTestingId(integration.id);
    setTestResult(null);
    try {
      const res = await adminApi.testPlatformIntegration(integration.id);
      setTestResult({
        id: integration.id,
        success: res.success,
        latency: res.latency_ms,
        msg: res.success ? 'الاتصال ناجح ومصادق عليه بنجاح' : (res.error_message || 'فشل الاتصال بالمزود'),
      });
      // Refresh list to update persisted status
      await fetchIntegrations();
    } catch (err: any) {
      setTestResult({
        id: integration.id,
        success: false,
        msg: err?.message || 'حدث خطأ أثناء اختبار الاتصال بالمزود',
      });
    } finally {
      setTestingId(null);
    }
  };

  const handleOpenCreate = () => {
    setFormData({
      name: '',
      provider: 'groq',
      model: 'openai/gpt-oss-120b',
      api_key: '',
      base_url: '',
      temperature: 0.2,
      max_tokens: 4096,
      is_default: integrations.length === 0,
    });
    setModalError(null);
    setIsCreateOpen(true);
  };

  const handleOpenEdit = (integ: PlatformIntegrationItem) => {
    setEditingIntegration(integ);
    setFormData({
      name: integ.name,
      provider: integ.provider,
      model: integ.model,
      api_key: '', // Keep empty unless updating
      base_url: integ.base_url || '',
      temperature: integ.temperature,
      max_tokens: integ.max_tokens || 4096,
      is_default: integ.is_default,
    });
    setModalError(null);
  };

  const handleSubmitCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name.trim() || !formData.model.trim()) {
      setModalError('الرجاء إدخال اسم التكوين واسم النموذج');
      return;
    }
    setIsSubmitting(true);
    setModalError(null);
    try {
      await adminApi.createPlatformIntegration({
        ...formData,
        name: formData.name.trim(),
        model: formData.model.trim(),
        api_key: formData.api_key?.trim() || undefined,
        base_url: formData.base_url?.trim() || undefined,
      });
      setIsCreateOpen(false);
      await fetchIntegrations();
    } catch (err: any) {
      setModalError(err?.message || 'فشل في حفظ التكوين الجديد');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSubmitEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingIntegration) return;
    if (!formData.name.trim() || !formData.model.trim()) {
      setModalError('الرجاء إدخال اسم التكوين واسم النموذج');
      return;
    }
    setIsSubmitting(true);
    setModalError(null);
    try {
      const payload: PlatformIntegrationUpdatePayload = {
        name: formData.name.trim(),
        model: formData.model.trim(),
        base_url: formData.base_url?.trim() || undefined,
        temperature: formData.temperature,
        max_tokens: formData.max_tokens,
        is_default: formData.is_default,
      };
      if (formData.api_key?.trim()) {
        payload.api_key = formData.api_key.trim();
      }
      await adminApi.updatePlatformIntegration(editingIntegration.id, payload);
      setEditingIntegration(null);
      await fetchIntegrations();
    } catch (err: any) {
      setModalError(err?.message || 'فشل في تحديث التكوين');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleToggleStatus = async (integ: PlatformIntegrationItem) => {
    const nextStatus = integ.status === 'active' ? 'disabled' : 'active';
    try {
      await adminApi.updatePlatformIntegration(integ.id, { status: nextStatus });
      await fetchIntegrations();
    } catch (err: any) {
      alert(`فشل تغيير حالة المزود: ${err?.message}`);
    }
  };

  const handleDelete = async (integ: PlatformIntegrationItem) => {
    if (!window.confirm(`هل أنت متأكد من حذف المزود المركزي "${integ.name}"؟`)) return;
    try {
      await adminApi.deletePlatformIntegration(integ.id);
      await fetchIntegrations();
    } catch (err: any) {
      alert(`فشل حذف المزود: ${err?.message}`);
    }
  };

  const defaultIntegration = integrations.find((i) => i.is_default && i.status === 'active');
  const activeCount = integrations.filter((i) => i.status === 'active').length;

  return (
    <div className="space-y-8 animate-in fade-in duration-200" dir="rtl">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-emerald-950 text-emerald-400 border border-emerald-800/80 flex items-center gap-1">
              <ShieldCheck className="w-3.5 h-3.5" /> خاص بمدير المنصة الأعلى فقط
            </span>
            <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-slate-900 text-slate-400 border border-slate-800 flex items-center gap-1">
              <Lock className="w-3 h-3 text-emerald-400" /> تشفير AES-256-GCM
            </span>
          </div>
          <h2 className="text-2xl font-black text-white tracking-tight flex items-center gap-2.5">
            <KeyRound className="w-6 h-6 text-emerald-400" />
            تكاملات ومزودو المنصة (Platform Integrations)
          </h2>
          <p className="text-sm text-slate-400 mt-1 max-w-2xl">
            إدارة مركزية لمفاتيح مزودي نماذج الذكاء الاصطناعي (AI Providers) ومزودي الخدمات العامين، مشفرة بالكامل ومعزولة تمامًا عن المستأجرين.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={fetchIntegrations}
            disabled={isLoading}
            className="p-2.5 rounded-xl border border-slate-800 bg-slate-900 text-slate-300 hover:text-white hover:bg-slate-800 transition flex items-center gap-2 text-sm"
            title="تحديث القائمة"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
            تحديث
          </button>
          <button
            onClick={handleOpenCreate}
            className="px-4 py-2.5 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-500 text-slate-950 font-bold hover:from-emerald-500 hover:to-teal-400 transition shadow-lg shadow-emerald-950/40 flex items-center gap-2 text-sm"
          >
            <Plus className="w-4 h-4" />
            إضافة مزود مركزي
          </button>
        </div>
      </div>

      {/* Metrics Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 backdrop-blur">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold">إجمالي المزودين</span>
            <Layers className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-black text-white">{integrations.length}</div>
          <div className="text-xs text-emerald-400 mt-1 flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3" /> {activeCount} مزود نشط حاليًا
          </div>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 backdrop-blur">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold">المزود الافتراضي للمنصة</span>
            <Sparkles className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-lg font-black text-white truncate">
            {defaultIntegration ? defaultIntegration.name : 'غير محدد'}
          </div>
          <div className="text-xs text-slate-400 mt-1 truncate">
            {defaultIntegration ? `${defaultIntegration.provider.toUpperCase()} (${defaultIntegration.model})` : 'يعتمد على متغيرات البيئة .env'}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 backdrop-blur">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold">مستوى الحماية والتشفير</span>
            <Lock className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-lg font-black text-emerald-400 flex items-center gap-1.5">
            <ShieldCheck className="w-5 h-5 text-emerald-400" /> مشفر بالكامل
          </div>
          <div className="text-xs text-slate-400 mt-1">
            مفاتيح مقنّعة ومحمية بـ AES-GCM
          </div>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 backdrop-blur">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold">نطاق الاستخدام</span>
            <Server className="w-4 h-4 text-blue-400" />
          </div>
          <div className="text-lg font-black text-white">Global Platform</div>
          <div className="text-xs text-slate-400 mt-1">
            متاح تلقائيًا لكافة وكلاء المستأجرين
          </div>
        </div>
      </div>

      {/* Test Result Toast/Banner */}
      {testResult && (
        <div
          className={`p-4 rounded-xl border flex items-center justify-between transition animate-in slide-in-from-top-2 duration-200 ${
            testResult.success
              ? 'bg-emerald-950/60 border-emerald-800 text-emerald-200'
              : 'bg-rose-950/60 border-rose-800 text-rose-200'
          }`}
        >
          <div className="flex items-center gap-3 text-sm">
            {testResult.success ? (
              <CheckCircle2 className="w-5 h-5 text-emerald-400 flex-shrink-0" />
            ) : (
              <XCircle className="w-5 h-5 text-rose-400 flex-shrink-0" />
            )}
            <div>
              <span className="font-bold">
                {testResult.success ? 'نجاح اختبار الاتصال:' : 'فشل اختبار الاتصال:'}
              </span>{' '}
              {testResult.msg}
              {testResult.latency !== undefined && (
                <span className="text-xs font-mono ml-2 opacity-80">
                  (زمن الاستجابة: {testResult.latency.toFixed(1)} ms)
                </span>
              )}
            </div>
          </div>
          <button
            onClick={() => setTestResult(null)}
            className="text-xs opacity-70 hover:opacity-100 px-2 py-1"
          >
            إغلاق
          </button>
        </div>
      )}

      {/* Content Section */}
      {isLoading ? (
        <LoadingState message="جاري استرجاع تكاملات ومزودي المنصة..." />
      ) : error ? (
        <ErrorState message={error} onRetry={fetchIntegrations} />
      ) : integrations.length === 0 ? (
        <EmptyState
          title="لا يوجد مزودو ذكاء اصطناعي مسجلون مركزيًا"
          description="يمكنك تسجيل مزود ذكاء اصطناعي مركزي (Groq, OpenAI, Gemini) ليعمل كخيار أساسي أو افتراضي لجميع وكلاء المنشآت."
          action={{
            label: 'إضافة أول مزود مركزي',
            onClick: handleOpenCreate,
          }}
        />
      ) : (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50 overflow-hidden backdrop-blur shadow-xl">
          <div className="overflow-x-auto">
            <table className="w-full text-right text-sm">
              <thead className="bg-slate-950/80 text-slate-400 border-b border-slate-800 text-xs uppercase font-semibold">
                <tr>
                  <th className="px-6 py-4">المزود والتكوين</th>
                  <th className="px-6 py-4">النموذج (Model)</th>
                  <th className="px-6 py-4">المفتاح المقنّع (API Key)</th>
                  <th className="px-6 py-4">الحالة</th>
                  <th className="px-6 py-4">آخر فحص اتصال</th>
                  <th className="px-6 py-4 text-center">الإجراءات</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {integrations.map((integ) => {
                  const isTesting = testingId === integ.id;
                  return (
                    <tr key={integ.id} className="hover:bg-slate-800/30 transition">
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-3">
                          <div className="w-10 h-10 rounded-xl bg-slate-800 flex items-center justify-center font-bold text-white border border-slate-700 uppercase flex-shrink-0">
                            {integ.provider.substring(0, 2)}
                          </div>
                          <div>
                            <div className="font-bold text-white flex items-center gap-2">
                              {integ.name}
                              {integ.is_default && (
                                <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-950 text-amber-300 border border-amber-800/80 flex items-center gap-0.5">
                                  <Sparkles className="w-2.5 h-2.5" /> افتراضي
                                </span>
                              )}
                            </div>
                            <span className="text-xs text-slate-400 uppercase tracking-wider">
                              مزود: {integ.provider}
                            </span>
                          </div>
                        </div>
                      </td>

                      <td className="px-6 py-4">
                        <span className="font-mono text-xs text-slate-200 bg-slate-950 px-2.5 py-1 rounded-lg border border-slate-800 inline-block">
                          {integ.model}
                        </span>
                        {integ.base_url && (
                          <div className="text-[10px] text-slate-500 font-mono mt-0.5 truncate max-w-xs">
                            {integ.base_url}
                          </div>
                        )}
                      </td>

                      <td className="px-6 py-4">
                        <div className="flex items-center gap-1.5 font-mono text-xs text-emerald-400">
                          <Lock className="w-3 h-3 text-emerald-500" />
                          <span>{integ.masked_api_key || 'مفتاح مشفر (AES-GCM)'}</span>
                        </div>
                      </td>

                      <td className="px-6 py-4">
                        <Badge
                          status={integ.status}
                          label={integ.status === 'active' ? 'نشط' : integ.status === 'disabled' ? 'معطل' : integ.status}
                        />
                      </td>

                      <td className="px-6 py-4">
                        {integ.last_test_status === 'success' ? (
                          <div className="flex items-center gap-1 text-emerald-400 text-xs">
                            <CheckCircle2 className="w-3.5 h-3.5" /> ناجح
                            {integ.last_test_result?.latency_ms && (
                              <span className="text-slate-400 text-[10px] font-mono">
                                ({integ.last_test_result.latency_ms.toFixed(0)}ms)
                              </span>
                            )}
                          </div>
                        ) : integ.last_test_status === 'failed' ? (
                          <div className="flex items-center gap-1 text-rose-400 text-xs">
                            <XCircle className="w-3.5 h-3.5" /> غير متصل
                          </div>
                        ) : (
                          <span className="text-slate-500 text-xs flex items-center gap-1">
                            <Clock className="w-3.5 h-3.5" /> لم يُختبر
                          </span>
                        )}
                      </td>

                      <td className="px-6 py-4 text-center">
                        <div className="flex items-center justify-center gap-2">
                          <button
                            onClick={() => handleTestConnection(integ)}
                            disabled={isTesting}
                            className="p-1.5 rounded-lg border border-slate-800 bg-slate-950 text-slate-300 hover:text-emerald-400 hover:border-emerald-800/80 transition text-xs flex items-center gap-1"
                            title="اختبار الاتصال المباشر"
                          >
                            <Zap className={`w-3.5 h-3.5 ${isTesting ? 'animate-pulse text-amber-400' : 'text-emerald-400'}`} />
                            {isTesting ? 'جاري الفحص...' : 'فحص'}
                          </button>

                          <button
                            onClick={() => handleOpenEdit(integ)}
                            className="p-1.5 rounded-lg border border-slate-800 bg-slate-950 text-slate-300 hover:text-white hover:bg-slate-800 transition"
                            title="تعديل الإعدادات"
                          >
                            <Edit2 className="w-3.5 h-3.5" />
                          </button>

                          <button
                            onClick={() => handleToggleStatus(integ)}
                            className={`p-1.5 rounded-lg border border-slate-800 bg-slate-950 text-xs transition ${
                              integ.status === 'active'
                                ? 'text-amber-400 hover:bg-amber-950/30'
                                : 'text-emerald-400 hover:bg-emerald-950/30'
                            }`}
                            title={integ.status === 'active' ? 'تعطيل المزود' : 'تفعيل المزود'}
                          >
                            {integ.status === 'active' ? 'تعطيل' : 'تفعيل'}
                          </button>

                          <button
                            onClick={() => handleDelete(integ)}
                            className="p-1.5 rounded-lg border border-slate-800 bg-slate-950 text-rose-400 hover:bg-rose-950/40 hover:border-rose-800 transition"
                            title="حذف المزود"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
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

      {/* Modal: Add New Platform Provider */}
      <Modal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        title="إضافة مزود ذكاء اصطناعي مركزي للمنصة"
      >
        <form onSubmit={handleSubmitCreate} className="space-y-4 text-right">
          {modalError && (
            <div className="p-3 rounded-xl bg-rose-950/50 border border-rose-800 text-rose-300 text-xs">
              {modalError}
            </div>
          )}

          <div>
            <label className="block text-xs font-bold text-slate-300 mb-1">
              اسم التكوين المرجعي (Reference Name) *
            </label>
            <input
              type="text"
              required
              placeholder="مثال: groq-global-main"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-bold text-slate-300 mb-1">المزود (Provider) *</label>
              <select
                value={formData.provider}
                onChange={(e) => setFormData({ ...formData, provider: e.target.value })}
                className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none"
              >
                <option value="groq">Groq Cloud</option>
                <option value="openai">OpenAI</option>
                <option value="gemini">Google Gemini</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-300 mb-1">اسم النموذج (Model) *</label>
              <input
                type="text"
                required
                placeholder="مثال: llama-3.3-70b-versatile"
                value={formData.model}
                onChange={(e) => setFormData({ ...formData, model: e.target.value })}
                className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
              />
              <div className="mt-1 flex flex-wrap gap-1">
                {formData.provider === 'groq' && (
                  <>
                    <button
                      type="button"
                      onClick={() => setFormData((prev) => ({ ...prev, model: 'llama-3.3-70b-versatile' }))}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 hover:text-white"
                    >
                      llama-3.3-70b
                    </button>
                    <button
                      type="button"
                      onClick={() => setFormData((prev) => ({ ...prev, model: 'llama-3.1-8b-instant' }))}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 hover:text-white"
                    >
                      llama-3.1-8b
                    </button>
                  </>
                )}
                {formData.provider === 'openai' && (
                  <>
                    <button
                      type="button"
                      onClick={() => setFormData((prev) => ({ ...prev, model: 'gpt-4o' }))}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 hover:text-white"
                    >
                      gpt-4o
                    </button>
                    <button
                      type="button"
                      onClick={() => setFormData((prev) => ({ ...prev, model: 'gpt-4o-mini' }))}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 hover:text-white"
                    >
                      gpt-4o-mini
                    </button>
                  </>
                )}
                {formData.provider === 'gemini' && (
                  <>
                    <button
                      type="button"
                      onClick={() => setFormData((prev) => ({ ...prev, model: 'gemini-1.5-pro' }))}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 hover:text-white"
                    >
                      gemini-1.5-pro
                    </button>
                    <button
                      type="button"
                      onClick={() => setFormData((prev) => ({ ...prev, model: 'gemini-1.5-flash' }))}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 hover:text-white"
                    >
                      gemini-1.5-flash
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-300 mb-1">
              مفتاح API السري (Secret Key)
            </label>
            <input
              type="password"
              placeholder="أدخل مفتاح المزود السري..."
              value={formData.api_key || ''}
              onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
              className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
            />
            <p className="text-[11px] text-emerald-400 mt-1 flex items-center gap-1">
              <ShieldCheck className="w-3 h-3" /> سيتم تشفير المفتاح فورًا باستخدام AES-256-GCM ولن يظهر أبدًا كنص واضح.
            </p>
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-300 mb-1">رابط مخصص (Base URL - اختياري)</label>
            <input
              type="url"
              placeholder="https://api.openai.com/v1"
              value={formData.base_url || ''}
              onChange={(e) => setFormData({ ...formData, base_url: e.target.value })}
              className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-bold text-slate-300 mb-1">درجة الحرارة (Temperature)</label>
              <input
                type="number"
                step="0.05"
                min="0"
                max="2"
                value={formData.temperature}
                onChange={(e) => setFormData({ ...formData, temperature: parseFloat(e.target.value) || 0.2 })}
                className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-300 mb-1">الحد الأقصى للتوكنات (Max Tokens)</label>
              <input
                type="number"
                step="256"
                min="256"
                value={formData.max_tokens || 4096}
                onChange={(e) => setFormData({ ...formData, max_tokens: parseInt(e.target.value, 10) || 4096 })}
                className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none"
              />
            </div>
          </div>

          <div className="pt-2">
            <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-200">
              <input
                type="checkbox"
                checked={formData.is_default}
                onChange={(e) => setFormData({ ...formData, is_default: e.target.checked })}
                className="rounded border-slate-800 bg-slate-950 text-emerald-500 focus:ring-0"
              />
              تعيين كمزود افتراضي للمنصة (Default Global Provider)
            </label>
          </div>

          <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-800">
            <button
              type="button"
              onClick={() => setIsCreateOpen(false)}
              className="px-4 py-2 rounded-xl border border-slate-800 text-slate-400 hover:text-white transition text-xs"
            >
              إلغاء
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-4 py-2 rounded-xl bg-emerald-600 text-slate-950 font-bold hover:bg-emerald-500 transition text-xs flex items-center gap-2"
            >
              {isSubmitting ? 'جاري الحفظ المشفر...' : 'حفظ المزود'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal: Edit Platform Provider */}
      <Modal
        isOpen={Boolean(editingIntegration)}
        onClose={() => setEditingIntegration(null)}
        title={`تعديل مزود المنصة: ${editingIntegration?.name || ''}`}
      >
        <form onSubmit={handleSubmitEdit} className="space-y-4 text-right">
          {modalError && (
            <div className="p-3 rounded-xl bg-rose-950/50 border border-rose-800 text-rose-300 text-xs">
              {modalError}
            </div>
          )}

          <div>
            <label className="block text-xs font-bold text-slate-300 mb-1">اسم التكوين المرجعي *</label>
            <input
              type="text"
              required
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none"
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-300 mb-1">اسم النموذج (Model) *</label>
            <input
              type="text"
              required
              value={formData.model}
              onChange={(e) => setFormData({ ...formData, model: e.target.value })}
              className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none"
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-300 mb-1">
              تحديث مفتاح API (اتركه فارغًا للاحتفاظ بالمفتاح الحالي المشفر)
            </label>
            <input
              type="password"
              placeholder={`المفتاح الحالي: ${editingIntegration?.masked_api_key || '********'}`}
              value={formData.api_key || ''}
              onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
              className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-300 mb-1">رابط مخصص (Base URL - اختياري)</label>
            <input
              type="url"
              placeholder="https://api.groq.com/openai/v1"
              value={formData.base_url || ''}
              onChange={(e) => setFormData({ ...formData, base_url: e.target.value })}
              className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-bold text-slate-300 mb-1">درجة الحرارة (Temperature)</label>
              <input
                type="number"
                step="0.05"
                min="0"
                max="2"
                value={formData.temperature}
                onChange={(e) => setFormData({ ...formData, temperature: parseFloat(e.target.value) || 0.2 })}
                className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-300 mb-1">الحد الأقصى للتوكنات (Max Tokens)</label>
              <input
                type="number"
                step="256"
                min="256"
                value={formData.max_tokens || 4096}
                onChange={(e) => setFormData({ ...formData, max_tokens: parseInt(e.target.value, 10) || 4096 })}
                className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none"
              />
            </div>
          </div>

          <div className="pt-2">
            <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-200">
              <input
                type="checkbox"
                checked={formData.is_default}
                onChange={(e) => setFormData({ ...formData, is_default: e.target.checked })}
                className="rounded border-slate-800 bg-slate-950 text-emerald-500 focus:ring-0"
              />
              تعيين كمزود افتراضي للمنصة (Default Global Provider)
            </label>
          </div>

          <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-800">
            <button
              type="button"
              onClick={() => setEditingIntegration(null)}
              className="px-4 py-2 rounded-xl border border-slate-800 text-slate-400 hover:text-white transition text-xs"
            >
              إلغاء
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-4 py-2 rounded-xl bg-emerald-600 text-slate-950 font-bold hover:bg-emerald-500 transition text-xs flex items-center gap-2"
            >
              {isSubmitting ? 'جاري حفظ التعديلات...' : 'تحديث المزود'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
