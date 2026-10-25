import React, { useState } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { Sparkles, Lock, AlertCircle, CheckCircle2, Loader2, ArrowLeft } from 'lucide-react';
import { authApi } from '../api/auth';

export const SetPasswordPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') || '';

  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!token.trim()) {
      setError('رمز التفعيل مفقود أو غير صالح. يرجى طلب رابط جديد من البوت.');
      return;
    }

    if (newPassword.length < 8) {
      setError('يجب أن تتكون كلمة المرور من 8 أحرف أو أكثر');
      return;
    }

    if (newPassword !== confirmPassword) {
      setError('كلمتا المرور غير متطابقتين');
      return;
    }

    setIsSubmitting(true);
    try {
      await authApi.resetPasswordWithToken(token.trim(), newPassword);
      setSuccess(true);
    } catch (err: any) {
      setError(err?.message || 'فشل تعيين كلمة المرور. قد يكون الرابط منتهي الصلاحية أو تم استخدامه مسبقاً.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#090d16] flex items-center justify-center p-4" dir="rtl">
      <div className="w-full max-w-md">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-tr from-emerald-600 to-teal-400 text-slate-950 font-bold shadow-xl shadow-emerald-950/60 mb-4">
            <Sparkles className="w-9 h-9" />
          </div>
          <h2 className="text-2xl font-black text-white tracking-tight">
            تعيين كلمة مرور الحساب
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            أهلاً بك! يرجى تعيين كلمة مرور قوية لتسجيل الدخول إلى لوحة تحكم منشأتك
          </p>
        </div>

        {/* Card */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/80 p-8 shadow-2xl backdrop-blur">
          {success ? (
            <div className="space-y-6 text-center">
              <div className="w-14 h-14 rounded-full bg-emerald-950/80 border border-emerald-800 text-emerald-400 flex items-center justify-center mx-auto">
                <CheckCircle2 className="w-8 h-8" />
              </div>
              <div className="space-y-2">
                <h3 className="text-lg font-bold text-white">تم تعيين كلمة المرور بنجاح!</h3>
                <p className="text-xs text-slate-400 leading-relaxed">
                  تم حفظ كلمة المرور المشفرة الخاصة بحسابك، ويمكنك الآن تسجيل الدخول مباشرة إلى لوحة تحكم المنشأة.
                </p>
              </div>
              <Link
                to="/login"
                className="inline-flex items-center justify-center gap-2 w-full py-3 px-4 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-400 text-slate-950 font-bold text-sm shadow-lg shadow-emerald-500/20 hover:opacity-95 transition"
              >
                <span>الانتقال لتسجيل الدخول</span>
                <ArrowLeft className="w-4 h-4" />
              </Link>
            </div>
          ) : (
            <>
              {error && (
                <div className="mb-6 flex items-start gap-3 rounded-xl border border-rose-900/60 bg-rose-950/40 p-4 text-rose-300 text-sm">
                  <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5 text-rose-400" />
                  <div className="leading-snug">{error}</div>
                </div>
              )}

              {!token.trim() && (
                <div className="mb-6 flex items-start gap-3 rounded-xl border border-amber-900/60 bg-amber-950/40 p-4 text-amber-300 text-xs">
                  <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5 text-amber-400" />
                  <div>
                    تنبيه: لم يتم تزويد رمز التفعيل في الرابط. تأكد من فتح الرابط الكامل المرسل إليك عبر تيليجرام.
                  </div>
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-5">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-2">
                    كلمة المرور الجديدة
                  </label>
                  <div className="relative">
                    <div className="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none text-slate-500">
                      <Lock className="w-5 h-5" />
                    </div>
                    <input
                      type="password"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      placeholder="•••••••••••• (8 أحرف على الأقل)"
                      required
                      minLength={8}
                      className="w-full rounded-xl border border-slate-800 bg-slate-950/70 py-3 pr-10 pl-4 text-sm text-white placeholder-slate-500 outline-none transition focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-2">
                    تأكيد كلمة المرور
                  </label>
                  <div className="relative">
                    <div className="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none text-slate-500">
                      <Lock className="w-5 h-5" />
                    </div>
                    <input
                      type="password"
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      placeholder="••••••••••••"
                      required
                      minLength={8}
                      className="w-full rounded-xl border border-slate-800 bg-slate-950/70 py-3 pr-10 pl-4 text-sm text-white placeholder-slate-500 outline-none transition focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
                    />
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={isSubmitting || !token.trim()}
                  className="w-full flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-400 py-3 px-4 font-bold text-sm text-slate-950 shadow-lg shadow-emerald-500/20 hover:opacity-95 transition disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="w-5 h-5 animate-spin" />
                      <span>جاري حفظ كلمة المرور...</span>
                    </>
                  ) : (
                    <span>تأكيد وحفظ كلمة المرور</span>
                  )}
                </button>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
