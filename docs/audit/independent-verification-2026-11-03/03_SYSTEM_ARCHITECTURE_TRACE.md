# 03_SYSTEM_ARCHITECTURE_TRACE.md — التتبع المعماري الحقيقي لمسارات التشغيل ونقاط الانتقال

- **تاريخ التوثيق والاعتماد:** 2026-11-03T03:35:00+03:00
- **نطاق الفحص:** تتبع مسار الرسالة الحقيقي من نقطة الدخول في الـ API وحتى وصول الرد للمستخدم، مع ربط كل خطوة بالملف الحقيقي، والكلاس، واسم الدالة بدقة.

---

## 1. مخطط التتبع المعماري للتدفق الحقيقي (End-to-End Execution Trace)

```mermaid
sequenceDiagram
    autonumber
    actor ExternalUser as العميل / المالك الخارجي
    participant Connector as Telegram / WhatsApp Webhook
    participant FastAPIRouter as apps/agent/api/v1/webhooks.py
    participant ChannelSvc as packages/services/channel_service.py
    participant IdemSvc as packages/services/idempotency_service.py
    participant Engine as packages/services/conversational_agent_engine.py
    participant IntentRouter as packages/services/owner_intent_router.py
    participant FactSvc as packages/services/fact_service.py
    participant ResilientAI as packages/ai_providers/resilient_provider.py
    participant OutboxSvc as packages/services/outbox_service.py
    participant OutboxDB as Database: outbox_events
    participant Worker as packages/services/outbox_worker.py
    participant NetDispatch as Channel Outbound API

    ExternalUser->>Connector: إرسال رسالة نصية ("أريد معرفة الأسعار")
    Connector->>FastAPIRouter: HTTP POST /api/v1/webhooks/telegram/{channel_id}
    
    rect rgb(240, 248, 255)
        note right of FastAPIRouter: 1. التحقق من التوقيع الرقمي والتأمين
        FastAPIRouter->>FastAPIRouter: التحقق من X-Telegram-Bot-Api-Secret-Token عبر hmac.compare_digest
    end

    FastAPIRouter->>ChannelSvc: handle_inbound_message(tenant_id, inbound)
    
    rect rgb(255, 250, 240)
        note right of ChannelSvc: 2. قفل التكرار ومكافحة الازدواج
        ChannelSvc->>IdemSvc: acquire_or_check(idem_key="telegram:<ext_id>")
        IdemSvc->>IdemSvc: SELECT FOR UPDATE على idempotency_records
    end

    ChannelSvc->>ChannelSvc: حفظ Message و Conversation في قاعدة البيانات
    ChannelSvc->>Engine: process_incoming_message(tenant_id, message, channel)

    rect rgb(255, 245, 245)
        note right of Engine: 3. فحص الهوية والاعتراض بالـ Regex
        alt إذا كان المرسل هو المالك (is_owner=True)
            Engine->>IntentRouter: process_owner_text(text) [1,082 سطراً من Regex]
        else إذا كان المرسل عميلاً (Customer Flow)
            Engine->>Engine: فحص طلب الكتالوج _detect_catalog_request (L608)
            Engine->>FactSvc: استرجاع الحقائق والتحقق من ساعات العمل
            Engine->>Engine: بتر التاريخ: max(1, min(history_limit, 8)) وقص الرسائل (L574-L605)
            Engine->>ResilientAI: generate_text(prompt, model="gemini-2.5-flash") [بدون أدوات]
            ResilientAI-->>Engine: الرد النصي الخام
            Engine->>Engine: تمرير الرد عبر _evaluate_reply_guardrails (L4026) وقص التحيات
        end
    end

    Engine->>OutboxSvc: create_event(event_type="send_channel_message", payload)
    OutboxSvc->>OutboxDB: INSERT INTO outbox_events (status="pending")
    OutboxSvc-->>ChannelSvc: تم إنشاء الحدث ذرياً
    ChannelSvc-->>FastAPIRouter: HTTP 200 OK (رسالة مقبولة)
    FastAPIRouter-->>Connector: HTTP 200 OK

    rect rgb(245, 255, 245)
        note over Worker,OutboxDB: 4. الحلقة الخلفية غير المتزامنة للموزع (Outbox Cycle)
        loop كل ثانية (Worker Loop)
            Worker->>OutboxSvc: claim_events(batch_size=10)
            OutboxSvc->>OutboxDB: SELECT FOR UPDATE SKIP LOCKED (L197)
            OutboxDB-->>Worker: حجز الحدث (status="processing", locked_at=now)
            Worker->>NetDispatch: HTTP POST https://api.telegram.org/bot.../sendMessage
            alt نجاح الإرسال (HTTP 200)
                Worker->>OutboxSvc: mark_completed(event.id)
                Worker->>OutboxDB: UPDATE outbox_events SET status="completed"
            else خطأ مؤقت (429 / 503)
                Worker->>OutboxSvc: mark_failed(event.id, delay=backoff, is_transient=True)
                Worker->>OutboxDB: إعادة الجدولة مع Exponential Backoff
            end
        end
    end

    NetDispatch-->>ExternalUser: استلام الرد النهائي على تطبيق Telegram
```

