import React, { useEffect, useState } from 'react';
import {
  Radio,
  Plus,
  RefreshCw,
  MessageSquare,
  Webhook,
  Send,
  Trash2,
  AlertTriangle,
  Lock,
  ShieldCheck,
  Zap,
  CheckCircle2,
  Clock,
  Loader2,
  MessageCircle,
  Camera,
  Mail,
} from 'lucide-react';
import { channelsApi } from '../api/channels';
import { Channel } from '../api/types';
import { Badge } from '../components/common/Badge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import { Modal } from '../components/common/Modal';

export const ChannelsPage: React.FC = () => {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Testing channel connectivity
  const [testingChannelId, setTestingChannelId] = useState<string | null>(null);

  // Connect Channel Modal
  const [isConnectOpen, setIsConnectOpen] = useState(false);
  const [name, setName] = useState('');
  const [channelType, setChannelType] = useState('whatsapp');
  const [provider, setProvider] = useState('meta');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [phoneNumberId, setPhoneNumberId] = useState('');
  const [accessToken, setAccessToken] = useState('');
  const [appSecret, setAppSecret] = useState('');
  const [verifyToken, setVerifyToken] = useState('');
  const [botToken, setBotToken] = useState('');
  const [botUsername, setBotUsername] = useState('');
  const [secretToken, setSecretToken] = useState('');
  const [webhookUrl, setWebhookUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  // Facebook / Instagram
  const [pageId, setPageId] = useState('');
  const [pageAccessToken, setPageAccessToken] = useState('');
  const [instagramAccountId, setInstagramAccountId] = useState('');
  // Email
  const [smtpHost, setSmtpHost] = useState('');
  const [smtpPort, setSmtpPort] = useState(587);
  const [smtpUser, setSmtpUser] = useState('');
  const [smtpPassword, setSmtpPassword] = useState('');
  const [fromEmail, setFromEmail] = useState('');
  const [useTls, setUseTls] = useState(true);

  const [connectLoading, setConnectLoading] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);

  // Delete Channel Modal
  const [deletingChannel, setDeletingChannel] = useState<Channel | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  const loadChannels = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await channelsApi.listChannels();
      setChannels(data);
    } catch (err: any) {
      setError(err?.message || 'تعذر استرجاع قنوات التواصل');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadChannels();
  }, []);

  const handleChannelTypeChange = (newType: string) => {
    setChannelType(newType);
    if (newType === 'whatsapp' || newType === 'facebook' || newType === 'instagram') {
      setProvider('meta');
    } else if (newType === 'telegram') {
      setProvider('telegram');
    } else if (newType === 'email') {
      setProvider('smtp');
    } else {
      setProvider('custom');
    }
  };

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setConnectError('يرجى كتابة اسم تعريفي للقناة');
      return;
    }
    setConnectLoading(true);
    setConnectError(null);

    const config: Record<string, any> = {};
    if (channelType === 'telegram') {
      if (!botToken.trim()) {
        setConnectError('يرجى إدخال رمز توكن البوت (Bot Token) من BotFather');
        setConnectLoading(false);
        return;
      }
      config.bot_token = botToken.trim();
      if (botUsername.trim()) config.bot_username = botUsername.trim();
      if (secretToken.trim()) config.secret_token = secretToken.trim();
    } else if (channelType === 'whatsapp') {
      if (!phoneNumberId.trim() || !accessToken.trim()) {
        setConnectError('معرف رقم الهاتف ورمز الوصول مطلوبان لربط واتساب');
        setConnectLoading(false);
        return;
      }
      config.phone_number_id = phoneNumberId.trim();
      config.access_token = accessToken.trim();
      if (phoneNumber.trim()) config.phone_number = phoneNumber.trim();
      if (appSecret.trim()) config.app_secret = appSecret.trim();
      if (verifyToken.trim()) config.verify_token = verifyToken.trim();
    } else if (channelType === 'facebook') {
      if (!pageId.trim() || !pageAccessToken.trim()) {
        setConnectError('معرف الصفحة ورمز وصول الصفحة مطلوبان لربط ماسنجر');
        setConnectLoading(false);
        return;
      }
      config.page_id = pageId.trim();
      config.page_access_token = pageAccessToken.trim();
      if (appSecret.trim()) config.app_secret = appSecret.trim();
      if (verifyToken.trim()) config.verify_token = verifyToken.trim();
    } else if (channelType === 'instagram') {
      if (!instagramAccountId.trim() || !pageAccessToken.trim()) {
        setConnectError('معرف حساب إنستغرام للأعمال ورمز وصول الصفحة مطلوبان');
        setConnectLoading(false);
        return;
      }
      config.instagram_account_id = instagramAccountId.trim();
      config.page_access_token = pageAccessToken.trim();
      if (appSecret.trim()) config.app_secret = appSecret.trim();
      if (verifyToken.trim()) config.verify_token = verifyToken.trim();
    } else if (channelType === 'email') {
      if (!smtpHost.trim() || !smtpUser.trim() || !smtpPassword.trim() || !fromEmail.trim()) {
        setConnectError('بيانات خادم البريد (المضيف، المستخدم، كلمة المرور، عنوان الإرسال) مطلوبة');
        setConnectLoading(false);
        return;
      }
      config.smtp_host = smtpHost.trim();
      config.smtp_port = Number(smtpPort) || 587;
      config.smtp_user = smtpUser.trim();
      config.smtp_password = smtpPassword.trim();
      config.from_email = fromEmail.trim();
      config.use_tls = Boolean(useTls);
    } else if (channelType === 'webhook') {
      if (!webhookUrl.trim()) {
        setConnectError('يرجى إدخال رابط الاستقبال (Endpoint URL)');
        setConnectLoading(false);
        return;
      }
      config.endpoint_url = webhookUrl.trim();
      if (apiKey.trim()) config.api_key = apiKey.trim();
    }

    try {
      await channelsApi.registerChannel({
        name: name.trim(),
        channel_type: channelType,
        provider,
        config,
      });
      setIsConnectOpen(false);
      setName('');
      setPhoneNumber('');
      setPhoneNumberId('');
      setAccessToken('');
      setAppSecret('');
      setVerifyToken('');
      setBotToken('');
      setBotUsername('');
      setSecretToken('');
      setWebhookUrl('');
      setApiKey('');
      setPageId('');
      setPageAccessToken('');
      setInstagramAccountId('');
      setSmtpHost('');
      setSmtpUser('');
      setSmtpPassword('');
      setFromEmail('');
      setActionSuccess('تم ربط قناة التواصل وتشفير أسرارها بنجاح!');
      loadChannels();
    } catch (err: any) {
      setConnectError(err?.message || 'فشل ربط قناة التواصل');
    } finally {
      setConnectLoading(false);
    }
  };

  const handleTestChannel = async (channelId: string) => {
    setTestingChannelId(channelId);
    setError(null);
    try {
      const res = await channelsApi.testChannel(channelId);
      const isSuccess = res.connected || res.status === 'connected';
      if (isSuccess) {
        setActionSuccess(`نجح اختبار الاتصال بالقناة (زمن الاستجابة: ${res.latency_ms ?? 0}ms)`);
      } else {
        setError(`فشل اختبار الاتصال: ${res.error || res.status || 'تعذر الوصول لموصل القناة'}`);
      }
      await loadChannels();
    } catch (err: any) {
      setError(err?.message || 'تعذر تشغيل اختبار الاتصال');
    } finally {
      setTestingChannelId(null);
    }
  };

  const handleDelete = async () => {
    if (!deletingChannel) return;
    setDeleteLoading(true);
    try {
      await channelsApi.deleteChannel(deletingChannel.id);
      setDeletingChannel(null);
      setActionSuccess('تم قطع اتصال القناة بنجاح.');
      loadChannels();
    } catch (err: any) {
      alert(`فشل قطع اتصال القناة: ${err?.message || 'خطأ غير معروف'}`);
    } finally {
      setDeleteLoading(false);
    }
  };

  const getChannelIcon = (type: string) => {
    switch (type.toLowerCase()) {
      case 'whatsapp':
        return <MessageSquare className="w-5 h-5 text-emerald-400" />;
      case 'webhook':
        return <Webhook className="w-5 h-5 text-teal-400" />;
      case 'telegram':
        return <Send className="w-5 h-5 text-blue-400" />;
      case 'facebook':
        return <MessageCircle className="w-5 h-5 text-indigo-400" />;
      case 'instagram':
        return <Camera className="w-5 h-5 text-pink-400" />;
      case 'email':
        return <Mail className="w-5 h-5 text-amber-400" />;
      default:
        return <Radio className="w-5 h-5 text-slate-400" />;
    }
  };

  if (loading) {
    return <LoadingState message="جاري استرجاع قنوات التواصل وربط العملاء..." />;
  }

  if (error && channels.length === 0) {
    return (
      <ErrorState
        title="تعذر تحميل قنوات التواصل"
        message={error}
        onRetry={loadChannels}
      />
    );
  }

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl sm:text-2xl font-extrabold text-white tracking-tight flex items-center gap-2">
            <Radio className="w-6 h-6 text-emerald-400" />
            <span>قنوات التواصل وربط الرسائل</span>
          </h2>
          <p className="text-xs sm:text-sm text-slate-400 mt-1">
            ربط الوكلاء الرقميين بقنوات واتساب، تيليجرام، فيسبوك، إنستغرام، البريد الإلكتروني للتفاعل مع عملائك
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => {
              setConnectError(null);
              setIsConnectOpen(true);
            }}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs sm:text-sm shadow-lg shadow-emerald-500/20 transition hover:scale-[1.02]"
          >
            <Plus className="w-4 h-4" />
            <span>ربط قناة جديدة</span>
          </button>
          <button
            onClick={loadChannels}
            className="p-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 hover:text-white border border-slate-800 transition"
            title="تحديث القنوات"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Alerts */}
      {actionSuccess && (
        <div className="p-3.5 rounded-xl bg-emerald-950/60 border border-emerald-800 text-emerald-300 text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
            <span>{actionSuccess}</span>
          </div>
          <button onClick={() => setActionSuccess(null)} className="text-emerald-400 hover:text-white">
            ✕
          </button>
        </div>
      )}

      {error && (
        <div className="p-3.5 rounded-xl bg-rose-950/60 border border-rose-800 text-rose-300 text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-rose-400 flex-shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-rose-400 hover:text-white">
            ✕
          </button>
        </div>
      )}

      {/* Security Note Banner */}
      <div className="p-4 rounded-2xl bg-slate-900 border border-slate-800 flex items-start gap-3">
        <ShieldCheck className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />
        <div className="text-xs text-slate-400 leading-relaxed">
          <span className="font-bold text-slate-200 block mb-0.5">
            حماية بيانات المستأجر والتشفير المتقدم (AES-256-GCM)
          </span>
          يتم تشفير وتأمين جميع مفاتيح الربط والتوكنز السرية لقنواتك تلقائياً داخل مساحة العزل الخاصة بشركتك. لن تظهر أية أسرار أو كلمات مرور في الواجهة لضمان الخصوصية التامة.
        </div>
      </div>

      {/* Channels Grid */}
      {channels.length === 0 ? (
        <EmptyState
          icon={Radio}
          title="لا توجد أي قنوات تواصل متصلة حالياً"
          description="اربط واتساب للأعمال، تيليجرام، فيسبوك، أو البريد الإلكتروني لتمكين موظفيك الرقميين من استقبال الرسائل والرد على العملاء تلقائياً."
          action={
            <button
              onClick={() => setIsConnectOpen(true)}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-500 text-slate-950 font-bold text-xs"
            >
              <Plus className="w-4 h-4" />
              <span>ربط أول قناة</span>
            </button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {channels.map((channel) => {
            const isActive = channel.status === 'active';
            const isTesting = testingChannelId === channel.id;

            return (
              <div
                key={channel.id}
                className="bg-slate-900 border border-slate-800 rounded-2xl p-5 hover:border-slate-700 transition flex flex-col justify-between group shadow-sm"
              >
                <div className="space-y-4">
                  {/* Top Bar */}
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <div className="w-11 h-11 rounded-2xl bg-slate-950 border border-slate-800 flex items-center justify-center">
                        {getChannelIcon(channel.channel_type)}
                      </div>
                      <div>
                        <h3 className="text-base font-bold text-white group-hover:text-emerald-400 transition">
                          {channel.name}
                        </h3>
                        <span className="text-xs text-slate-400 font-mono">
                          {channel.channel_type.toUpperCase()} • {channel.provider || 'افتراضي'}
                        </span>
                      </div>
                    </div>
                    <Badge variant={isActive ? 'success' : 'neutral'}>
                      {isActive ? 'متصلة ونشطة' : 'متوقفة'}
                    </Badge>
                  </div>

                  {/* Channel Config Details (Sanitized) */}
                  <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 space-y-2 text-xs">
                    <div className="flex items-center justify-between text-slate-400">
                      <span>معرف القناة:</span>
                      <span className="font-mono text-slate-300">
                        {channel.id.slice(0, 10)}...
                      </span>
                    </div>

                    {channel.config?.phone_number && (
                      <div className="flex items-center justify-between text-slate-400">
                        <span>رقم الواتساب:</span>
                        <span className="font-mono text-emerald-400">
                          {channel.config.phone_number}
                        </span>
                      </div>
                    )}

                    {channel.config?.phone_number_id && (
                      <div className="flex items-center justify-between text-slate-400">
                        <span>معرف الهاتف:</span>
                        <span className="font-mono text-slate-300">
                          {channel.config.phone_number_id}
                        </span>
                      </div>
                    )}

                    {channel.config?.page_id && (
                      <div className="flex items-center justify-between text-slate-400">
                        <span>معرف صفحة فيسبوك:</span>
                        <span className="font-mono text-indigo-400">
                          {channel.config.page_id}
                        </span>
                      </div>
                    )}

                    {channel.config?.instagram_account_id && (
                      <div className="flex items-center justify-between text-slate-400">
                        <span>معرف إنستغرام:</span>
                        <span className="font-mono text-pink-400">
                          {channel.config.instagram_account_id}
                        </span>
                      </div>
                    )}

                    {channel.config?.from_email && (
                      <div className="flex items-center justify-between text-slate-400">
                        <span>بريد الإرسال:</span>
                        <span className="font-mono text-amber-400">
                          {channel.config.from_email}
                        </span>
                      </div>
                    )}

                    {channel.config?.bot_username && (
                      <div className="flex items-center justify-between text-slate-400">
                        <span>معرف البوت:</span>
                        <span className="font-mono text-blue-400">
                          {channel.config.bot_username}
                        </span>
                      </div>
                    )}

                    {channel.config?.endpoint_url && (
                      <div className="flex items-center justify-between text-slate-400">
                        <span>مسار الويب هوك:</span>
                        <span className="font-mono text-teal-400 truncate max-w-[140px]" dir="ltr">
                          {channel.config.endpoint_url}
                        </span>
                      </div>
                    )}

                    <div className="flex items-center justify-between text-slate-400">
                      <span>الأمان والمفاتيح:</span>
                      <span className="text-emerald-400 flex items-center gap-1 font-semibold">
                        <Lock className="w-3 h-3" />
                        مشفرة بالكامل
                      </span>
                    </div>
                  </div>

                  {/* Telemetry & Test Connectivity Box */}
                  <div className="p-3 rounded-xl bg-slate-950/80 border border-slate-800 text-xs space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-slate-400 font-medium">حالة الاتصال:</span>
                      {channel.last_test_status === 'success' ? (
                        <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-800 flex items-center gap-1">
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> جاهز للاتصال
                        </span>
                      ) : channel.last_test_status === 'failed' ? (
                        <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-rose-950 text-rose-300 border border-rose-800 flex items-center gap-1">
                          <AlertTriangle className="w-3.5 h-3.5 text-rose-400" /> فشل الاتصال
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-amber-950 text-amber-300 border border-amber-800 flex items-center gap-1">
                          <Clock className="w-3.5 h-3.5 text-amber-400" /> لم تُختبر بعد
                        </span>
                      )}
                    </div>

                    {channel.last_test_status === 'success' && channel.last_test_result?.latency_ms && (
                      <div className="text-[10px] text-emerald-400 flex items-center justify-between pt-1 border-t border-slate-800/60">
                        <span>الاستجابة: {channel.last_test_result.latency_ms} ms</span>
                        {channel.last_tested_at && (
                          <span className="text-slate-500 font-mono">
                            {new Date(channel.last_tested_at).toLocaleTimeString('ar-EG')}
                          </span>
                        )}
                      </div>
                    )}

                    {channel.last_test_status === 'failed' && channel.last_test_result?.error_message && (
                      <div className="text-[10px] text-rose-400 pt-1 border-t border-slate-800/60 truncate">
                        {channel.last_test_result.error_message}
                      </div>
                    )}
                  </div>
                </div>

                {/* Bottom Actions */}
                <div className="pt-4 mt-4 border-t border-slate-800 flex items-center justify-between">
                  <button
                    type="button"
                    onClick={() => handleTestChannel(channel.id)}
                    disabled={isTesting}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-emerald-400 hover:text-emerald-300 hover:bg-emerald-950/40 border border-emerald-900/40 transition disabled:opacity-50"
                  >
                    {isTesting ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        <span>جاري الفحص...</span>
                      </>
                    ) : (
                      <>
                        <Zap className="w-3.5 h-3.5 text-emerald-400" />
                        <span>اختبار الاتصال</span>
                      </>
                    )}
                  </button>

                  <button
                    onClick={() => setDeletingChannel(channel)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-rose-400 hover:text-rose-300 hover:bg-rose-950/40 border border-rose-900/40 transition"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>قطع الاتصال</span>
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Connect Channel Modal */}
      <Modal
        isOpen={isConnectOpen}
        onClose={() => setIsConnectOpen(false)}
        title="ربط قناة تواصل جديدة"
        description="اختر نوع القناة لإتاحة استقبال الرسائل من العملاء وتوجيهها للوكلاء الرقميين."
      >
        <form onSubmit={handleConnect} className="space-y-4">
          {connectError && (
            <div className="p-3 rounded-lg bg-rose-950/50 border border-rose-800 text-rose-300 text-xs flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              <span>{connectError}</span>
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              اسم القناة التعريفي <span className="text-rose-400">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="مثال: واتساب الدعم الفني، روبوت تيليجرام المبيعات"
              required
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                نوع القناة
              </label>
              <select
                value={channelType}
                onChange={(e) => handleChannelTypeChange(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500 transition"
              >
                <option value="whatsapp">واتساب (WhatsApp Cloud)</option>
                <option value="telegram">تيليجرام (Telegram Bot)</option>
                <option value="facebook">ماسنجر فيسبوك (Facebook Messenger)</option>
                <option value="instagram">إنستغرام (Instagram Messaging)</option>
                <option value="email">البريد الإلكتروني (Email SMTP)</option>
                <option value="webhook">واجهة برمجية (Webhook / API)</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                المزود التقني
              </label>
              <input
                type="text"
                readOnly
                value={provider}
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-900 border border-slate-800 text-slate-400 text-sm outline-none font-mono"
              />
            </div>
          </div>

          {channelType === 'telegram' && (
            <div className="space-y-3">
              <div className="p-3 rounded-xl bg-blue-950/40 border border-blue-900/60 text-blue-200 text-xs leading-relaxed">
                <span className="font-bold text-white block mb-1">كيفية الحصول على بيانات البوت:</span>
                1. افتح تطبيق تيليجرام وابحث عن <span className="font-mono text-blue-300">@BotFather</span>.<br />
                2. أرسل الأمر <span className="font-mono text-blue-300">/newbot</span> واتبع الخطوات لتسمية البوت.<br />
                3. انسخ الـ <span className="font-mono text-emerald-300 font-bold">HTTP API Token</span> وضعه في الحقل أدناه.
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  رمز توكن البوت (Bot Token) <span className="text-rose-400">*</span>
                </label>
                <input
                  type="password"
                  value={botToken}
                  onChange={(e) => setBotToken(e.target.value)}
                  placeholder="مثال: 7123456789:AAHq_xxxxxxxxx_yyyyyyyy"
                  required
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                    معرف البوت (Username) <span className="text-slate-500">(اختياري)</span>
                  </label>
                  <input
                    type="text"
                    value={botUsername}
                    onChange={(e) => setBotUsername(e.target.value)}
                    placeholder="@MyCompanyBot"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                    رمز سري للويب هوك <span className="text-slate-500">(اختياري)</span>
                  </label>
                  <input
                    type="password"
                    value={secretToken}
                    onChange={(e) => setSecretToken(e.target.value)}
                    placeholder="حماية إضافية للرسائل الواردة"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                  />
                </div>
              </div>
            </div>
          )}

          {channelType === 'whatsapp' && (
            <div className="space-y-3">
              <div className="p-3 rounded-xl bg-emerald-950/40 border border-emerald-900/60 text-emerald-200 text-xs leading-relaxed">
                يتطلب ربط واتساب حساب أعمال مفعل في <span className="font-bold text-white">Meta for Developers</span> وتطبيق WhatsApp Cloud API.
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                    معرف رقم الهاتف (Phone Number ID) <span className="text-rose-400">*</span>
                  </label>
                  <input
                    type="text"
                    value={phoneNumberId}
                    onChange={(e) => setPhoneNumberId(e.target.value)}
                    placeholder="104928372615243"
                    required
                    className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                    رقم الهاتف المعتمد
                  </label>
                  <input
                    type="text"
                    value={phoneNumber}
                    onChange={(e) => setPhoneNumber(e.target.value)}
                    placeholder="+966500000000"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  رمز الوصول الدائم (System User Access Token) <span className="text-rose-400">*</span>
                </label>
                <input
                  type="password"
                  value={accessToken}
                  onChange={(e) => setAccessToken(e.target.value)}
                  placeholder="EAABw..."
                  required
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                    سر التطبيق (App Secret) <span className="text-slate-500">(اختياري)</span>
                  </label>
                  <input
                    type="password"
                    value={appSecret}
                    onChange={(e) => setAppSecret(e.target.value)}
                    placeholder="مفتاح سر تطبيق Meta"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                    رمز التحقق (Verify Token)
                  </label>
                  <input
                    type="text"
                    value={verifyToken}
                    onChange={(e) => setVerifyToken(e.target.value)}
                    placeholder="my-secret-verify-token"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                  />
                </div>
              </div>
            </div>
          )}

          {channelType === 'facebook' && (
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  معرف صفحة فيسبوك (Facebook Page ID) <span className="text-rose-400">*</span>
                </label>
                <input
                  type="text"
                  value={pageId}
                  onChange={(e) => setPageId(e.target.value)}
                  placeholder="109283746501928"
                  required
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                  dir="ltr"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  رمز وصول الصفحة (Page Access Token) <span className="text-rose-400">*</span>
                </label>
                <input
                  type="password"
                  value={pageAccessToken}
                  onChange={(e) => setPageAccessToken(e.target.value)}
                  placeholder="EAA..."
                  required
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                />
              </div>
            </div>
          )}

          {channelType === 'instagram' && (
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  معرف حساب إنستغرام للأعمال (Instagram Account ID) <span className="text-rose-400">*</span>
                </label>
                <input
                  type="text"
                  value={instagramAccountId}
                  onChange={(e) => setInstagramAccountId(e.target.value)}
                  placeholder="17841400000000000"
                  required
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                  dir="ltr"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  رمز وصول الصفحة المرتبطة (Page Access Token) <span className="text-rose-400">*</span>
                </label>
                <input
                  type="password"
                  value={pageAccessToken}
                  onChange={(e) => setPageAccessToken(e.target.value)}
                  placeholder="EAA..."
                  required
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                />
              </div>
            </div>
          )}

          {channelType === 'email' && (
            <div className="space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                    مضيف SMTP <span className="text-rose-400">*</span>
                  </label>
                  <input
                    type="text"
                    value={smtpHost}
                    onChange={(e) => setSmtpHost(e.target.value)}
                    placeholder="smtp.example.com"
                    required
                    className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                    dir="ltr"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                    منفذ SMTP <span className="text-rose-400">*</span>
                  </label>
                  <input
                    type="number"
                    value={smtpPort}
                    onChange={(e) => setSmtpPort(parseInt(e.target.value) || 587)}
                    required
                    className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                    dir="ltr"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                    اسم المستخدم <span className="text-rose-400">*</span>
                  </label>
                  <input
                    type="text"
                    value={smtpUser}
                    onChange={(e) => setSmtpUser(e.target.value)}
                    placeholder="user@example.com"
                    required
                    className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                    dir="ltr"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                    كلمة المرور <span className="text-rose-400">*</span>
                  </label>
                  <input
                    type="password"
                    value={smtpPassword}
                    onChange={(e) => setSmtpPassword(e.target.value)}
                    required
                    className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  عنوان البريد للمرسل (From Email) <span className="text-rose-400">*</span>
                </label>
                <input
                  type="email"
                  value={fromEmail}
                  onChange={(e) => setFromEmail(e.target.value)}
                  placeholder="support@company.com"
                  required
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                  dir="ltr"
                />
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="smtp_tls_tenant"
                  checked={useTls}
                  onChange={(e) => setUseTls(e.target.checked)}
                  className="rounded accent-emerald-500 w-4 h-4 cursor-pointer"
                />
                <label htmlFor="smtp_tls_tenant" className="text-xs text-slate-300 select-none cursor-pointer">
                  تفعيل تشفير الاتصال الآمن (TLS)
                </label>
              </div>
            </div>
          )}

          {channelType === 'webhook' && (
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  رابط الاستقبال (Endpoint URL) <span className="text-rose-400">*</span>
                </label>
                <input
                  type="url"
                  value={webhookUrl}
                  onChange={(e) => setWebhookUrl(e.target.value)}
                  placeholder="https://api.mycompany.com/webhook"
                  required
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                  dir="ltr"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  مفتاح المصادقة (API Key / Bearer Secret) <span className="text-slate-500">(اختياري)</span>
                </label>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="Secret Token"
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
                />
              </div>
            </div>
          )}

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
            <button
              type="button"
              onClick={() => setIsConnectOpen(false)}
              className="px-4 py-2 rounded-xl text-slate-400 hover:text-white text-xs sm:text-sm font-medium transition"
            >
              إلغاء
            </button>
            <button
              type="submit"
              disabled={connectLoading}
              className="px-5 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs sm:text-sm transition disabled:opacity-50"
            >
              {connectLoading ? 'جاري الربط والتشفير...' : 'تأكيد الربط والتشفير'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal
        isOpen={!!deletingChannel}
        onClose={() => setDeletingChannel(null)}
        title="تأكيد قطع اتصال القناة"
        description="تحذير: سيؤدي قطع اتصال القناة إلى توقف استلام رسائل العملاء عبرها."
      >
        <div className="space-y-4">
          <p className="text-xs sm:text-sm text-slate-300">
            هل أنت متأكد من رغبتك في حذف القناة{' '}
            <span className="font-bold text-white">"{deletingChannel?.name}"</span>؟
          </p>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
            <button
              type="button"
              onClick={() => setDeletingChannel(null)}
              className="px-4 py-2 rounded-xl text-slate-400 hover:text-white text-xs sm:text-sm font-medium transition"
            >
              تراجع
            </button>
            <button
              type="button"
              onClick={handleDelete}
              disabled={deleteLoading}
              className="px-5 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs sm:text-sm transition disabled:opacity-50"
            >
              {deleteLoading ? 'جاري الحذف...' : 'تأكيد قطع الاتصال'}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
};
