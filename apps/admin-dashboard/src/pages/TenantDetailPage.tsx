import React, { useEffect, useState } from 'react';
import { useParams, useSearchParams, useNavigate, Link } from 'react-router-dom';
import {
  ArrowRight,
  RefreshCw,
  ListTodo,
  AlertTriangle,
  Cpu,
  Layers,
  Activity,
  CheckCircle2,
  ShieldAlert,
  Power,
  Building2,
  X,
  Bot,
  Plus,
  Zap,
  Lock,
  Clock,
  ShieldCheck,
  Loader2,
  Radio,
  Send,
  MessageSquare,
  MessageCircle,
  Camera,
  Mail,
  Webhook,
  Trash2,
} from 'lucide-react';
import { adminApi } from '../api/admin';
import {
  TenantDashboardData,
  TaskItem,
  TenantErrorsResponse,
  TenantCapabilitiesResponse,
  ExecutionTraceItem,
  ExecutionStepItem,
  TenantChannelItem,
} from '../api/types';
import { Badge } from '../components/common/Badge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import { Modal } from '../components/common/Modal';

type TabType = 'tasks' | 'errors' | 'capabilities' | 'channels' | 'traces';

export const TenantDetailPage: React.FC = () => {
  const { tenantId } = useParams<{ tenantId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const rawTab = searchParams.get('tab');
  const activeTab: TabType = (rawTab === 'integrations' ? 'channels' : rawTab as TabType) || 'tasks';

  const [dashboardData, setDashboardData] = useState<TenantDashboardData | null>(null);
  const [isLoadingTenant, setIsLoadingTenant] = useState<boolean>(true);
  const [tenantError, setTenantError] = useState<string | null>(null);

  // Tab content state
  const [isTabLoading, setIsTabLoading] = useState<boolean>(false);
  const [tabError, setTabError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Tasks state
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [taskStatusFilter, setTaskStatusFilter] = useState<string>('');
  const [cancellingTaskId, setCancellingTaskId] = useState<string | null>(null);
  const [cancelReason, setCancelReason] = useState<string>('');
  const [isCancelling, setIsCancelling] = useState<boolean>(false);

  // Errors state
  const [errorsData, setErrorsData] = useState<TenantErrorsResponse | null>(null);

  // Capabilities state
  const [capabilitiesData, setCapabilitiesData] = useState<TenantCapabilitiesResponse | null>(null);

  // Channels state (قنوات الاتصال للمستأجر)
  const [channels, setChannels] = useState<TenantChannelItem[]>([]);
  const [updatingChannelId, setUpdatingChannelId] = useState<string | null>(null);
  const [testingChannelId, setTestingChannelId] = useState<string | null>(null);
  const [deletingChannelId, setDeletingChannelId] = useState<string | null>(null);
  const [isAddChannelOpen, setIsAddChannelOpen] = useState<boolean>(false);
  const [channelModalError, setChannelModalError] = useState<string | null>(null);
  const [isSubmittingChannel, setIsSubmittingChannel] = useState<boolean>(false);

  const [channelFormData, setChannelFormData] = useState({
    name: '',
    channel_type: 'telegram' as 'telegram' | 'whatsapp' | 'facebook' | 'instagram' | 'email' | 'webhook',
    provider: 'telegram',
    // Telegram
    bot_token: '',
    bot_username: '',
    secret_token: '',
    update_mode: 'polling',
    telegram_webhook_url: '',
    // WhatsApp
    phone_number: '',
    phone_number_id: '',
    whatsapp_access_token: '',
    whatsapp_app_secret: '',
    whatsapp_verify_token: '',
    // Facebook Messenger
    page_id: '',
    messenger_page_access_token: '',
    messenger_app_secret: '',
    messenger_verify_token: '',
    // Instagram
    instagram_account_id: '',
    instagram_page_access_token: '',
    instagram_app_secret: '',
    instagram_verify_token: '',
    // Email SMTP
    smtp_host: '',
    smtp_port: 587,
    smtp_user: '',
    smtp_password: '',
    from_email: '',
    use_tls: true,
    // Webhook
    webhook_endpoint_url: '',
    webhook_api_key: '',
  });

  // Traces state
  const [traces, setTraces] = useState<ExecutionTraceItem[]>([]);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [traceSteps, setTraceSteps] = useState<ExecutionStepItem[]>([]);
  const [loadingSteps, setLoadingSteps] = useState<boolean>(false);

  // Fetch Tenant Overview
  const fetchTenantOverview = async () => {
    if (!tenantId) return;
    setIsLoadingTenant(true);
    setTenantError(null);
    try {
      const data = await adminApi.getTenantDashboard(tenantId);
      setDashboardData(data);
    } catch (err: any) {
      setTenantError(err?.message || 'تعذر جلب بيانات المستأجر');
    } finally {
      setIsLoadingTenant(false);
    }
  };

  useEffect(() => {
    fetchTenantOverview();
  }, [tenantId]);

  // Fetch Tab Specific Data
  const loadTabData = async (tab: TabType) => {
    if (!tenantId) return;
    setIsTabLoading(true);
    setTabError(null);
    setActionSuccess(null);

    try {
      if (tab === 'tasks') {
        const res = await adminApi.getTenantTasks(tenantId, taskStatusFilter || undefined);
        setTasks(res.tasks || []);
      } else if (tab === 'errors') {
        const res = await adminApi.getTenantErrors(tenantId);
        setErrorsData(res);
      } else if (tab === 'capabilities') {
        const res = await adminApi.getTenantCapabilities(tenantId);
        setCapabilitiesData(res);
      } else if (tab === 'channels') {
        const res = await adminApi.getTenantChannels(tenantId);
        setChannels(res || []);
      } else if (tab === 'traces') {
        const res = await adminApi.getTenantTraces(tenantId);
        setTraces(res.items || []);
        setSelectedTraceId(null);
        setTraceSteps([]);
      }
    } catch (err: any) {
      setTabError(err?.message || 'تعذر تحميل بيانات التبويب');
    } finally {
      setIsTabLoading(false);
    }
  };

  useEffect(() => {
    if (tenantId && !tenantError && !isLoadingTenant) {
      loadTabData(activeTab);
    }
  }, [tenantId, activeTab, isLoadingTenant]);

  const handleTabChange = (newTab: TabType) => {
    setSearchParams({ tab: newTab });
  };

  const handleCancelTask = async (taskId: string) => {
    if (!tenantId || !cancelReason.trim()) return;
    if (cancelReason.trim().length < 15) {
      setTabError('سبب الإلغاء الطارئ يجب ألا يقل عن 15 حرفاً لضمان التدقيق الأمني');
      return;
    }

    setIsCancelling(true);
    setTabError(null);
    try {
      await adminApi.emergencyCancelTask(tenantId, taskId, cancelReason.trim());
      setActionSuccess('تم إلغاء المهمة بنجاح وتوثيق سبب الإلغاء في سجل التدقيق الأمني.');
      setCancellingTaskId(null);
      setCancelReason('');
      await loadTabData('tasks');
      await fetchTenantOverview();
    } catch (err: any) {
      setTabError(err?.message || 'فشل إلغاء المهمة');
    } finally {
      setIsCancelling(false);
    }
  };

  const handleOpenAddChannel = () => {
    setChannelFormData({
      name: '',
      channel_type: 'telegram',
      provider: 'telegram',
      bot_token: '',
      bot_username: '',
      secret_token: '',
      update_mode: 'polling',
      telegram_webhook_url: '',
      phone_number: '',
      phone_number_id: '',
      whatsapp_access_token: '',
      whatsapp_app_secret: '',
      whatsapp_verify_token: '',
      page_id: '',
      messenger_page_access_token: '',
      messenger_app_secret: '',
      messenger_verify_token: '',
      instagram_account_id: '',
      instagram_page_access_token: '',
      instagram_app_secret: '',
      instagram_verify_token: '',
      smtp_host: '',
      smtp_port: 587,
      smtp_user: '',
      smtp_password: '',
      from_email: '',
      use_tls: true,
      webhook_endpoint_url: '',
      webhook_api_key: '',
    });
    setChannelModalError(null);
    setIsAddChannelOpen(true);
  };

  const handleChannelTypeChange = (newType: 'telegram' | 'whatsapp' | 'facebook' | 'instagram' | 'email' | 'webhook') => {
    let defaultProvider = 'telegram';
    if (newType === 'whatsapp' || newType === 'facebook' || newType === 'instagram') defaultProvider = 'meta';
    else if (newType === 'email') defaultProvider = 'smtp';
    else if (newType === 'webhook') defaultProvider = 'custom';

    setChannelFormData((prev) => ({
      ...prev,
      channel_type: newType,
      provider: defaultProvider,
    }));
  };

  const handleSubmitCreateChannel = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!tenantId) return;
    if (!channelFormData.name.trim()) {
      setChannelModalError('الرجاء إدخال اسم تعريفي واضح للقناة');
      return;
    }

    const config: Record<string, any> = {};

    if (channelFormData.channel_type === 'telegram') {
      if (!channelFormData.bot_token.trim()) {
        setChannelModalError('رمز توكن البوت (Bot Token) من BotFather مطلوب');
        return;
      }
      config.bot_token = channelFormData.bot_token.trim();
      if (channelFormData.bot_username.trim()) config.bot_username = channelFormData.bot_username.trim();
      if (channelFormData.secret_token.trim()) config.secret_token = channelFormData.secret_token.trim();
      config.update_mode = channelFormData.update_mode;
      if (channelFormData.update_mode === 'webhook' && channelFormData.telegram_webhook_url.trim()) {
        config.webhook_url = channelFormData.telegram_webhook_url.trim();
      }
    } else if (channelFormData.channel_type === 'whatsapp') {
      if (!channelFormData.phone_number_id.trim() || !channelFormData.whatsapp_access_token.trim()) {
        setChannelModalError('معرف رقم الهاتف (Phone Number ID) ورمز الوصول الدائم مطلوبان للربط');
        return;
      }
      config.phone_number_id = channelFormData.phone_number_id.trim();
      config.access_token = channelFormData.whatsapp_access_token.trim();
      if (channelFormData.phone_number.trim()) config.phone_number = channelFormData.phone_number.trim();
      if (channelFormData.whatsapp_app_secret.trim()) config.app_secret = channelFormData.whatsapp_app_secret.trim();
      if (channelFormData.whatsapp_verify_token.trim()) config.verify_token = channelFormData.whatsapp_verify_token.trim();
    } else if (channelFormData.channel_type === 'facebook') {
      if (!channelFormData.page_id.trim() || !channelFormData.messenger_page_access_token.trim()) {
        setChannelModalError('معرف صفحة فيسبوك (Page ID) وتوكن وصول الصفحة مطلوبان للربط');
        return;
      }
      config.page_id = channelFormData.page_id.trim();
      config.page_access_token = channelFormData.messenger_page_access_token.trim();
      if (channelFormData.messenger_app_secret.trim()) config.app_secret = channelFormData.messenger_app_secret.trim();
      if (channelFormData.messenger_verify_token.trim()) config.verify_token = channelFormData.messenger_verify_token.trim();
    } else if (channelFormData.channel_type === 'instagram') {
      if (!channelFormData.instagram_account_id.trim() || !channelFormData.instagram_page_access_token.trim()) {
        setChannelModalError('معرف حساب إنستغرام للأعمال (Instagram Account ID) وتوكن الوصول مطلوبان للربط');
        return;
      }
      config.instagram_account_id = channelFormData.instagram_account_id.trim();
      config.page_access_token = channelFormData.instagram_page_access_token.trim();
      if (channelFormData.instagram_app_secret.trim()) config.app_secret = channelFormData.instagram_app_secret.trim();
      if (channelFormData.instagram_verify_token.trim()) config.verify_token = channelFormData.instagram_verify_token.trim();
    } else if (channelFormData.channel_type === 'email') {
      if (
        !channelFormData.smtp_host.trim() ||
        !channelFormData.smtp_user.trim() ||
        !channelFormData.smtp_password.trim() ||
        !channelFormData.from_email.trim()
      ) {
        setChannelModalError('بيانات خادم SMTP (المضيف، المستخدم، كلمة المرور، وعنوان الإرسال) مطلوبة');
        return;
      }
      config.smtp_host = channelFormData.smtp_host.trim();
      config.smtp_port = Number(channelFormData.smtp_port) || 587;
      config.smtp_user = channelFormData.smtp_user.trim();
      config.smtp_password = channelFormData.smtp_password.trim();
      config.from_email = channelFormData.from_email.trim();
      config.use_tls = Boolean(channelFormData.use_tls);
    } else if (channelFormData.channel_type === 'webhook') {
      if (!channelFormData.webhook_endpoint_url.trim()) {
        setChannelModalError('رابط استقبال الويب هوك (Endpoint URL) مطلوب');
        return;
      }
      config.endpoint_url = channelFormData.webhook_endpoint_url.trim();
      if (channelFormData.webhook_api_key.trim()) config.api_key = channelFormData.webhook_api_key.trim();
    }

    setIsSubmittingChannel(true);
    setChannelModalError(null);

    try {
      await adminApi.createTenantChannel(tenantId, {
        name: channelFormData.name.trim(),
        channel_type: channelFormData.channel_type,
        provider: channelFormData.provider,
        config,
      });
      setIsAddChannelOpen(false);
      setActionSuccess('تم إنشاء وتشفير قناة الاتصال للمستأجر بنجاح! يُنصح بإجراء «اختبار الاتصال» للتأكد من الجاهزية.');
      await loadTabData('channels');
      await fetchTenantOverview();
    } catch (err: any) {
      setChannelModalError(err?.message || 'فشل حفظ قناة الاتصال للمستأجر');
    } finally {
      setIsSubmittingChannel(false);
    }
  };

  const handleTestTenantChannel = async (channelId: string) => {
    if (!tenantId) return;
    setTestingChannelId(channelId);
    setTabError(null);
    try {
      const result = await adminApi.testTenantChannel(tenantId, channelId);
      const isSuccess = result.connected || result.success || result.status === 'connected';
      if (isSuccess) {
        setActionSuccess(`نجح اختبار الاتصال بالقناة بنجاح (زمن الاستجابة: ${result.latency_ms ?? 0}ms)`);
      } else {
        const errorMsg = result.error || result.error_message || result.error_type || result.status || 'فشل الاتصال بموصل القناة';
        setTabError(`فشل اختبار الاتصال بالقناة: ${errorMsg}`);
      }
      await loadTabData('channels');
    } catch (err: any) {
      setTabError(err?.message || 'تعذر استدعاء اختبار اتصال القناة');
    } finally {
      setTestingChannelId(null);
    }
  };

  const handleToggleChannelStatus = async (channelId: string, currentStatus: string) => {
    if (!tenantId) return;
    const newStatus = currentStatus === 'active' ? 'disabled' : 'active';
    setUpdatingChannelId(channelId);
    setTabError(null);
    try {
      await adminApi.updateTenantChannel(tenantId, channelId, { status: newStatus });
      setActionSuccess(`تم تحديث حالة قناة الاتصال إلى: ${newStatus}`);
      await loadTabData('channels');
      await fetchTenantOverview();
    } catch (err: any) {
      setTabError(err?.message || 'فشل تحديث حالة قناة الاتصال');
    } finally {
      setUpdatingChannelId(null);
    }
  };

  const handleDeleteTenantChannel = async (channelId: string) => {
    if (!tenantId) return;
    if (!window.confirm('هل أنت متأكد من رغبتك في حذف أو قطع اتصال هذه القناة؟ لن يتمكن العملاء من مراسلة الوكلاء عبرها.')) {
      return;
    }
    setDeletingChannelId(channelId);
    setTabError(null);
    try {
      await adminApi.deleteTenantChannel(tenantId, channelId);
      setActionSuccess('تم حذف قناة الاتصال وقطع ارتباطها بنجاح.');
      await loadTabData('channels');
      await fetchTenantOverview();
    } catch (err: any) {
      setTabError(err?.message || 'تعذر حذف قناة الاتصال');
    } finally {
      setDeletingChannelId(null);
    }
  };

  const handleViewTraceSteps = async (traceUuid: string) => {
    if (!tenantId) return;
    setSelectedTraceId(traceUuid);
    setLoadingSteps(true);
    try {
      const steps = await adminApi.getTenantTraceSteps(tenantId, traceUuid, 'tree');
      setTraceSteps(steps || []);
    } catch (err: any) {
      setTabError(err?.message || 'تعذر جلب خطوات التتبع');
    } finally {
      setLoadingSteps(false);
    }
  };

  const getChannelIcon = (type: string) => {
    switch (type.toLowerCase()) {
      case 'telegram':
        return <Send className="w-5 h-5 text-blue-400" />;
      case 'whatsapp':
        return <MessageSquare className="w-5 h-5 text-emerald-400" />;
      case 'facebook':
        return <MessageCircle className="w-5 h-5 text-indigo-400" />;
      case 'instagram':
        return <Camera className="w-5 h-5 text-pink-400" />;
      case 'email':
        return <Mail className="w-5 h-5 text-amber-400" />;
      case 'webhook':
        return <Webhook className="w-5 h-5 text-teal-400" />;
      default:
        return <Radio className="w-5 h-5 text-slate-400" />;
    }
  };

  const getChannelTypeLabel = (type: string) => {
    switch (type.toLowerCase()) {
      case 'telegram':
        return 'تيليجرام (Telegram Bot)';
      case 'whatsapp':
        return 'واتساب للأعمال (WhatsApp Cloud)';
      case 'facebook':
        return 'ماسنجر فيسبوك (Facebook Messenger)';
      case 'instagram':
        return 'إنستغرام للأعمال (Instagram Messaging)';
      case 'email':
        return 'البريد الإلكتروني (SMTP)';
      case 'webhook':
        return 'واجهة برمجة / ويب هوك (Webhook)';
      default:
        return type.toUpperCase();
    }
  };

  if (isLoadingTenant) {
    return <LoadingState message="جاري استرجاع تفاصيل المستأجر..." />;
  }

  if (tenantError || !dashboardData) {
    return (
      <div className="space-y-4">
        <ErrorState
          message={tenantError || 'المستأجر غير موجود أو ليس لديك صلاحيات لعرضه'}
          onRetry={fetchTenantOverview}
        />
        <div className="flex justify-center">
          <button
            onClick={() => navigate('/tenants')}
            className="inline-flex items-center gap-2 rounded-xl bg-slate-800 px-4 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-700 transition"
          >
            <ArrowRight className="w-4 h-4" />
            <span>العودة لقائمة المستأجرين</span>
          </button>
        </div>
      </div>
    );
  }

  const { tenant, budget, tasks: taskSummary, agents: agentSummary } = dashboardData;

  return (
    <div className="space-y-6 animate-in fade-in duration-200 text-right">
      {/* Breadcrumb and Top Navigation */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-slate-800/80">
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <Link to="/tenants" className="hover:text-emerald-400 transition flex items-center gap-1">
            <Building2 className="w-3.5 h-3.5" />
            <span>المستأجرون والشركات</span>
          </Link>
          <span>/</span>
          <span className="text-white font-bold">{tenant.name}</span>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => {
              fetchTenantOverview();
              loadTabData(activeTab);
            }}
            className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-3 py-1.5 text-xs font-semibold text-slate-200 hover:bg-slate-800 border border-slate-800 transition"
            title="تحديث البيانات"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>تحديث</span>
          </button>
          <button
            onClick={() => navigate('/tenants')}
            className="inline-flex items-center gap-2 rounded-xl bg-slate-800 px-3.5 py-1.5 text-xs font-semibold text-slate-200 hover:bg-slate-700 transition"
          >
            <ArrowRight className="w-3.5 h-3.5" />
            <span>العودة للقائمة</span>
          </button>
        </div>
      </div>

      {/* Tenant Identity & Quick Stat Header Card */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 backdrop-blur">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-start gap-4">
            <div className="p-3 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
              <Building2 className="w-8 h-8" />
            </div>
            <div>
              <div className="flex items-center gap-3 flex-wrap">
                <h1 className="text-2xl font-black text-white">{tenant.name}</h1>
                <Badge status={tenant.status} />
              </div>
              <div className="flex items-center gap-3 mt-1.5 text-xs text-slate-400 font-mono flex-wrap">
                <span>المعرف: {tenant.id}</span>
                <span className="text-slate-600">|</span>
                <span>الاسم اللطيف: {tenant.slug}</span>
              </div>
            </div>
          </div>

          {/* Quick Metrics Badges */}
          <div className="flex items-center gap-4 flex-wrap bg-slate-950/70 p-3 rounded-xl border border-slate-800/80 text-xs">
            <div className="text-center px-2">
              <span className="block font-black text-white text-sm flex items-center justify-center gap-1">
                <Bot className="w-3.5 h-3.5 text-blue-400" />
                {agentSummary?.total ?? 0}
              </span>
              <span className="text-[10px] text-slate-400">الوكلاء</span>
            </div>
            <div className="text-slate-700">|</div>
            <div className="text-center px-2">
              <span className="block font-black text-white text-sm flex items-center justify-center gap-1">
                <ListTodo className="w-3.5 h-3.5 text-emerald-400" />
                {taskSummary?.total ?? 0}
              </span>
              <span className="text-[10px] text-slate-400">المهام</span>
            </div>
            <div className="text-slate-700">|</div>
            <div className="text-center px-2">
              <span className="block font-black text-rose-400 text-sm">
                {taskSummary?.failed ?? 0}
              </span>
              <span className="text-[10px] text-slate-400">فشل المهام</span>
            </div>
            <div className="text-slate-700">|</div>
            <div className="text-center px-2">
              <span className="block font-bold text-slate-200 text-xs">
                {(budget?.current_day_tokens ?? 0).toLocaleString()} توكن
              </span>
              <span className="text-[10px] text-slate-400">استهلاك اليوم</span>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs Navigation */}
      <div className="flex items-center gap-2 border-b border-slate-800 bg-slate-900/40 px-2 pt-2 rounded-t-xl overflow-x-auto">
        <button
          onClick={() => handleTabChange('tasks')}
          className={`flex items-center gap-2 px-5 py-3 text-xs font-bold rounded-t-xl transition border-b-2 ${
            activeTab === 'tasks'
              ? 'border-emerald-500 text-emerald-400 bg-slate-900'
              : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
          }`}
        >
          <ListTodo className="w-4 h-4" />
          <span>المهام التشغيلية ({taskSummary?.total ?? 0})</span>
        </button>

        <button
          onClick={() => handleTabChange('errors')}
          className={`flex items-center gap-2 px-5 py-3 text-xs font-bold rounded-t-xl transition border-b-2 ${
            activeTab === 'errors'
              ? 'border-rose-500 text-rose-400 bg-slate-900'
              : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
          }`}
        >
          <AlertTriangle className="w-4 h-4" />
          <span>مركز تشخيص الأعطال</span>
          {(taskSummary?.failed ?? 0) > 0 && (
            <span className="px-1.5 py-0.2 bg-rose-950 text-rose-300 text-[10px] rounded-full border border-rose-800">
              {taskSummary.failed}
            </span>
          )}
        </button>

        <button
          onClick={() => handleTabChange('capabilities')}
          className={`flex items-center gap-2 px-5 py-3 text-xs font-bold rounded-t-xl transition border-b-2 ${
            activeTab === 'capabilities'
              ? 'border-purple-500 text-purple-400 bg-slate-900'
              : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
          }`}
        >
          <Layers className="w-4 h-4" />
          <span>المهارات والقدرات</span>
        </button>

        {/* TAB 4: CHANNELS */}
        <button
          onClick={() => handleTabChange('channels')}
          className={`flex items-center gap-2 px-5 py-3 text-xs font-bold rounded-t-xl transition border-b-2 ${
            activeTab === 'channels'
              ? 'border-blue-500 text-blue-400 bg-slate-900'
              : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
          }`}
        >
          <Radio className="w-4 h-4" />
          <span>قنوات الاتصال ({channels.length})</span>
        </button>

        <button
          onClick={() => handleTabChange('traces')}
          className={`flex items-center gap-2 px-5 py-3 text-xs font-bold rounded-t-xl transition border-b-2 ${
            activeTab === 'traces'
              ? 'border-teal-500 text-teal-400 bg-slate-900'
              : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
          }`}
        >
          <Activity className="w-4 h-4" />
          <span>سجلات التتبع والخطوات</span>
        </button>
      </div>

      {/* Success / Error Alerts */}
      {actionSuccess && (
        <div className="p-3.5 rounded-xl bg-emerald-950/60 border border-emerald-800 text-emerald-300 text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
            <span>{actionSuccess}</span>
          </div>
          <button onClick={() => setActionSuccess(null)} className="text-emerald-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {tabError && (
        <div className="p-3.5 rounded-xl bg-rose-950/60 border border-rose-800 text-rose-300 text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-rose-400 flex-shrink-0" />
            <span>{tabError}</span>
          </div>
          <button onClick={() => setTabError(null)} className="text-rose-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Tab Body Content */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-6">
        {isTabLoading ? (
          <LoadingState message="جاري استرجاع بيانات القسم..." />
        ) : (
          <>
            {/* TAB 1: TASKS */}
            {activeTab === 'tasks' && (
              <div className="space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                  <div>
                    <h3 className="font-bold text-white text-sm">قائمة المهام التشغيلية</h3>
                    <p className="text-xs text-slate-400 mt-0.5">
                      مراقبة حالات تنفيذ مهام الوكيل للمستأجر مع إمكانية التدخل والإلغاء الطارئ للمهام العالقة.
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-400">تصفية:</span>
                    <select
                      value={taskStatusFilter}
                      onChange={(e) => {
                        setTaskStatusFilter(e.target.value);
                        adminApi.getTenantTasks(tenantId!, e.target.value || undefined).then((res) => {
                          setTasks(res.tasks || []);
                        });
                      }}
                      className="rounded-lg border border-slate-800 bg-slate-950 px-3 py-1.5 text-xs text-white focus:outline-none focus:border-emerald-500"
                    >
                      <option value="">كافة الحالات</option>
                      <option value="completed">مكتملة (Completed)</option>
                      <option value="failed">فاشلة (Failed)</option>
                      <option value="in_progress">قيد التنفيذ (In Progress)</option>
                      <option value="pending">قيد الانتظار (Pending)</option>
                    </select>
                  </div>
                </div>

                {tasks.length === 0 ? (
                  <EmptyState
                    title="لا توجد مهام مسجلة"
                    description="لم يتم تنفيذ أي مهام لهذا المستأجر حتى الآن أو لا توجد نتائج مطابقة للتصفية الحالية."
                    icon={ListTodo}
                  />
                ) : (
                  <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/60">
                    <table className="w-full text-right border-collapse text-xs">
                      <thead>
                        <tr className="border-b border-slate-800 bg-slate-900 text-slate-400">
                          <th className="py-3 px-4 font-semibold">المهمة</th>
                          <th className="py-3 px-4 font-semibold">الهدف</th>
                          <th className="py-3 px-4 font-semibold">الحالة</th>
                          <th className="py-3 px-4 font-semibold">الأولوية</th>
                          <th className="py-3 px-4 font-semibold">النتيجة / الخطأ</th>
                          <th className="py-3 px-4 font-semibold text-left">إجراء الطوارئ</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60">
                        {tasks.map((task) => (
                          <tr key={task.id} className="hover:bg-slate-800/30 transition">
                            <td className="py-3.5 px-4 font-bold text-white">{task.title}</td>
                            <td className="py-3.5 px-4 text-slate-300 max-w-xs truncate">{task.objective}</td>
                            <td className="py-3.5 px-4">
                              <Badge status={task.status} />
                            </td>
                            <td className="py-3.5 px-4 text-slate-400 font-mono text-[11px]">{task.priority}</td>
                            <td className="py-3.5 px-4 max-w-xs">
                              {task.error ? (
                                <span className="text-rose-400 truncate block font-medium" title={task.error}>
                                  {task.error}
                                </span>
                              ) : task.result && Object.keys(task.result).length > 0 ? (
                                <span className="text-slate-400 truncate block font-mono text-[11px]">
                                  {JSON.stringify(task.result)}
                                </span>
                              ) : (
                                <span className="text-slate-500 italic">لا توجد مخرجات</span>
                              )}
                            </td>
                            <td className="py-3.5 px-4 text-left">
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
                <div className="flex items-center justify-between p-4 rounded-xl border border-slate-800 bg-slate-950/60">
                  <div>
                    <h3 className="font-bold text-white text-sm">مركز تجميع وتشخيص الأعطال</h3>
                    <p className="text-xs text-slate-400 mt-0.5">
                      فحص فوري للأخطاء الحقيقية المسجلة عبر المهام، والتتبعات، واستهلاك مزودي الذكاء الاصطناعي، وصندوق الإرسال (Outbox).
                    </p>
                  </div>
                  <div className="text-center px-5 py-2.5 rounded-xl bg-slate-900 border border-slate-800">
                    <span className="block text-2xl font-black text-rose-400">{errorsData?.total_errors ?? 0}</span>
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
                    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 space-y-3">
                      <h4 className="font-bold text-slate-200 text-xs flex items-center gap-2">
                        <ListTodo className="w-4 h-4 text-rose-400" />
                        أخطاء المهام ({errorsData?.tasks_errors.length ?? 0})
                      </h4>
                      {errorsData?.tasks_errors.length === 0 ? (
                        <p className="text-xs text-slate-500">لا توجد أخطاء في المهام</p>
                      ) : (
                        <div className="space-y-2">
                          {errorsData?.tasks_errors.map((err) => (
                            <div key={err.id} className="p-3 rounded-lg bg-slate-900 border border-slate-800/80 text-xs">
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
                    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 space-y-3">
                      <h4 className="font-bold text-slate-200 text-xs flex items-center gap-2">
                        <Activity className="w-4 h-4 text-amber-400" />
                        أخطاء مسارات التتبع ({errorsData?.traces_errors.length ?? 0})
                      </h4>
                      {errorsData?.traces_errors.length === 0 ? (
                        <p className="text-xs text-slate-500">لا توجد أخطاء في مسارات التتبع</p>
                      ) : (
                        <div className="space-y-2">
                          {errorsData?.traces_errors.map((err) => (
                            <div key={err.id} className="p-3 rounded-lg bg-slate-900 border border-slate-800/80 text-xs">
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
                    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 space-y-3">
                      <h4 className="font-bold text-slate-200 text-xs flex items-center gap-2">
                        <Cpu className="w-4 h-4 text-purple-400" />
                        أخطاء مزودي الذكاء الاصطناعي ({errorsData?.ai_errors.length ?? 0})
                      </h4>
                      {errorsData?.ai_errors.length === 0 ? (
                        <p className="text-xs text-slate-500">لا توجد أخطاء في واجهات المزودين</p>
                      ) : (
                        <div className="space-y-2">
                          {errorsData?.ai_errors.map((err) => (
                            <div key={err.id} className="p-3 rounded-lg bg-slate-900 border border-slate-800/80 text-xs">
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
                    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 space-y-3">
                      <h4 className="font-bold text-slate-200 text-xs flex items-center gap-2">
                        <ShieldAlert className="w-4 h-4 text-red-400" />
                        رسائل صندوق الإرسال المتعثرة ({errorsData?.outbox_errors.length ?? 0})
                      </h4>
                      {errorsData?.outbox_errors.length === 0 ? (
                        <p className="text-xs text-slate-500">لا توجد رسائل ميتة في Outbox</p>
                      ) : (
                        <div className="space-y-2">
                          {errorsData?.outbox_errors.map((err) => (
                            <div key={err.id} className="p-3 rounded-lg bg-slate-900 border border-slate-800/80 text-xs">
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
                <div>
                  <h3 className="font-bold text-white text-sm">إدارة المهارات والقدرات البرمجية</h3>
                  <p className="text-xs text-slate-400 mt-0.5">
                    الفصل المعماري الصارم بين مهارات المستأجر الخاصة، ومكتبة المنصة المشتركة المعتمدة، وإصدارات التطوير الذاتي.
                  </p>
                </div>

                <div className="space-y-6">
                  {/* 1. Custom Tenant Capabilities */}
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 space-y-3">
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
                          <div key={cap.id} className="p-3.5 rounded-lg bg-slate-900 border border-slate-800">
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
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 space-y-3">
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
                          <div key={cap.id} className="p-3.5 rounded-lg bg-slate-900 border border-slate-800">
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
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 space-y-3">
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
                          <div key={ver.id} className="p-3.5 rounded-lg bg-slate-900 border border-slate-800">
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

            {/* TAB 4: TENANT CHANNELS (قنوات الاتصال للمستأجر) */}
            {activeTab === 'channels' && (
              <div className="space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                  <div>
                    <h3 className="font-bold text-white text-sm">قنوات الاتصال للمستأجر (Communication Channels)</h3>
                    <p className="text-xs text-slate-400 mt-0.5">
                      ربط قنوات المراسلة (تيليجرام، واتساب، فيسبوك، إنستغرام، البريد الإلكتروني، ويب هوك) مع التشفير الصارم واختبار الاتصال اللحظي.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={handleOpenAddChannel}
                    className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition shadow-sm self-start sm:self-auto"
                  >
                    <Plus className="w-4 h-4" />
                    <span>إضافة قناة اتصال</span>
                  </button>
                </div>

                {channels.length === 0 ? (
                  <EmptyState
                    title="لا توجد قنوات اتصال مسجلة لهذا المستأجر"
                    description="لم يتم ربط أي قناة تواصل (واتساب، تيليجرام، فيسبوك، بريد، إلخ) لهذا المستأجر حتى الآن. يمكنك إضافة قناة جديدة الآن."
                    icon={Radio}
                  />
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {channels.map((ch) => (
                      <div key={ch.id} className="p-4 rounded-xl border border-slate-800 bg-slate-950/60 space-y-3">
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-start gap-3">
                            <div className="p-2 rounded-xl bg-slate-900 border border-slate-800">
                              {getChannelIcon(ch.channel_type)}
                            </div>
                            <div>
                              <div className="font-bold text-white text-sm">{ch.name}</div>
                              <div className="text-xs text-slate-400 font-mono mt-0.5">
                                {getChannelTypeLabel(ch.channel_type)} • {ch.provider || 'افتراضي'}
                              </div>
                            </div>
                          </div>
                          <Badge status={ch.status || 'active'} />
                        </div>

                        {/* Masked Secrets & Config Summary Display */}
                        <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800 text-xs font-mono space-y-1.5 text-slate-300">
                          {ch.channel_type === 'telegram' && (
                            <div className="flex items-center justify-between">
                              <span className="flex items-center gap-1.5 text-slate-400">
                                <Lock className="w-3.5 h-3.5 text-blue-400" /> توكن البوت (Bot Token):
                              </span>
                              <span className="text-blue-400 font-bold">
                                {ch.config?.bot_token ? String(ch.config.bot_token).replace(/./g, '•') : '••••••••••••'}
                              </span>
                            </div>
                          )}

                          {ch.channel_type === 'whatsapp' && (
                            <>
                              <div className="flex items-center justify-between">
                                <span className="text-slate-400">معرف رقم الواتساب:</span>
                                <span className="text-emerald-400 font-bold">{ch.config?.phone_number_id || '-'}</span>
                              </div>
                              <div className="flex items-center justify-between">
                                <span className="flex items-center gap-1.5 text-slate-400">
                                  <Lock className="w-3.5 h-3.5 text-emerald-400" /> توكن الوصول السري:
                                </span>
                                <span className="text-emerald-400 font-bold">••••••••••••</span>
                              </div>
                            </>
                          )}

                          {ch.channel_type === 'facebook' && (
                            <>
                              <div className="flex items-center justify-between">
                                <span className="text-slate-400">معرف صفحة فيسبوك:</span>
                                <span className="text-indigo-400 font-bold">{ch.config?.page_id || '-'}</span>
                              </div>
                              <div className="flex items-center justify-between">
                                <span className="flex items-center gap-1.5 text-slate-400">
                                  <Lock className="w-3.5 h-3.5 text-indigo-400" /> توكن الصفحة السري:
                                </span>
                                <span className="text-indigo-400 font-bold">••••••••••••</span>
                              </div>
                            </>
                          )}

                          {ch.channel_type === 'instagram' && (
                            <>
                              <div className="flex items-center justify-between">
                                <span className="text-slate-400">معرف حساب إنستغرام:</span>
                                <span className="text-pink-400 font-bold">{ch.config?.instagram_account_id || '-'}</span>
                              </div>
                              <div className="flex items-center justify-between">
                                <span className="flex items-center gap-1.5 text-slate-400">
                                  <Lock className="w-3.5 h-3.5 text-pink-400" /> توكن الوصول:
                                </span>
                                <span className="text-pink-400 font-bold">••••••••••••</span>
                              </div>
                            </>
                          )}

                          {ch.channel_type === 'email' && (
                            <>
                              <div className="flex items-center justify-between">
                                <span className="text-slate-400">خادم SMTP / المرسل:</span>
                                <span className="text-amber-400 font-bold">{ch.config?.from_email || ch.config?.smtp_host || '-'}</span>
                              </div>
                              <div className="flex items-center justify-between">
                                <span className="flex items-center gap-1.5 text-slate-400">
                                  <Lock className="w-3.5 h-3.5 text-amber-400" /> كلمة مرور SMTP:
                                </span>
                                <span className="text-amber-400 font-bold">••••••••••••</span>
                              </div>
                            </>
                          )}

                          {ch.channel_type === 'webhook' && (
                            <div className="flex items-center justify-between">
                              <span className="text-slate-400">رابط الاستقبال:</span>
                              <span className="text-teal-400 font-bold truncate max-w-[200px]" dir="ltr">
                                {ch.config?.endpoint_url || '-'}
                              </span>
                            </div>
                          )}
                        </div>

                        {/* Live Connection Test Status & Telemetry */}
                        <div className="p-3 rounded-lg bg-slate-900/80 border border-slate-800/80 text-xs space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="text-slate-400 font-medium">حالة الاتصال والجاهزية:</span>
                            {ch.last_test_status === 'success' ? (
                              <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-800 flex items-center gap-1">
                                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> جاهز للاتصال
                              </span>
                            ) : ch.last_test_status === 'failed' ? (
                              <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-rose-950 text-rose-300 border border-rose-800 flex items-center gap-1">
                                <AlertTriangle className="w-3.5 h-3.5 text-rose-400" /> فشل الاتصال
                              </span>
                            ) : (
                              <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-amber-950 text-amber-300 border border-amber-800 flex items-center gap-1">
                                <Clock className="w-3.5 h-3.5 text-amber-400" /> لم تُختبر بعد
                              </span>
                            )}
                          </div>

                          {ch.last_test_status === 'success' && (
                            <div className="text-[11px] text-emerald-400 flex items-center justify-between pt-1 border-t border-slate-800/60">
                              <span>زمن الاستجابة: {ch.last_test_result?.latency_ms ?? '-'} ms</span>
                              {ch.last_tested_at && (
                                <span className="text-slate-500 font-mono text-[10px]">
                                  {new Date(ch.last_tested_at).toLocaleTimeString('ar-EG')}
                                </span>
                              )}
                            </div>
                          )}

                          {ch.last_test_status === 'failed' && (
                            <div className="text-[11px] text-rose-400 bg-rose-950/40 p-2 rounded border border-rose-900/50 mt-1">
                              <div className="font-semibold">{ch.last_test_result?.error_type || 'خطأ في المصادقة'}</div>
                              <div className="text-[10px] text-rose-300 mt-0.5">
                                {ch.last_test_result?.error_message || 'تعذر الاتصال بالقناة أو أن المفاتيح غير صالحة'}
                              </div>
                            </div>
                          )}

                          {(!ch.last_test_status || ch.last_test_status === 'untested') && (
                            <p className="text-[11px] text-amber-400/90 pt-1">
                              تم حفظ إعدادات القناة، يُرجى إجراء اختبار الاتصال للتحقق من المفاتيح قبل توجيه رسائل العملاء للوكلاء.
                            </p>
                          )}
                        </div>

                        {/* Actions */}
                        <div className="flex items-center justify-between pt-2 border-t border-slate-800/60">
                          <button
                            type="button"
                            onClick={() => handleTestTenantChannel(ch.id)}
                            disabled={testingChannelId === ch.id}
                            className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-emerald-950 hover:bg-emerald-900 border border-emerald-800 text-emerald-300 transition flex items-center gap-1.5 disabled:opacity-50"
                          >
                            {testingChannelId === ch.id ? (
                              <>
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                <span>جاري الاختبار...</span>
                              </>
                            ) : (
                              <>
                                <Zap className="w-3.5 h-3.5 text-emerald-400" />
                                <span>اختبار الاتصال</span>
                              </>
                            )}
                          </button>

                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => handleToggleChannelStatus(ch.id, ch.status || 'active')}
                              disabled={updatingChannelId === ch.id}
                              className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition flex items-center gap-1.5 ${
                                ch.status === 'disabled'
                                  ? 'bg-emerald-950 border border-emerald-800 text-emerald-300 hover:bg-emerald-900'
                                  : 'bg-rose-950 border border-rose-800 text-rose-300 hover:bg-rose-900'
                              }`}
                            >
                              <Power className="w-3.5 h-3.5" />
                              <span>{ch.status === 'disabled' ? 'تفعيل القناة' : 'تعطيل طارئ'}</span>
                            </button>

                            <button
                              type="button"
                              onClick={() => handleDeleteTenantChannel(ch.id)}
                              disabled={deletingChannelId === ch.id}
                              className="p-1.5 rounded-lg text-rose-400 hover:text-white hover:bg-rose-900/40 border border-rose-900/40 transition"
                              title="حذف القناة"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
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
                <div>
                  <h3 className="font-bold text-white text-sm">سجلات التتبع وسلسلة الخطوات المنفذة</h3>
                  <p className="text-xs text-slate-400 mt-0.5">
                    سجلات تتبع مسارات التنفيذ (Execution Traces) وسلسلة الخطوات المنفذة مع المدد الزمنية بالملي ثانية.
                  </p>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {/* Traces List */}
                  <div className="space-y-2">
                    <h4 className="font-bold text-xs text-slate-300 mb-2">قائمة التتبعات المسجلة</h4>
                    {traces.length === 0 ? (
                      <p className="text-xs text-slate-500">لا توجد مسارات تتبع مسجلة لهذا المستأجر.</p>
                    ) : (
                      <div className="space-y-2 max-h-96 overflow-y-auto">
                        {traces.map((tr) => (
                          <div
                            key={tr.id}
                            onClick={() => handleViewTraceSteps(tr.trace_id)}
                            className={`p-3.5 rounded-xl border cursor-pointer transition text-xs ${
                              selectedTraceId === tr.trace_id
                                ? 'border-teal-500 bg-teal-950/20'
                                : 'border-slate-800 bg-slate-950/60 hover:bg-slate-900'
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
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 space-y-3">
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
                          <div key={step.id} className="p-3 rounded-lg bg-slate-900 border border-slate-800 text-xs">
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

      {/* Modal: Add New Communication Channel (قناة اتصال للمستأجر) */}
      <Modal
        isOpen={isAddChannelOpen}
        onClose={() => setIsAddChannelOpen(false)}
        title="إضافة وتشفير قناة اتصال للمستأجر"
        size="lg"
      >
        <form onSubmit={handleSubmitCreateChannel} className="space-y-4 text-right">
          {channelModalError && (
            <div className="p-3 rounded-xl bg-rose-950/60 border border-rose-800 text-rose-300 text-xs">
              {channelModalError}
            </div>
          )}

          <div>
            <label className="block text-xs font-bold text-slate-300 mb-1">
              اسم القناة التعريفي (Channel Name) *
            </label>
            <input
              type="text"
              required
              placeholder="مثال: بوت تيليجرام خدمة العملاء، واتساب المبيعات الرسمي"
              value={channelFormData.name}
              onChange={(e) => setChannelFormData({ ...channelFormData, name: e.target.value })}
              className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-bold text-slate-300 mb-1">نوع قناة الاتصال (Channel Type) *</label>
              <select
                value={channelFormData.channel_type}
                onChange={(e) =>
                  handleChannelTypeChange(
                    e.target.value as 'telegram' | 'whatsapp' | 'facebook' | 'instagram' | 'email' | 'webhook'
                  )
                }
                className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none"
              >
                <option value="telegram">تيليجرام (Telegram Bot)</option>
                <option value="whatsapp">واتساب (WhatsApp Cloud API)</option>
                <option value="facebook">ماسنجر فيسبوك (Facebook Messenger)</option>
                <option value="instagram">إنستغرام (Instagram Messaging)</option>
                <option value="email">البريد الإلكتروني (Email SMTP)</option>
                <option value="webhook">واجهة برمجية (Webhook / API)</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-300 mb-1">المزود التقني (Provider)</label>
              <input
                type="text"
                readOnly
                value={channelFormData.provider}
                className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-800 text-slate-400 text-sm outline-none font-mono"
              />
            </div>
          </div>

          {/* DYNAMIC FIELDS: TELEGRAM */}
          {channelFormData.channel_type === 'telegram' && (
            <div className="space-y-3 p-3.5 rounded-xl bg-slate-900/60 border border-slate-800">
              <div>
                <label className="block text-xs font-bold text-slate-300 mb-1">
                  رمز توكن البوت (Bot Token) من BotFather *
                </label>
                <input
                  type="password"
                  required
                  placeholder="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
                  value={channelFormData.bot_token}
                  onChange={(e) => setChannelFormData({ ...channelFormData, bot_token: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">اسم مستخدم البوت (Bot Username - اختياري)</label>
                  <input
                    type="text"
                    placeholder="@my_support_bot"
                    value={channelFormData.bot_username}
                    onChange={(e) => setChannelFormData({ ...channelFormData, bot_username: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                    dir="ltr"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">نمط الاستقبال (Update Mode)</label>
                  <select
                    value={channelFormData.update_mode}
                    onChange={(e) => setChannelFormData({ ...channelFormData, update_mode: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none"
                  >
                    <option value="polling">Long Polling (موصى به للبيئات المغلقة)</option>
                    <option value="webhook">Webhook (استقبال فوري عبر رابط عام)</option>
                  </select>
                </div>
              </div>

              {channelFormData.update_mode === 'webhook' && (
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">رابط الاستقبال العام (Webhook URL)</label>
                  <input
                    type="url"
                    placeholder="https://example.com/api/v1/webhooks/telegram/my-channel"
                    value={channelFormData.telegram_webhook_url}
                    onChange={(e) => setChannelFormData({ ...channelFormData, telegram_webhook_url: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                    dir="ltr"
                  />
                </div>
              )}
            </div>
          )}

          {/* DYNAMIC FIELDS: WHATSAPP CLOUD */}
          {channelFormData.channel_type === 'whatsapp' && (
            <div className="space-y-3 p-3.5 rounded-xl bg-slate-900/60 border border-slate-800">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">
                    معرف رقم الهاتف (Phone Number ID) *
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="102938475610293"
                    value={channelFormData.phone_number_id}
                    onChange={(e) => setChannelFormData({ ...channelFormData, phone_number_id: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                    dir="ltr"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">رقم الهاتف الظاهر (Phone Number)</label>
                  <input
                    type="text"
                    placeholder="+966500000000"
                    value={channelFormData.phone_number}
                    onChange={(e) => setChannelFormData({ ...channelFormData, phone_number: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                    dir="ltr"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-300 mb-1">
                  رمز الوصول السري (Permanent System User Access Token) *
                </label>
                <input
                  type="password"
                  required
                  placeholder="EAAB••••••••••••••••"
                  value={channelFormData.whatsapp_access_token}
                  onChange={(e) => setChannelFormData({ ...channelFormData, whatsapp_access_token: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">سر التطبيق (App Secret للتحقق من التوقيع)</label>
                  <input
                    type="password"
                    placeholder="32-char hex secret"
                    value={channelFormData.whatsapp_app_secret}
                    onChange={(e) => setChannelFormData({ ...channelFormData, whatsapp_app_secret: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">رمز التحقق (Verify Token للمصافحة)</label>
                  <input
                    type="text"
                    placeholder="my-secret-verify-token"
                    value={channelFormData.whatsapp_verify_token}
                    onChange={(e) => setChannelFormData({ ...channelFormData, whatsapp_verify_token: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                    dir="ltr"
                  />
                </div>
              </div>
            </div>
          )}

          {/* DYNAMIC FIELDS: FACEBOOK MESSENGER */}
          {channelFormData.channel_type === 'facebook' && (
            <div className="space-y-3 p-3.5 rounded-xl bg-slate-900/60 border border-slate-800">
              <div>
                <label className="block text-xs font-bold text-slate-300 mb-1">معرف صفحة فيسبوك (Facebook Page ID) *</label>
                <input
                  type="text"
                  required
                  placeholder="109283746501928"
                  value={channelFormData.page_id}
                  onChange={(e) => setChannelFormData({ ...channelFormData, page_id: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                  dir="ltr"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-300 mb-1">
                  رمز وصول الصفحة (Page Access Token) *
                </label>
                <input
                  type="password"
                  required
                  placeholder="EAA••••••••••••••••"
                  value={channelFormData.messenger_page_access_token}
                  onChange={(e) => setChannelFormData({ ...channelFormData, messenger_page_access_token: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">سر التطبيق (App Secret)</label>
                  <input
                    type="password"
                    placeholder="Meta App Secret"
                    value={channelFormData.messenger_app_secret}
                    onChange={(e) => setChannelFormData({ ...channelFormData, messenger_app_secret: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">رمز التحقق (Verify Token)</label>
                  <input
                    type="text"
                    placeholder="fb-messenger-verify-token"
                    value={channelFormData.messenger_verify_token}
                    onChange={(e) => setChannelFormData({ ...channelFormData, messenger_verify_token: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                    dir="ltr"
                  />
                </div>
              </div>
            </div>
          )}

          {/* DYNAMIC FIELDS: INSTAGRAM MESSAGING */}
          {channelFormData.channel_type === 'instagram' && (
            <div className="space-y-3 p-3.5 rounded-xl bg-slate-900/60 border border-slate-800">
              <div>
                <label className="block text-xs font-bold text-slate-300 mb-1">
                  معرف حساب إنستغرام للأعمال (Instagram Account ID) *
                </label>
                <input
                  type="text"
                  required
                  placeholder="17841400000000000"
                  value={channelFormData.instagram_account_id}
                  onChange={(e) => setChannelFormData({ ...channelFormData, instagram_account_id: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                  dir="ltr"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-300 mb-1">
                  رمز وصول صفحة إنستغرام المرتبطة (Page Access Token) *
                </label>
                <input
                  type="password"
                  required
                  placeholder="EAA••••••••••••••••"
                  value={channelFormData.instagram_page_access_token}
                  onChange={(e) => setChannelFormData({ ...channelFormData, instagram_page_access_token: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">سر التطبيق (App Secret)</label>
                  <input
                    type="password"
                    placeholder="Meta App Secret"
                    value={channelFormData.instagram_app_secret}
                    onChange={(e) => setChannelFormData({ ...channelFormData, instagram_app_secret: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">رمز التحقق (Verify Token)</label>
                  <input
                    type="text"
                    placeholder="ig-verify-token"
                    value={channelFormData.instagram_verify_token}
                    onChange={(e) => setChannelFormData({ ...channelFormData, instagram_verify_token: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                    dir="ltr"
                  />
                </div>
              </div>
            </div>
          )}

          {/* DYNAMIC FIELDS: EMAIL SMTP */}
          {channelFormData.channel_type === 'email' && (
            <div className="space-y-3 p-3.5 rounded-xl bg-slate-900/60 border border-slate-800">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">مضيف SMTP (SMTP Host) *</label>
                  <input
                    type="text"
                    required
                    placeholder="smtp.example.com أو smtp.gmail.com"
                    value={channelFormData.smtp_host}
                    onChange={(e) => setChannelFormData({ ...channelFormData, smtp_host: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                    dir="ltr"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">منفذ SMTP (Port) *</label>
                  <input
                    type="number"
                    required
                    placeholder="587"
                    value={channelFormData.smtp_port}
                    onChange={(e) => setChannelFormData({ ...channelFormData, smtp_port: parseInt(e.target.value) || 587 })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                    dir="ltr"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">اسم المستخدم (SMTP User) *</label>
                  <input
                    type="text"
                    required
                    placeholder="user@example.com"
                    value={channelFormData.smtp_user}
                    onChange={(e) => setChannelFormData({ ...channelFormData, smtp_user: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                    dir="ltr"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-300 mb-1">كلمة المرور / مفتاح التطبيق *</label>
                  <input
                    type="password"
                    required
                    placeholder="App password"
                    value={channelFormData.smtp_password}
                    onChange={(e) => setChannelFormData({ ...channelFormData, smtp_password: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-300 mb-1">عنوان البريد الإلكتروني للمرسل (From Email) *</label>
                <input
                  type="email"
                  required
                  placeholder="support@company.com"
                  value={channelFormData.from_email}
                  onChange={(e) => setChannelFormData({ ...channelFormData, from_email: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                  dir="ltr"
                />
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="smtp_tls_check"
                  checked={channelFormData.use_tls}
                  onChange={(e) => setChannelFormData({ ...channelFormData, use_tls: e.target.checked })}
                  className="rounded accent-emerald-500 w-4 h-4 cursor-pointer"
                />
                <label htmlFor="smtp_tls_check" className="text-xs text-slate-300 select-none cursor-pointer">
                  تفعيل تشفير الاتصال الآمن (TLS / STARTTLS)
                </label>
              </div>
            </div>
          )}

          {/* DYNAMIC FIELDS: WEBHOOK */}
          {channelFormData.channel_type === 'webhook' && (
            <div className="space-y-3 p-3.5 rounded-xl bg-slate-900/60 border border-slate-800">
              <div>
                <label className="block text-xs font-bold text-slate-300 mb-1">رابط الاستقبال للويب هوك (Endpoint URL) *</label>
                <input
                  type="url"
                  required
                  placeholder="https://api.external-system.com/webhook/incoming"
                  value={channelFormData.webhook_endpoint_url}
                  onChange={(e) => setChannelFormData({ ...channelFormData, webhook_endpoint_url: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                  dir="ltr"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-300 mb-1">مفتاح المصادقة السري (API Key / Token - اختياري)</label>
                <input
                  type="password"
                  placeholder="Bearer token or custom secret"
                  value={channelFormData.webhook_api_key}
                  onChange={(e) => setChannelFormData({ ...channelFormData, webhook_api_key: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:border-emerald-500 outline-none font-mono"
                />
              </div>
            </div>
          )}

          {/* Security Banner */}
          <p className="text-[11px] text-emerald-400 flex items-center gap-1.5 p-2.5 rounded-xl bg-emerald-950/40 border border-emerald-900/40">
            <ShieldCheck className="w-4 h-4 flex-shrink-0" />
            <span>
              يتم تشفير كافة أسرار وتوكنز القناة فورياً عبر نظام التشفير القياسي AES-256-GCM ولن تظهر كنص صريح مطلقاً.
            </span>
          </p>

          <div className="flex justify-end gap-2 pt-4 border-t border-slate-800">
            <button
              type="button"
              onClick={() => setIsAddChannelOpen(false)}
              className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold transition"
            >
              إلغاء
            </button>
            <button
              type="submit"
              disabled={isSubmittingChannel}
              className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition flex items-center gap-1.5 disabled:opacity-50"
            >
              {isSubmittingChannel ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>جاري الحفظ والتشفير...</span>
                </>
              ) : (
                <span>حفظ القناة وتشفير المفاتيح</span>
              )}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