---

## 2. جدول المكونات والمسؤوليات البرمجية الدقيقة

| المرحلة | الملف المسؤول (`File Path`) | الكلاس / الدالة التنفيذية (`Class / Function`) | المسؤولية الميدانية |
| :--- | :--- | :--- | :--- |
| **استقبال وتوثيق Webhook** | `apps/agent/api/v1/webhooks.py` | `telegram_webhook` (L414) / `whatsapp_webhook_post` (L369) | استلام الـ Payload والتحقق الصارم من التوقيع الرقمي وSecret Token عبر `hmac.compare_digest`. |
| **قفل التكرار ومطابقة المستأجر** | `packages/services/channel_service.py` | `ChannelService.handle_inbound_message` (L528) | توليد مفتاح فريد `channel_type:external_id` وفحص جدول `idempotency_records` قبل أي معالجة. |
| **إدارة جلسة التحاور والتوجيه** | `packages/services/conversational_agent_engine.py` | `ConversationalAgentEngine.process_incoming_message` (L234) | التحقق من تصنيف المرسل (مالك vs عميل) وفحص حالة `conversation_fsm_service`. |
| **معالجة أوامر المالك** | `packages/services/owner_intent_router.py` | `OwnerIntentRouter.route_owner_intent` (L180) | مطابقة Regex لاستخراج أوامر المهام، والموافقات، والمنتجات، أو الاستفسارات المعلقة. |
| **استرجاع الحقائق والمعرفة** | `packages/services/fact_service.py` | `FactService.get_effective_facts` / `search_facts` | جلب ساعات العمل والفروع والسياسات عبر البحث الدلالي في جدول `facts`. |
| **توليد الرد بالذكاء الاصطناعي** | `packages/ai_providers/resilient_provider.py` | `ResilientProvider.generate_text` | استدعاء نماذج Gemini مع التراجع للنماذج البديلة دون تمرير أي واجهة استدعاء أدوات للنموذج. |
| **تسجيل الصادر الموثوق** | `packages/services/outbox_service.py` | `OutboxService.create_event` (L50) | كتابة سجل `OutboxEvent` داخل المعاملة الذرية لقاعدة البيانات. |
| **العامل الخلفي والتسليم الخارجي** | `packages/services/outbox_worker.py` | `OutboxWorker.process_event` (L155) | جلب الأحداث بـ `FOR UPDATE SKIP LOCKED` والإرسال عبر `ChannelConnector` وإدارة المحاولات والتراجع الأسي. |

---

## 3. نقاط الانتقال الحساسة ومخاطر الفشل المكتشفة

1. **فجوة استعلام الرسالة في `channel_service.py:543`:**
   - عند مطابقة سجل التكرار (`cached["message_id"]`)، يستعلم الكود عن الرسالة عبر `where(Message.id == UUID(cached["message_id"]))` **دون التحقق من `Message.tenant_id == tenant_id`**؛ مما يشكل ثغرة أمنية عند تلف الكاش.
2. **انقطاع شبكة القنوات الخارجية بعد الإرسال وقبل حفظ `mark_completed`:**
   - يثبت التتبع استحالة تحقيق Exactly-Once عبر HTTP، وأن المنصة تعتمد على At-least-once مع إعادة التحقق من حقل `delivery_status` في جدول الرسائل لمنع ازدواجية الإرسال.
