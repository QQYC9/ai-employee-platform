import React, { useEffect, useState } from 'react';
import {
  Building2,
  ShieldCheck,
  Brain,
  Save,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  User as UserIcon,
  Sparkles,
  Info,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { tenantApi } from '../api/tenant';
import { Tenant, BusinessBrain } from '../api/types';
import { Badge } from '../components/common/Badge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';

export const CompanySettingsPage: React.FC = () => {
  const { user } = useAuth();
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [brain, setBrain] = useState<BusinessBrain | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form states
  const [companyName, setCompanyName] = useState('');
  const [voiceTone, setVoiceTone] = useState('');
  const [companyMission, setCompanyMission] = useState('');
  const [companyPolicies, setCompanyPolicies] = useState('');
  const [productsSummary, setProductsSummary] = useState('');

  // Saving states
  const [savingGeneral, setSavingGeneral] = useState(false);
  const [savingBrain, setSavingBrain] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [tenantData, brainData] = await Promise.all([
        tenantApi.getTenant(),
        tenantApi.getBusinessBrain(),
      ]);
      setTenant(tenantData);
      setBrain(brainData);
      setCompanyName(tenantData.name);

      // Extract brain fields safely
      setVoiceTone(brainData?.identity?.voice_tone || 'احترافي، ودود، دقيق ومباشر');
      setCompanyMission(brainData?.identity?.mission || '');
      setCompanyPolicies(
        Array.isArray(brainData?.policies?.rules)
          ? brainData.policies.rules.join('\n')
          : typeof brainData?.policies === 'string'
          ? brainData.policies
          : ''
      );
      setProductsSummary(
        typeof brainData?.products?.overview === 'string'
          ? brainData.products.overview
          : ''
      );
    } catch (err: any) {
      setError(err?.message || 'تعذر تحميل إعدادات الشركة');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleSaveGeneral = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!companyName.trim()) {
      setSaveError('اسم الشركة مطلوب');
      return;
    }
    setSavingGeneral(true);
    setSaveError(null);
    setSuccessMessage(null);
    try {
      const updated = await tenantApi.updateTenant(companyName.trim());
      setTenant(updated);
      setSuccessMessage('تم تحديث اسم الشركة بنجاح');
    } catch (err: any) {
      setSaveError(err?.message || 'فشل تحديث بيانات الشركة');
    } finally {
      setSavingGeneral(false);
      setTimeout(() => setSuccessMessage(null), 4000);
    }
  };

  const handleSaveBrain = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingBrain(true);
    setSaveError(null);
    setSuccessMessage(null);

    const rulesArray = companyPolicies
      .split('\n')
      .map((r) => r.trim())
      .filter(Boolean);

    const updatedBrain: Partial<BusinessBrain> = {
      ...(brain || {}),
      identity: {
        ...(brain?.identity || {}),
        voice_tone: voiceTone.trim(),
        mission: companyMission.trim(),
      },
      policies: {
        ...(brain?.policies || {}),
        rules: rulesArray,
      },
      products: {
        ...(brain?.products || {}),
        overview: productsSummary.trim(),
      },
    };

    try {
      const res = await tenantApi.updateBusinessBrain(updatedBrain);
      setBrain(res);
      setSuccessMessage('تم تحديث العقل المؤسسي (BusinessBrain) وسيتم تطبيقه على جميع الوكلاء فوراً');
    } catch (err: any) {
      setSaveError(err?.message || 'فشل تحديث العقل المؤسسي');
    } finally {
      setSavingBrain(false);
      setTimeout(() => setSuccessMessage(null), 4000);
    }
  };

  if (loading) {
    return <LoadingState message="جاري استرجاع بيانات وإعدادات الشركة..." />;
  }

  if (error || !tenant) {
    return (
      <ErrorState
        title="تعذر تحميل الإعدادات"
        message={error || 'حدث خطأ أثناء تحميل ملف الشركة'}
        onRetry={loadData}
      />
    );
  }

  return (
    <div className="space-y-8 animate-fadeIn max-w-5xl">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl sm:text-2xl font-extrabold text-white tracking-tight flex items-center gap-2">
            <Building2 className="w-6 h-6 text-emerald-400" />
            <span>إعدادات الشركة والملف التشغيلي</span>
          </h2>
          <p className="text-xs sm:text-sm text-slate-400 mt-1">
            إدارة بيانات المستأجر، قواعد العمل المشتركة، وتغذية العقل المؤسسي لموظفيك الرقميين
          </p>
        </div>

        <button
          onClick={loadData}
          className="p-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 hover:text-white border border-slate-800 transition self-start sm:self-auto"
          title="تحديث البيانات"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Notifications */}
      {successMessage && (
        <div className="p-4 rounded-xl bg-emerald-950/70 border border-emerald-800 text-emerald-300 text-xs sm:text-sm flex items-center gap-2.5 animate-fadeIn">
          <CheckCircle2 className="w-5 h-5 flex-shrink-0 text-emerald-400" />
          <span>{successMessage}</span>
        </div>
      )}
      {saveError && (
        <div className="p-4 rounded-xl bg-rose-950/70 border border-rose-800 text-rose-300 text-xs sm:text-sm flex items-center gap-2.5 animate-fadeIn">
          <AlertCircle className="w-5 h-5 flex-shrink-0 text-rose-400" />
          <span>{saveError}</span>
        </div>
      )}

      {/* Two Column Layout: User Card + General Info */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* User Profile Card */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <UserIcon className="w-4 h-4 text-emerald-400" />
            <span>حساب المستخدم الحالي</span>
          </h3>

          <div className="space-y-3 text-xs">
            <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80">
              <span className="text-slate-400 block mb-0.5">الاسم:</span>
              <span className="font-bold text-white text-sm">{user?.name}</span>
            </div>

            <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80">
              <span className="text-slate-400 block mb-0.5">البريد الإلكتروني:</span>
              <span className="font-mono text-slate-200">{user?.email}</span>
            </div>

            <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 flex items-center justify-between">
              <span className="text-slate-400">الصلاحية:</span>
              <Badge variant="success">{user?.role}</Badge>
            </div>
          </div>

          <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-[11px] text-emerald-300 flex items-start gap-2">
            <ShieldCheck className="w-4 h-4 flex-shrink-0 mt-0.5 text-emerald-400" />
            <span>جلسة آمنة ومحصورة بالكامل ضمن مستأجر شركتك.</span>
          </div>
        </div>

        {/* Company Profile Form */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-2xl p-5 sm:p-6 space-y-4">
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <Building2 className="w-5 h-5 text-emerald-400" />
            <span>بيانات الشركة والمستأجر</span>
          </h3>

          <form onSubmit={handleSaveGeneral} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                اسم الشركة التجاري <span className="text-rose-400">*</span>
              </label>
              <input
                type="text"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                required
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500 transition"
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
              <div className="p-3 rounded-xl bg-slate-950 border border-slate-800">
                <span className="text-slate-400 block mb-1">المعرف المختصر (Slug):</span>
                <span className="font-mono text-emerald-400 font-bold">@{tenant.slug}</span>
              </div>
              <div className="p-3 rounded-xl bg-slate-950 border border-slate-800">
                <span className="text-slate-400 block mb-1">حالة الحساب:</span>
                <Badge variant={tenant.status === 'active' ? 'success' : 'neutral'}>
                  {tenant.status === 'active' ? 'نشط ومعتمد' : tenant.status}
                </Badge>
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button
                type="submit"
                disabled={savingGeneral}
                className="inline-flex items-center gap-2 px-5 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs sm:text-sm transition disabled:opacity-50"
              >
                <Save className="w-4 h-4" />
                <span>{savingGeneral ? 'جاري الحفظ...' : 'حفظ بيانات الشركة'}</span>
              </button>
            </div>
          </form>
        </div>
      </div>

      {/* BusinessBrain Section */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 sm:p-6 space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-base sm:text-lg font-bold text-white flex items-center gap-2">
              <Brain className="w-5 h-5 text-emerald-400" />
              <span>العقل المؤسسي (BusinessBrain) وقواعد العمل</span>
            </h3>
            <p className="text-xs text-slate-400 mt-1">
              هذه المعلومات يتم تزويد جميع موظفيك الرقميين بها ليعملوا بنفس هوية وأسلوب وسياسات شركتك
            </p>
          </div>

          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <Sparkles className="w-3.5 h-3.5" />
            <span>تحديث فوري للسياق</span>
          </span>
        </div>

        <form onSubmit={handleSaveBrain} className="space-y-5">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                نبرة وأسلوب التخاطب (Voice & Tone)
              </label>
              <input
                type="text"
                value={voiceTone}
                onChange={(e) => setVoiceTone(e.target.value)}
                placeholder="مثال: احترافي، ودود، فوري، يعتمد المصطلحات التقنية الحديثة"
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-xs sm:text-sm focus:outline-none focus:border-emerald-500 transition"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                رسالة ورؤية الشركة (Company Mission)
              </label>
              <input
                type="text"
                value={companyMission}
                onChange={(e) => setCompanyMission(e.target.value)}
                placeholder="مثال: تمكين الشركات من أتمتة العمليات اليومية بأعلى معايير الدقة"
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-xs sm:text-sm focus:outline-none focus:border-emerald-500 transition"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              سياسات وقواعد العمل الإلزامية للوكلاء (سطر لكل قاعدة)
            </label>
            <textarea
              value={companyPolicies}
              onChange={(e) => setCompanyPolicies(e.target.value)}
              placeholder="مثال:&#10;- الرد دائماً باللغة العربية الفصحى المبسطة&#10;- عدم مشاركة أي أسعار بدون تأكيد رسمي&#10;- تصعيد الشكاوى المعقدة للمشرف البشري"
              rows={4}
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-xs sm:text-sm focus:outline-none focus:border-emerald-500 transition resize-none leading-relaxed"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              ملخص المنتجات والخدمات (Products & Services Overview)
            </label>
            <textarea
              value={productsSummary}
              onChange={(e) => setProductsSummary(e.target.value)}
              placeholder="نبذة مختصرة عن المنتجات أو الخدمات الرئيسية التي تقدمها شركتك للعملاء..."
              rows={3}
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-xs sm:text-sm focus:outline-none focus:border-emerald-500 transition resize-none leading-relaxed"
            />
          </div>

          <div className="flex items-center justify-between pt-3 border-t border-slate-800">
            <div className="flex items-center gap-1.5 text-xs text-slate-400">
              <Info className="w-4 h-4 text-emerald-400" />
              <span>يتم تخزين هذه البيانات في سياق الشركة ولا يمكن لأي مستأجر آخر الوصول إليها.</span>
            </div>

            <button
              type="submit"
              disabled={savingBrain}
              className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs sm:text-sm shadow-lg shadow-emerald-500/20 transition hover:scale-[1.02] disabled:opacity-50"
            >
              <Save className="w-4 h-4" />
              <span>{savingBrain ? 'جاري الحفظ وتحديث العقل...' : 'حفظ وتطبيق القواعد'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
