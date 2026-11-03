# 07_CHANNELS_WORKERS_AND_DELIVERY.md — التدقيق الجنائي للعمال والقنوات وموثوقية التسليم

- **تاريخ التدقيق والاعتماد:** 2026-11-03T03:48:00+03:00
- **الملفات المفحوصة في هذا النطاق:**
  1. `packages/services/outbox_worker.py` (1,243 سطراً)
  2. `packages/services/outbox_service.py` (370 سطراً)
  3. `packages/services/idempotency_service.py` (226 سطراً)
  4. `packages/connectors/telegram.py` (418 سطراً)
  5. `packages/connectors/whatsapp.py` (313 سطراً)
  6. `apps/agent/api/v1/webhooks.py` (456 سطراً)

---

## 1. محرك صندوق الصادر وحجز الأحداث (`OutboxWorker` & `OutboxService`)

### أ. استعلام حجز الأحداث ومنع التنافس (Concurrency Control)
- **الملف والسطر الفعلي:** `packages/services/outbox_service.py` (السطور L180–L205).
- **الاستعلام الدقيق:**
  ```python
  stmt = (
      select(OutboxEvent)
      .where(OutboxEvent.status == "pending", OutboxEvent.scheduled_at <= now)
      .order_by(OutboxEvent.scheduled_at.asc(), OutboxEvent.created_at.asc())
      .limit(batch_size)
  )
  if dialect_name == "postgresql":
      stmt = stmt.with_for_update(skip_locked=True)  # السطر 197
  claimed_rows = list(self.db.scalars(stmt).all())
  ```
- **تأكيد السطر:** `with_for_update(skip_locked=True)` مستدعاة حرفياً في **السطر L197** لحجز الأحداث، ومستدعاة أيضاً في **السطر L330** عند استعادة الأحداث الراكدة.
- **تأجير القفل (Lock Lease):** يتم تعيين `status = "processing"` مع مهلة قفل مدتها 300 ثانية (`lock_expires_at = now + 300s`) وتسجيل معرّف العامل `locked_by = worker_id` (السطور L209–L217).

---

### ب. سياسة إعادة المحاولة والتراجع الأسي (Exponential Backoff Formula)
- **المعادلة الرياضية في الكود:** `packages/services/outbox_worker.py` (السطور L148–L151):
  ```python
  delay = self.base_backoff_seconds * (self.backoff_factor ** max(0, attempt_count - 1))
  return min(delay, self.max_backoff_seconds)
  ```
  - الثوابت: `base_backoff_seconds = 2.0`، `backoff_factor = 2.0`، `max_backoff_seconds = 300.0`.
  - التسلسل الزمني للمحاولات: المحاولة 1 = 2 ثوانٍ، 2 = 4 ثوانٍ، 3 = 8 ثوانٍ، 4 = 16 ثانية، 5 = 32 ثانية، بحد أقصى 300 ثانية.

### ج. تصنيف الأخطاء (عابرة vs دائمة) والتحول لـ Dead-Letter
- **الأخطاء الدائمة (`is_transient = False`):**
  - استثناءات بايثون: `ValueError`, `KeyError`, `TypeError`, `AttributeError`.
  - نصوص الأخطاء: `"not found"`, `"forbidden"`, `"unauthorized"`, `"blocked"`, `"tampering"`.
  - الإجراء: التحول الفوري إلى `status = "failed"` وإلغاء إعادة المحاولة لتفادي استنزاف الموارد.
- **الأخطاء المؤقتة (`is_transient = True`):**
  - استثناءات الشبكة: `TimeoutError`, `IOError`, `OSError`, `AIProviderTimeoutError`.
  - نصوص الأخطاء: `"timeout"`, `"connection reset"`, `"rate limit"`, `"429"`, `"502"`, `"503"`.
  - الإجراء: إعادة الجدولة إلى `status = "pending"` مع وقت استحقاق `scheduled_at = now + delay`.
- **سقف المحاولات (Dead-Letter):** الحد الأقصى للمحاولات هو 5 محاولات (`max_attempts = 5` في `domain.py:1596`)؛ إذا تجاوز المحاولات، يتحول الحدث نهائياً إلى `status = "failed"` مع رسالة: `Max retry attempts (5) exceeded`.

---

