import React, { useEffect, useState } from 'react';
import {
  Megaphone,
  Plus,
  RefreshCw,
  Play,
  Pause,
  XCircle,
  Clock,
  CheckCircle2,
  AlertCircle,
  Bell,
  Users,
  Calendar,
} from 'lucide-react';
import { campaignsApi, CreateCampaignInput, ProactiveTriggerInput } from '../api/campaigns';
import { channelsApi } from '../api/channels';
import { Campaign, Channel } from '../api/types';
import { Badge } from '../components/common/Badge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import { Modal } from '../components/common/Modal';

export const CampaignsPage: React.FC = () => {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('all');

  // New Campaign Modal
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [goal, setGoal] = useState('');
  const [channelId, setChannelId] = useState('');
  const [messageTemplate, setMessageTemplate] = useState('');
  const [targetTags, setTargetTags] = useState('');
  const [batchSize, setBatchSize] = useState(50);
  const [rateLimit, setRateLimit] = useState(60);
  const [requiresApproval, setRequiresApproval] = useState(false);

  // Proactive Trigger Modal
  const [isProactiveOpen, setIsProactiveOpen] = useState(false);
  const [proactiveLoading, setProactiveLoading] = useState(false);
  const [proactiveError, setProactiveError] = useState<string | null>(null);
  const [proactiveSuccess, setProactiveSuccess] = useState<string | null>(null);
  const [proactiveCustomerId, setProactiveCustomerId] = useState('');
  const [proactiveChannelId, setProactiveChannelId] = useState('');
  const [proactiveType, setProactiveType] = useState<'appointment_reminder' | 'service_followup' | 'inactivity_reengagement' | 'custom'>('appointment_reminder');
  const [proactiveTime, setProactiveTime] = useState('');
  const [proactiveService, setProactiveService] = useState('');
  const [proactiveFeedbackUrl, setProactiveFeedbackUrl] = useState('');
  const [proactiveOffer, setProactiveOffer] = useState('');
  const [proactiveContent, setProactiveContent] = useState('');

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [campRes, chanRes] = await Promise.all([
        campaignsApi.listCampaigns(statusFilter === 'all' ? undefined : statusFilter),
        channelsApi.listChannels(),
      ]);
      setCampaigns(campRes.items || []);
      setChannels(chanRes || []);
      if (chanRes.length > 0 && !channelId) {
        setChannelId(chanRes[0].id);
      }
      if (chanRes.length > 0 && !proactiveChannelId) {
        setProactiveChannelId(chanRes[0].id);
      }
    } catch (err: any) {
      setError(err?.message || 'تعذر تحميل بيانات الحملات');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [statusFilter]);

  const handleCreateCampaign = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !messageTemplate.trim()) {
      setCreateError('يرجى تحديد اسم الحملة وقالب الرسالة');
      return;
    }
    setCreateLoading(true);
    setCreateError(null);

    const tags = targetTags
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);

    const payload: CreateCampaignInput = {
      name: name.trim(),
      goal: goal.trim() || undefined,
      message_template: messageTemplate.trim(),
      channel_id: channelId || undefined,
      audience_filter: tags.length > 0 ? { tags } : {},
      batch_size: batchSize,
      rate_limit_per_minute: rateLimit,
      requires_approval: requiresApproval,
    };

    try {
      await campaignsApi.createCampaign(payload);
      setIsCreateOpen(false);
      setName('');
      setGoal('');
      setMessageTemplate('');
      setTargetTags('');
      loadData();
    } catch (err: any) {
      setCreateError(err?.message || 'فشل إنشاء الحملة');
    } finally {
      setCreateLoading(false);
    }
  };

  const handleProactiveTrigger = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!proactiveCustomerId.trim() || !proactiveChannelId) {
      setProactiveError('يرجى إدخال معرف العميل واختيار القناة');
      return;
    }
    setProactiveLoading(true);
    setProactiveError(null);
    setProactiveSuccess(null);

    const payload: ProactiveTriggerInput = {
      customer_id: proactiveCustomerId.trim(),
      channel_id: proactiveChannelId,
      notification_type: proactiveType,
      appointment_time: proactiveTime || undefined,
      service_name: proactiveService || undefined,
      feedback_url: proactiveFeedbackUrl || undefined,
      offer_details: proactiveOffer || undefined,
      content: proactiveContent || undefined,
    };

    try {
      const res = await campaignsApi.triggerProactive(payload);
      setProactiveSuccess(`تم جدولة الإشعار بنجاح (الحالة: ${res.status})`);
      setTimeout(() => {
        setIsProactiveOpen(false);
        setProactiveSuccess(null);
        setProactiveCustomerId('');
        setProactiveContent('');
      }, 1500);
    } catch (err: any) {
      setProactiveError(err?.message || 'فشل إرسال الإشعار الاستباقي');
    } finally {
      setProactiveLoading(false);
    }
  };

  const handleAction = async (id: string, action: 'start' | 'pause' | 'resume' | 'cancel') => {
    try {
      if (action === 'start') await campaignsApi.startCampaign(id);
      else if (action === 'pause') await campaignsApi.pauseCampaign(id);
      else if (action === 'resume') await campaignsApi.resumeCampaign(id);
      else if (action === 'cancel') await campaignsApi.cancelCampaign(id);
      loadData();
    } catch (err: any) {
      alert(err?.message || `فشل تنفيذ العملية (${action})`);
    }
  };

  const totalDelivered = campaigns.reduce((acc, c) => acc + (c.metrics?.delivered_count || 0), 0);
  const totalEnqueued = campaigns.reduce((acc, c) => acc + (c.metrics?.enqueued_count || 0), 0);
  const activeCount = campaigns.filter((c) => c.status === 'running').length;

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Megaphone className="h-6 w-6 text-indigo-400" />
            الحملات والإشعارات الاستباقية
          </h1>
          <p className="text-gray-400 text-sm mt-1">
            إدارة حملات التواصل الجماعية، وجدولة إشعارات وتذكيرات العملاء التلقائية بأعلى درجات الموثوقية
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={loadData}
            className="p-2.5 rounded-lg bg-[#131c2e] border border-[#1e2c47] text-gray-300 hover:text-white hover:border-gray-500 transition-colors"
            title="تحديث البيانات"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={() => setIsProactiveOpen(true)}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-[#1a2640] border border-indigo-500/30 text-indigo-300 hover:bg-indigo-500/20 text-sm font-medium transition-colors"
          >
            <Bell className="h-4 w-4" />
            إشعار استباقي سريع
          </button>
          <button
            onClick={() => setIsCreateOpen(true)}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-colors shadow-lg shadow-indigo-600/20"
          >
            <Plus className="h-4 w-4" />
            حملة جديدة
          </button>
        </div>
      </div>

      {/* KPI Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-[#131c2e] border border-[#1e2c47] rounded-xl p-4">
          <div className="flex items-center justify-between text-gray-400 text-xs">
            <span>إجمالي الحملات</span>
            <Megaphone className="h-4 w-4 text-gray-400" />
          </div>
          <div className="text-2xl font-bold text-white mt-2">{campaigns.length}</div>
        </div>
        <div className="bg-[#131c2e] border border-[#1e2c47] rounded-xl p-4">
          <div className="flex items-center justify-between text-emerald-400 text-xs">
            <span>حملات قيد الإرسال</span>
            <Play className="h-4 w-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold text-emerald-300 mt-2">{activeCount}</div>
        </div>
        <div className="bg-[#131c2e] border border-[#1e2c47] rounded-xl p-4">
          <div className="flex items-center justify-between text-indigo-400 text-xs">
            <span>الرسائل المسلّمة</span>
            <CheckCircle2 className="h-4 w-4 text-indigo-400" />
          </div>
          <div className="text-2xl font-bold text-indigo-300 mt-2">{totalDelivered}</div>
        </div>
        <div className="bg-[#131c2e] border border-[#1e2c47] rounded-xl p-4">
          <div className="flex items-center justify-between text-amber-400 text-xs">
            <span>المجدولة / قيد المعالجة</span>
            <Clock className="h-4 w-4 text-amber-400" />
          </div>
          <div className="text-2xl font-bold text-amber-300 mt-2">{totalEnqueued}</div>
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 border-b border-[#1e2c47]">
        {[
          { key: 'all', label: 'الكل' },
          { key: 'draft', label: 'المسودات' },
          { key: 'scheduled', label: 'المجدولة' },
          { key: 'running', label: 'قيد التنفيذ' },
          { key: 'paused', label: 'متوقفة مؤقتاً' },
          { key: 'completed', label: 'المكتملة' },
          { key: 'cancelled', label: 'الملغاة' },
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setStatusFilter(tab.key)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors whitespace-nowrap ${
              statusFilter === tab.key
                ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30'
                : 'text-gray-400 hover:text-white hover:bg-[#131c2e]'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content State */}
      {loading ? (
        <LoadingState message="جاري استرجاع الحملات ومؤشرات الإرسال..." />
      ) : error ? (
        <ErrorState message={error} onRetry={loadData} />
      ) : campaigns.length === 0 ? (
        <EmptyState
          icon={Megaphone}
          title="لا توجد حملات مسجلة"
          description="أنشئ أول حملة تواصل أو أطلق إشعاراً استباقياً لعملائك لزيادة التفاعل."
          actionText="إنشاء حملة الآن"
          onAction={() => setIsCreateOpen(true)}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {campaigns.map((camp) => {
            const m = camp.metrics || {
              total_recipients: 0,
              enqueued_count: 0,
              delivered_count: 0,
              failed_count: 0,
              skipped_count: 0,
            };
            const channel = channels.find((ch) => ch.id === camp.channel_id);

            return (
              <div
                key={camp.id}
                className="bg-[#131c2e] border border-[#1e2c47] hover:border-gray-600 transition-colors rounded-xl p-5"
              >
                <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4">
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2.5">
                      <h3 className="text-base font-semibold text-white">{camp.name}</h3>
                      <Badge
                        variant={
                          camp.status === 'running'
                            ? 'success'
                            : camp.status === 'completed'
                            ? 'info'
                            : camp.status === 'paused'
                            ? 'warning'
                            : camp.status === 'cancelled'
                            ? 'danger'
                            : 'neutral'
                        }
                      >
                        {camp.status}
                      </Badge>
                      {camp.requires_approval && (
                        <span className="text-xs bg-amber-500/10 text-amber-300 border border-amber-500/20 px-2 py-0.5 rounded">
                          تتطلب موافقة
                        </span>
                      )}
                    </div>
                    {camp.goal && <p className="text-xs text-gray-400">الهدف: {camp.goal}</p>}
                    <div className="flex items-center gap-4 text-xs text-gray-400 mt-2">
                      <span className="flex items-center gap-1">
                        <Users className="h-3.5 w-3.5 text-gray-500" />
                        القناة: {channel ? `${channel.name} (${channel.channel_type})` : 'غير محددة'}
                      </span>
                      {camp.scheduled_at && (
                        <span className="flex items-center gap-1">
                          <Calendar className="h-3.5 w-3.5 text-gray-500" />
                          الموعد: {new Date(camp.scheduled_at).toLocaleString('ar-SA')}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Metrics Bar */}
                  <div className="w-full lg:w-72 bg-[#0d1422] p-3 rounded-lg border border-[#1a2640] space-y-1.5">
                    <div className="flex items-center justify-between text-xs text-gray-300 font-medium">
                      <span>إجمالي المستلمين: {m.total_recipients}</span>
                      <span className="text-emerald-400">{m.delivered_count} تم التسليم</span>
                    </div>
                    <div className="w-full bg-gray-800 h-2 rounded-full overflow-hidden flex">
                      <div
                        className="bg-emerald-500 h-full"
                        style={{
                          width: `${
                            m.total_recipients > 0 ? (m.delivered_count / m.total_recipients) * 100 : 0
                          }%`,
                        }}
                      />
                      <div
                        className="bg-red-500 h-full"
                        style={{
                          width: `${
                            m.total_recipients > 0 ? (m.failed_count / m.total_recipients) * 100 : 0
                          }%`,
                        }}
                      />
                      <div
                        className="bg-amber-500 h-full"
                        style={{
                          width: `${
                            m.total_recipients > 0 ? (m.skipped_count / m.total_recipients) * 100 : 0
                          }%`,
                        }}
                      />
                    </div>
                    <div className="flex items-center justify-between text-[11px] text-gray-500">
                      <span>فشل: {m.failed_count}</span>
                      <span>تم التخطي: {m.skipped_count}</span>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2">
                    {(camp.status === 'draft' || camp.status === 'scheduled') && (
                      <button
                        onClick={() => handleAction(camp.id, 'start')}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-600/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-600/30 text-xs font-medium transition-colors"
                      >
                        <Play className="h-3.5 w-3.5" />
                        بدء الإرسال
                      </button>
                    )}
                    {camp.status === 'running' && (
                      <button
                        onClick={() => handleAction(camp.id, 'pause')}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-amber-600/20 text-amber-300 border border-amber-500/30 hover:bg-amber-600/30 text-xs font-medium transition-colors"
                      >
                        <Pause className="h-3.5 w-3.5" />
                        إيقاف مؤقت
                      </button>
                    )}
                    {camp.status === 'paused' && (
                      <button
                        onClick={() => handleAction(camp.id, 'resume')}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-indigo-600/20 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-600/30 text-xs font-medium transition-colors"
                      >
                        <Play className="h-3.5 w-3.5" />
                        استئناف
                      </button>
                    )}
                    {camp.status !== 'completed' && camp.status !== 'cancelled' && (
                      <button
                        onClick={() => handleAction(camp.id, 'cancel')}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-red-600/10 text-red-300 border border-red-500/20 hover:bg-red-600/20 text-xs font-medium transition-colors"
                      >
                        <XCircle className="h-3.5 w-3.5" />
                        إلغاء
                      </button>
                    )}
                  </div>
                </div>

                {/* Template Preview */}
                <div className="mt-3 pt-3 border-t border-[#1a2640] text-xs text-gray-400">
                  <span className="text-gray-500 font-medium">قالب الرسالة: </span>
                  <span className="text-gray-300 italic">"{camp.message_template}"</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Modal: New Campaign */}
      <Modal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        title="إنشاء حملة تواصل جديدة"
      >
        <form onSubmit={handleCreateCampaign} className="space-y-4">
          {createError && (
            <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs flex items-center gap-2">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{createError}</span>
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-gray-300 mb-1">اسم الحملة *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="مثال: حملة التخفيضات الموسمية"
              className="w-full bg-[#0d1422] border border-[#1e2c47] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
              required
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-300 mb-1">هدف الحملة</label>
            <input
              type="text"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="مثال: إعادة تنشيط العملاء السابقين"
              className="w-full bg-[#0d1422] border border-[#1e2c47] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-300 mb-1">القناة المستخدمة *</label>
            <select
              value={channelId}
              onChange={(e) => setChannelId(e.target.value)}
              className="w-full bg-[#0d1422] border border-[#1e2c47] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
              required
            >
              <option value="">اختر القناة...</option>
              {channels.map((ch) => (
                <option key={ch.id} value={ch.id}>
                  {ch.name} ({ch.channel_type}) - {ch.status}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-300 mb-1">قالب الرسالة *</label>
            <textarea
              value={messageTemplate}
              onChange={(e) => setMessageTemplate(e.target.value)}
              rows={3}
              placeholder="مرحباً {{name}}، يسعدنا تقديم عرض خاص لك بمناسبة..."
              className="w-full bg-[#0d1422] border border-[#1e2c47] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
              required
            />
            <p className="text-[11px] text-gray-500 mt-1">
              المتغيرات المتاحة: <code className="text-indigo-400">{'{{name}}'}</code>,{' '}
              <code className="text-indigo-400">{'{{phone}}'}</code>,{' '}
              <code className="text-indigo-400">{'{{email}}'}</code>
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-300 mb-1">الوسوم المستهدفة (اختياري)</label>
            <input
              type="text"
              value={targetTags}
              onChange={(e) => setTargetTags(e.target.value)}
              placeholder="مثال: vip, active, retail (مفصولة بفاصلة)"
              className="w-full bg-[#0d1422] border border-[#1e2c47] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-300 mb-1">حجم الدفعة</label>
              <input
                type="number"
                value={batchSize}
                onChange={(e) => setBatchSize(Number(e.target.value))}
                min={1}
                max={500}
                className="w-full bg-[#0d1422] border border-[#1e2c47] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-300 mb-1">معدل الإرسال / دقيقة</label>
              <input
                type="number"
                value={rateLimit}
                onChange={(e) => setRateLimit(Number(e.target.value))}
                min={1}
                max={1000}
                className="w-full bg-[#0d1422] border border-[#1e2c47] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          <div className="flex items-center gap-2 pt-2">
            <input
              type="checkbox"
              id="requires_approval"
              checked={requiresApproval}
              onChange={(e) => setRequiresApproval(e.target.checked)}
              className="rounded bg-[#0d1422] border-[#1e2c47] text-indigo-600 focus:ring-0"
            />
            <label htmlFor="requires_approval" className="text-xs text-gray-300">
              تتطلب موافقة المالك قبل بدء الإرسال الفعلي
            </label>
          </div>

          <div className="flex items-center justify-end gap-2 pt-3 border-t border-[#1e2c47]">
            <button
              type="button"
              onClick={() => setIsCreateOpen(false)}
              className="px-4 py-2 rounded-lg bg-gray-800 text-gray-300 hover:text-white text-xs font-medium transition-colors"
            >
              إلغاء
            </button>
            <button
              type="submit"
              disabled={createLoading}
              className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors disabled:opacity-50 flex items-center gap-1.5"
            >
              {createLoading && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
              حفظ كمسودة
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal: Proactive Trigger */}
      <Modal
        isOpen={isProactiveOpen}
        onClose={() => setIsProactiveOpen(false)}
        title="إطلاق إشعار استباقي فوري لعميل"
      >
        <form onSubmit={handleProactiveTrigger} className="space-y-4">
          {proactiveError && (
            <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs flex items-center gap-2">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{proactiveError}</span>
            </div>
          )}
          {proactiveSuccess && (
            <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <span>{proactiveSuccess}</span>
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-gray-300 mb-1">نوع الإشعار *</label>
            <select
              value={proactiveType}
              onChange={(e) => setProactiveType(e.target.value as any)}
              className="w-full bg-[#0d1422] border border-[#1e2c47] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
            >
              <option value="appointment_reminder">تذكير بموعد قادم</option>
              <option value="service_followup">متابعة وطلب تقييم بعد الخدمة</option>
              <option value="inactivity_reengagement">إعادة تفاعل مع عميل غير نشط</option>
              <option value="custom">رسالة استباقية مخصصة</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-300 mb-1">معرف العميل (UUID) *</label>
            <input
              type="text"
              value={proactiveCustomerId}
              onChange={(e) => setProactiveCustomerId(e.target.value)}
              placeholder="أدخل معرف العميل"
              className="w-full bg-[#0d1422] border border-[#1e2c47] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
              required
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-300 mb-1">القناة المستخدمة *</label>
            <select
              value={proactiveChannelId}
              onChange={(e) => setProactiveChannelId(e.target.value)}
              className="w-full bg-[#0d1422] border border-[#1e2c47] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
              required
            >
              <option value="">اختر القناة...</option>
              {channels.map((ch) => (
                <option key={ch.id} value={ch.id}>
                  {ch.name} ({ch.channel_type})
                </option>
              ))}
            </select>
          </div>

          {proactiveType === 'appointment_reminder' && (
            <>
              <div>
                <label className="block text-xs font-medium text-gray-300 mb-1">اسم الخدمة / الموعد *</label>
                <input
                  type="text"
                  value={proactiveService}
                  onChange={(e) => setProactiveService(e.target.value)}
                  placeholder="مثال: جلسة استشارة تقنية"
                  className="w-full bg-[#0d1422] border border-[#1e2c47] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-300 mb-1">تاريخ ووقت الموعد *</label>
                <input
                  type="text"
                  value={proactiveTime}
                  onChange={(e) => setProactiveTime(e.target.value)}
                  placeholder="مثال: غداً الساعة 4:00 مساءً"
                  className="w-full bg-[#0d1422] border border-[#1e2c47] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>
            </>
          )}

          {proactiveType === 'service_followup' && (
            <>
              <div>
                <label className="block text-xs font-medium text-gray-300 mb-1">اسم الخدمة المكتملة *</label>
                <input
                  type="text"
                  value={proactiveService}
                  onChange={(e) => setProactiveService(e.target.value)}
                  placeholder="مثال: فحص الصيانة الدورية"
                  className="w-full bg-[#0d1422] border border-[#1e2c47] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-300 mb-1">رابط التقييم (اختياري)</label>
                <input
                  type="url"
                  value={proactiveFeedbackUrl}
                  onChange={(e) => setProactiveFeedbackUrl(e.target.value)}
                  placeholder="https://feedback.example.com/..."
                  className="w-full bg-[#0d1422] border border-[#1e2c47] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                />
              </div>
            </>
          )}

          {proactiveType === 'inactivity_reengagement' && (
            <div>
              <label className="block text-xs font-medium text-gray-300 mb-1">تفاصيل العرض الترويجي</label>
              <input
                type="text"
                value={proactiveOffer}
                onChange={(e) => setProactiveOffer(e.target.value)}
                placeholder="مثال: خصم 20% على طلبك القادم بكود WELCOME20"
                className="w-full bg-[#0d1422] border border-[#1e2c47] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
              />
            </div>
          )}

          {proactiveType === 'custom' && (
            <div>
              <label className="block text-xs font-medium text-gray-300 mb-1">نص الرسالة *</label>
              <textarea
                value={proactiveContent}
                onChange={(e) => setProactiveContent(e.target.value)}
                rows={3}
                placeholder="أدخل نص الرسالة المباشرة للعميل..."
                className="w-full bg-[#0d1422] border border-[#1e2c47] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                required
              />
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-3 border-t border-[#1e2c47]">
            <button
              type="button"
              onClick={() => setIsProactiveOpen(false)}
              className="px-4 py-2 rounded-lg bg-gray-800 text-gray-300 hover:text-white text-xs font-medium transition-colors"
            >
              إلغاء
            </button>
            <button
              type="submit"
              disabled={proactiveLoading}
              className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors disabled:opacity-50 flex items-center gap-1.5"
            >
              {proactiveLoading && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
              إرسال الإشعار
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
