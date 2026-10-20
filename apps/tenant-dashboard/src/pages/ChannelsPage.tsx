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

  // Connect Channel Modal
  const [isConnectOpen, setIsConnectOpen] = useState(false);
  const [name, setName] = useState('');
  const [channelType, setChannelType] = useState('whatsapp');
  const [provider, setProvider] = useState('meta');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [webhookUrl, setWebhookUrl] = useState('');
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

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setConnectError('يرجى كتابة اسم تعريفي للقناة');
      return;
    }
    setConnectLoading(true);
    setConnectError(null);

    const config: Record<string, any> = {};
    if (channelType === 'whatsapp' && phoneNumber) {
      config.phone_number = phoneNumber.trim();
    } else if (channelType === 'webhook' && webhookUrl) {
      config.endpoint_url = webhookUrl.trim();
    }

    try {
      await channelsApi.registerChannel({
        name: name.trim(),
        channel_type: channelType,
        provider: provider || null,
        config,
      });
      setIsConnectOpen(false);
      setName('');
      setPhoneNumber('');
      setWebhookUrl('');
      loadChannels();
    } catch (err: any) {
      setConnectError(err?.message || 'فشل ربط قناة التواصل');
    } finally {
      setConnectLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!deletingChannel) return;
    setDeleteLoading(true);
    try {
      await channelsApi.deleteChannel(deletingChannel.id);
      setDeletingChannel(null);
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
      default:
        return <Radio className="w-5 h-5 text-slate-400" />;
    }
  };

  if (loading) {
    return <LoadingState message="جاري استرجاع قنوات التواصل وربط العملاء..." />;
  }

  if (error) {
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
            ربط الوكلاء الرقميين بقنوات واتساب والويب هوك والمنصات الخارجية للتفاعل مع عملائك
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

      {/* Security Note Banner */}
      <div className="p-4 rounded-2xl bg-slate-900 border border-slate-800 flex items-start gap-3">
        <ShieldCheck className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />
        <div className="text-xs text-slate-400 leading-relaxed">
          <span className="font-bold text-slate-200 block mb-0.5">
            حماية بيانات المستأجر والتشفير المتقدم
          </span>
          يتم تشفير وتأمين جميع مفاتيح الربط والتوكنز السرية لقنواتك تلقائياً داخل مساحة العزل الخاصة بشركتك. لن تظهر أية أسرار أو كلمات مرور في الواجهة لضمان الخصوصية التامة.
        </div>
      </div>

      {/* Channels Grid */}
      {channels.length === 0 ? (
        <EmptyState
          icon={Radio}
          title="لا توجد أي قنوات تواصل متصلة حالياً"
          description="اربط واتساب للأعمال أو Webhook لتمكين موظفيك الرقميين من استقبال الرسائل والرد على العملاء تلقائياً."
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

                    {channel.config?.endpoint_url && (
                      <div className="flex items-center justify-between text-slate-400">
                        <span>مسار الويب هوك:</span>
                        <span className="font-mono text-teal-400 truncate max-w-[140px]">
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
                </div>

                {/* Bottom Actions */}
                <div className="pt-4 mt-4 border-t border-slate-800 flex items-center justify-between">
                  <span className="text-[11px] text-slate-400 font-mono">
                    {channel.created_at
                      ? new Date(channel.created_at).toLocaleDateString('ar-SA')
                      : ''}
                  </span>

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
              placeholder="مثال: واتساب الدعم الفني، روبوت المبيعات"
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
                onChange={(e) => setChannelType(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500 transition"
              >
                <option value="whatsapp">واتساب (WhatsApp Cloud)</option>
                <option value="webhook">واجهة برمجية (Webhook / API)</option>
                <option value="telegram">تيليجرام (Telegram Bot)</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                المزود التقني
              </label>
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500 transition"
              >
                <option value="meta">Meta Cloud API</option>
                <option value="twilio">Twilio Services</option>
                <option value="custom">مخصص / مدمج (Custom)</option>
              </select>
            </div>
          </div>

          {channelType === 'whatsapp' && (
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                رقم الهاتف المعتمد (مع الرمز الدولي)
              </label>
              <input
                type="text"
                value={phoneNumber}
                onChange={(e) => setPhoneNumber(e.target.value)}
                placeholder="+966500000000"
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
              />
            </div>
          )}

          {channelType === 'webhook' && (
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                رابط الاستقبال (Endpoint URL)
              </label>
              <input
                type="url"
                value={webhookUrl}
                onChange={(e) => setWebhookUrl(e.target.value)}
                placeholder="https://api.mycompany.com/webhook"
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-emerald-500 transition font-mono"
              />
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
              {connectLoading ? 'جاري الربط...' : 'تأكيد الربط'}
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