### د. التعافي من الانهيار والسقوط المفاجئ (Crash Recovery)
- **الملف والسطر:** `packages/services/outbox_service.py` (السطور L307–L362):
  - في بداية كل دورة استطلاع، يستدعي العامل `recover_stale_events`.
  - يستعلم عن الأحداث العالقة في `status == "processing"` التي انتهت مهلة قفلها (`lock_expires_at <= now`).
  - يقفلها بـ `with_for_update(skip_locked=True)` ويعيدها فوراً إلى `status = "pending"` مع `scheduled_at = now` لإعادة معالجتها عبر عامل سليم.

---

### هـ. الحقيقة العلمية: استحالة الـ "Exactly-Once" واعتماد "At-Least-Once + Idempotent Fencing"
- **البرهان البرمجي والفيزيائي:**
  - في السطرين L384 و L408 من `outbox_worker.py`: يتم إرسال الرسالة عبر HTTP إلى تيليجرام أو واتساب، ثم يُستدعى `outbox_service.mark_completed(event_id)`.
  - إذا نجح خادم تيليجرام في إرسال الرسالة إلى هاتف العميل، ولكن انقطعت الشبكة قبل وصول رد الـ HTTP 200 إلى العامل، أو انهار الخادم قبل تنفيذ `session.commit()`:
    - لن يتم تسجيل الاكتمال في PostgreSQL.
    - بعد انتهاء مهلة القفل (300 ثانية)، سيستعيد العامل الساقط الحدث ويعيد إرساله مرة ثانية!
  - **الاستنتاج الحاسم:** لا يمكن هندسياً تحقيق "Exactly-Once" مع شبكات خارجية غير منسقة بـ 2PC (معضلة الجنرالين - Two Generals' Problem).
- **حواجز الحماية المدمجة (Idempotency Fencing):**
  1. **إعادة استخدام الرد المعتمد (L259–L281):** يفحص الكود وجود رد سابق معتمد لنفس `in_reply_to_message_id` ويعيد إرسال نفس النص دون استدعاء الذكاء الاصطناعي مجدداً.
  2. **فحص حالة التسليم (L333):** إذا كان حقل `delivery_status == "delivered"`، يُسجل الحدث كمكتمل فوراً دون إعادة الإرسال.

---

## 2. موصلات القنوات الرسمية (Connectors)

### أ. موصل تيليجرام (`packages/connectors/telegram.py`)
- **نقطة النهاية:** `POST https://api.telegram.org/bot<bot_token>/sendMessage` (L180).
- **التجزئة (Chunking):** يجزئ الرسائل الطويلة تلقائياً عند 4,000 حرف لتفادي رفض تيليجرام للرسائل فوق 4,096 حرفاً.
- **التحقق من الويب هوك:** يفحص ترويسة `X-Telegram-Bot-Api-Secret-Token` ويطابقها بـ `hmac.compare_digest` بالتوكن المشفر المسجل في قاعدة البيانات (L72).

### ب. موصل واتساب السحابي (`packages/connectors/whatsapp.py`)
- **نقطة النهاية:** `POST https://graph.facebook.com/v19.0/{phone_number_id}/messages` (L185).
- **التجزئة:** يجزئ الرسائل عند 4,000 حرف.
- **التحقق من الويب هوك:**
  - التحقق المبدئي (GET): فحص `hub.verify_token` ومطابقته وإرجاع `hub.challenge` (L66–L76).
  - التحقق من الرسائل (POST): التحقق من توقيع `X-Hub-Signature-256` عبر حساب HMAC-SHA256 باستخدام `app_secret` ومقارنته بـ `hmac.compare_digest` (L78–L102).

---

## 3. معمارية التكرار الوارد (Inbound Idempotency)

- **الجدول المركزي:** `idempotency_records` مع قيد فريد `uq_tenant_idempotency_key` على `(tenant_id, idempotency_key)` في `domain.py:572`.
- **المسار في `channel_service.py` (L530–L546):**
  - عند وصول رسالة، يتم توليد المفتاح: `idem_key = f"{channel_type}:{external_message_id}"`.
  - يستدعي `acquire_or_check` مع قفل الصف بـ `with_for_update()`.
  - إذا كانت معالجة مسبقاً، يرجع الرسالة المسجلة مباشرة دون إدخالها في دورة الذكاء الاصطناعي مجدداً.
