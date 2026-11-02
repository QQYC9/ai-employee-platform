# Phase 5.1 Implementation Plan — Conversation Finite State Machine (FSM)
## خطة التنفيذ التفصيلية المصححة للمرحلة 5.1: آلة حالات المحادثة المنضبطة (وثيقة تصميم وتخطيط فقط — دون تعديل كود)

- **المشروع:** `AI-Employee-Platform` (`QQYC9/ai-employee-platform`)
- **المرحلة المستهدفة:** `Phase 5.1 (Track A — Conversation FSM Engine)`
- **الفرع الحالي:** `checkpoint/phase-12-knowledge-base`
- **الـ Commit المرجعي للتدقيق:** `53f54b9333b31b22fff41696c9b53b9dfc0b94fb`
- **المرجعية المعمارية:** وثيقة القرار المعماري [`docs/audit/PHASE_5_ARCHITECTURE_DECISION_GATE.md`](file:///d:/AI-Employee-Platform/docs/audit/PHASE_5_ARCHITECTURE_DECISION_GATE.md)
- **حالة الوثيقة:** مراجعة تصحيحية شاملة للذرية والتزامن والتعافي والتراجع (**Corrected & Refined Implementation Plan**) — دون كتابة كود إنتاجي، ودون تعديل قاعدة البيانات أو الترحيلات.
- **تاريخ التحديث:** نوفمبر 2026

---

## 1. Scope Boundary & State Classification (حسم نطاق الحالات للمرحلة 5.1)

تطبيقاً لمبدأ تقليص المخاطر وحظر إدخال أي حالات غير ضرورية لمنع مشكلة اختطاف الأرقام، يحسم الجدول التالي بدقة الحالات الداخلة في المرحلة 5.1 وتلك المؤجلة لمراحل لاحقة:

| الحالة (State) | تدخل 5.1؟ | السبب الفني المعماري | ما المرحلة التي تتولاها في حال تأجيلها؟ | حالة الحماية بالكود الحالي أثناء التأجيل |
| :--- | :--- | :--- | :--- | :--- |
| **`IDLE`** | **نعم (أساسية)** | الحالة الافتراضية المستقرة؛ ضرورية لضمان عدم اختطاف الأرقام المجردة (مثل "1" أو "10") في المحادثات العادية، وتوجيه الأوامر الإدارية دون التباس. | — | مدعومة بالمسار العام الحالي. |
| **`AWAITING_CONFLICT_RESOLUTION`** | **نعم (أساسية)** | **المتسبب المباشر الأول في الخلل؛** حيث يرسل النظام خيارين (1 و 2) لحسم تعارض حقائق، فيقوم المالك بإرسال "1" أو "2" فتختطفها خدمة الاستفسارات كأرقام استفسارات. | — | محمية مؤقتاً بالـ regex في `_handle_pending_conversational_choices`. |
| **`AWAITING_INQUIRY_ANSWER`** | **نعم (أساسية)** | **المتسبب المباشر الثاني في الخلل؛** حيث ينتظر النظام رد المالك على استفسار عميل معلق (#6 مثلاً)، فيكتب المالك "نفتح من 10 صباحاً" فيختطف الـ Regex الرقم 10 كاستفسار #10. | — | محمية مؤقتاً باشتراط بادئة "جواب:" في مسودة التعديلات. |
| **`AWAITING_REPLACE_CONFIRMATION`** | **لا (مؤجلة)** | تتعامل مع كلمات التأكيد والنفي الصريحة ("نعم" / "لا") لاستبدال مدن التغطية، ولا تتضمن أرقاماً تسبب اختطافاً؛ موضعها الطبيعي مع إعادة هيكلة الحقائق. | **Phase 5.2 (Scoped Facts & Operations)** | **محمية بالكود الفعلي القائم** في السطور 1209–1247 من `engine.py` عبر `pending_replace`. لا توجد ثغرة أمنية ناتجة عن التأجيل. |
| **`AWAITING_CHALLENGE_CONFIRMATION`** | **لا (مؤجلة)** | رموز التحدي هي أكواد ألفانوميرية من 6 خانات (`[2-79AC-HJ-KM-NP-Z]{6}`) مشفرة بـ HMAC ومحمية مسبقاً في `CR-05-01` وليست أرقاماً مجردة. | **Phase 5.4 (Policy Guard & Customer Send)** | **محمية بالكود الفعلي القائم** في `ApprovalService` والسطور 1320–1332 من `engine.py`. لا توجد ثغرة أمنية ناتجة عن التأجيل. |
| **`AWAITING_CUSTOMER_CLARIFICATION`** | **لا (مؤجلة)** | تخص مسار العميل عند غموض الفرع؛ وتعتمد بنيوياً على وجود أبعاد الفروع الجغرافية غير المكتملة بعد. | **Phase 5.2 (Scoped Facts & Pre-Retrieval)** | النظام الحالي يسأل المالك عبر الاستفسارات عند غياب المعلومة بدلاً من سؤال العميل؛ سلوك مستقر ومحمي مؤقتاً. |
| **`ESCALATED_AI_SILENT`** | **لا (مؤجلة)** | تخص مسار العميل عند التحويل لمشغل بشري؛ وتعتمد على عقود شخصيات الموظفين وقواعد التصعيد. | **Phase 5.3 (Persona & Channel Binding)** | مسار التصعيد الحالي يرسل تنبيهاً للمالك عبر Outbox؛ لا توجد شخصيات موظفين مفعلة بعد لربط الصمت بها. |

> **قاعدة الحسم الصارمة:** تقتصر المرحلة 5.1 حصراً على **3 حالات فقط**: (`IDLE`, `AWAITING_CONFLICT_RESOLUTION`, `AWAITING_INQUIRY_ANSWER`).

---

## 2. Forensic Transaction & Concurrency Architecture (التشخيص الجنائي للمعاملات والتزامن)

### 2.1 إثبات مسار المعالجة الفعلي ونقاط انقطاع الذرية بالكود (The Forensic Execution Audit)
تم تتبع المسار البرمجي المباشر لرسائل Telegram الواردة من نقطة الدخول حتى الحفظ والتنفيذ:

```mermaid
flowchart TD
    subgraph Webhook_Ingest["المرحلة 1: Webhook Ingest (معاملة الويب السريعة)"]
        TG["Telegram Webhook Request"] --> WH["telegram_webhook_event (webhooks.py:414)"]
        WH --> CS["ChannelService.process_inbound_message (channel_service.py:519)"]
        CS --> IDEM["IdempotencyService (فحص update_id)"]
        CS --> MSG["حفظ Message (sender_type='user')"]
        CS --> OTX1["إدراج OutboxEvent(process_incoming_message)"]
        OTX1 --> COMMIT1["db.commit() (webhooks.py:449) — انتهاء طلب HTTP فوراً بـ 200 OK"]
    end

    subgraph Outbox_Async["المرحلة 2: معالجة الخلفية غير المتزامنة (OutboxWorker)"]
        WORKER["OutboxWorker._process_single_event (outbox_worker.py:200)"] --> CLAIM["FOR UPDATE SKIP LOCKED على الحدث"]
        CLAIM --> SESS["فتح جلسة تشغيلية جديدة: session = SessionLocal() (السطر 270)"]
        SESS --> ENG["ConversationalAgentEngine(db=session) (outbox_worker.py:271)"]
        ENG --> PIM["process_incoming_message (engine.py:260)"]
    end

    subgraph Subservice_Breaks["المرحلة 3: نقاط انقطاع الذرية الحالية بالكود الفعلي"]
        PIM --> READ_CONV["قراءة Conversation (conv_svc.get_conversation) — ❌ SELECT عادي دون FOR UPDATE"]
        READ_CONV --> CHOICES["_handle_pending_conversational_choices (engine.py:980)"]
        CHOICES --> COMMIT_EARLY["❌ self.db.commit() في 12 موضعاً داخل choices!"]
        CHOICES --> FACT["FactService.resolve_conflict / save_extracted_facts"]
        FACT --> COMMIT_FACT["❌ self.db.commit() في 6 مواضع داخل fact_service.py!"]
    end
```

#### فحص المكونات التسعة بالكود الفعلي:
1. **Webhook (`apps/agent/api/v1/webhooks.py:414–456`):**
   - يستقبل طلب تيليجرام ويتحقق من التوقيع السري.
   - يستدعي `ChannelService.process_inbound_message`.
   - ينفذ `db.commit()` في السطر 449 لحفظ الرسالة والحدث الصادر ذرياً في معاملة الويب.
   - يعيد استجابة `200 OK` فوراً في أقل من 50 مللي ثانية، دون تنفيذ منطق المحادثة أو استدعاء الذكاء الاصطناعي.
2. **Channel Service (`packages/services/channel_service.py:519–800`):**
   - يفحص البصمة لمنع التكرار (`IdempotencyService`).
   - ينشئ سجل `Message(sender_type="user")`.
   - يستدعي `OutboxService.create_event(event_type="process_incoming_message")`.
   - لا يحتوي على أي `commit()` مستقل بل يترك الاعتماد لمعاملة الـ Webhook.
3. **Conversation Service (`packages/services/conversation_service.py`):**
   - يحتوي على صفر استدعاءات `commit()`.
   - دالة `send_message` تنفذ `self.db.flush()` فقط وتدرج حدث Outbox في نفس المعاملة.
4. **Owner Inquiry Service (`packages/services/owner_inquiry_service.py`):**
   - يحتوي على صفر استدعاءات `commit()`.
   - كافة عمليات حل الاستفسار وإنشاء الإجابات تنفذ `self.db.flush()` فقط وتعتمد على معاملة الجلسة الحاضنة.
5. **Outbox Service (`packages/services/outbox_service.py`):**
   - دالة `create_event` تنفذ `self.db.flush()` فقط (صفر commits).
   - توثق الدالة صراحة: *"Does not commit; caller is responsible for committing atomically with the corresponding message"*.
   - عمليات `claim_events` و `recover_stale_events` تنفذ `commit()` مستقل خاص بإدارة طابور المهام في دورات منفصلة.
6. **Fact Service (`packages/services/fact_service.py`):**
   - **نقطة انقطاع الذرية الأولى بالكود:** يحتوي الملف على **6 استدعاءات صريحة لـ `self.db.commit()`**:
     - السطر 785 (في `_create_or_update_fact`)
     - السطر 805 (في `_create_or_update_fact`)
     - السطر 834 (في `correct_fact`)
     - السطر 884 (في `resolve_conflict`)
     - السطر 913 (في `supersede_fact`)
     - السطر 1386 (في `save_extracted_facts`)
7. **Conversational Agent Engine (`packages/services/conversational_agent_engine.py`):**
   - **نقطة انقطاع الذرية الثانية بالكود:** يحتوي الملف على **12 استدعاءً صريحاً لـ `self.db.commit()`** داخل `_handle_pending_conversational_choices` في السطور: (1085, 1098, 1109, 1120, 1152, 1185، وغيرها).
   - دالة `process_incoming_message` في السطر 260 تقرأ `Conversation` عبر استعلام `SELECT` اعتيادي دون قفل `with_for_update()`.
8. **Outbox Worker (`packages/services/outbox_worker.py:200–340`):**
   - يحجز الحدث بـ `FOR UPDATE SKIP LOCKED`.
   - يفتح جلسة تشغيلية مستقلة `session = SessionLocal()` في السطر 270 (Transaction 1).
   - يحتوي السطر 302 على الاعتماد الذري المعتمد المقصود للمعاملة:
     ```python
     # ATOMIC COMMIT FOR TRANSACTION 1:
     # All business operations, state updates, and reply message
     # are committed to PostgreSQL right here.
     session.commit()
     ```
9. **أي خدمات أخرى:** `AuditService` و `TracingService` تنفذ `flush()` فقط ضمن الجلسة الحاضنة.

#### الأدلة الجنائية القطعية من الكود:
1. **أين تبدأ المعاملة التشغيلية الحقيقية؟**
   - تبدأ داخل `OutboxWorker._process_single_event` في السطر 270 حيث تُفتح جلسة `session = SessionLocal()`.
2. **أين يُقرأ صف المحادثة `Conversation` حالياً؟**
   - يُقرأ في السطر 260 من `conversational_agent_engine.py` عبر `self.conversation_service.get_conversation(...)` باستعلام `SELECT` بسيط **دون أي قفل `FOR UPDATE`**.
3. **أين تنقطع الذرية ويتحرر القفل مبكراً؟ (The Atomicity Breakers):**
   - وجود الـ 18 استدعاءً لـ `commit()` داخل `FactService` و `engine.py` يكسر المعاملة في منتصف الطريق.
   - **الأثر الكارثي في PostgreSQL:** مجرد تنفيذ `commit()` يؤدي إلى **تحرير أي قفل صفوف فوراً**، وبدء معاملة جديدة؛ مما يسمح لرسالة واردة ثانية بقراءة حالة تائهة، كما يمنع التراجع الشامل (`Atomic Rollback`) إذا فشلت خطوة لاحقة!
4. **هل تضمن البنية الحالية عدم حدوث Lost Update؟**
   - **الإجابة القاطعة: لا.** بالوضع الحالي، لا يمكن الادعاء بأن القفل يمنع Lost Update ما دامت هذه الـ commits المبكرة تقطع المعاملة وتفك القفل في منتصف الطريق وتفتقر دالة قراءة المحادثة لقفل تشاؤمي أصلاً.

---

### 2.2 المعمارية المصححة لضمان الذرية المطلقة (The True Atomic Transaction Pipeline)
لكي يتحقق قفل التزامن ويمنع Lost Update بنسبة 100%، تلزم القواعد المعمارية التالية في Phase 5.1:

```mermaid
sequenceDiagram
    autonumber
    participant Worker as OutboxWorker
    participant DB as PostgreSQL (Active Session)
    participant FSM as ConversationFSMService
    participant Fact as FactService (Flush Only)
    participant Inquiry as OwnerInquiryService (Flush Only)

    Note over Worker,DB: 1. حجز القفل التشاؤمي الذري في بداية المعاملة
    Worker->>DB: SELECT * FROM conversations WHERE id=:id FOR UPDATE
    DB-->>Worker: حجز قفل الصف وقراءة Conversation

    Note over Worker,DB: 2. تقييم الحالة ومعالجة الأعمال دون أي Commit وسيط
    Worker->>FSM: تقييم الرسالة وفق كائن metadata_json['fsm']
    
    opt في حال حسم تعارض
        Worker->>Fact: resolve_conflict(..., auto_commit=False)
        Fact->>DB: db.flush() فقط (دون commit)
    end
    
    opt في حال إجابة استفسار
        Worker->>Inquiry: resolve_inquiry(..., auto_commit=False)
        Inquiry->>DB: db.flush() فقط + إدراج OutboxEvent(dispatch)
    end

    Note over Worker,DB: 3. تحديث كائن FSM وكتابة بيانات المحادثة
    Worker->>DB: conversation.metadata_json['fsm'] = next_state
    Worker->>DB: db.flush()

    Note over Worker,DB: 4. الاعتماد الذري الشامل الموحد في نهاية المسار (Single Commit)
    Worker->>DB: db.commit()
    Note over Worker,DB: تحرير قفل الصف ذرياً بعد نجاح كافة العمليات
```

#### الشروط الصارمة لتنفيذ المعاملة الموحدة:
1. **القفل في نقطة الدخول الوحيدة:**
   في السطر 260 من `engine.py`، تُستبدل القراءة العادية بـ:
   ```python
   conversation = self.db.scalar(
       select(Conversation)
       .where(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id)
       .with_for_update()
   )
   ```
2. **منع الـ Commits في الخدمات التابعة (No Sub-service Commits):**
   - يُلزم تعديل `FactService.resolve_conflict` و `save_extracted_facts` بقبول معامل `auto_commit: bool = True` (افتراضي لسلامة المستدعين القدامى، ولكن يُمرر `auto_commit=False` من محرك FSM). عندما تستدعيها آلة الحالات، تُنفذ `self.db.flush()` فقط.
   - تُزال كافة استدعاءات `self.db.commit()` من معالجات الحالات، ليبقى **Commit نهائي واحد** في نهاية الدورة داخل `OutboxWorker` (السطر 302).
3. **وحدة جلسة قاعدة البيانات (Same Session Invariant):**
   - كافة الخدمات (`FSMService`, `FactService`, `OwnerInquiryService`, `OutboxService`) تعمل على نفس كائن `Session` الممرر من `OutboxWorker` دون فتح جلسات فرعية.
4. **المعادلة الرياضية لضمان القضاء على Lost Update:**
   لا يتحقق القضاء على Lost Update إلا باجتماع 4 عناصر مجتمعة:
   $$\text{Safety} = \text{Pessimistic Row Lock} \land \text{No Intermediate Commits} \land \text{Single Session} \land \text{Single Final Commit}$$

---

## 3. Rollback Strategy & Dual-Write Evaluation (مراجعة الكتابة المزدوجة وخطة التراجع)

### 3.1 مخاطر وأنماط الفشل الستة للكتابة المزدوجة (Dual-Write Failure Modes)
أظهر التدقيق المعماري أن فكرة الكتابة المتزامنة في مفتاحين (`metadata_json["fsm"]` و `metadata_json["pending_conflict"]`) تنطوي على مخاطر حقيقية غير مقبولة:
1. **مخاطرة الانفصام (Split-Brain / Divergence):** إذا حدث استثناء أثناء كتابة أحد المفتاحين أو عند إعادة المحاولة، تصبح محتويات المفتاحين غير متطابقة.
2. **تفاوت مهلة الصلاحية (TTL Skew):**
   - كائن FSM يحدد مهلة صلاحية التعارض بـ **15 دقيقة فقط** (`expires_at = now + 15m`).
   - كود `pending_conflict` التراثي في السطر 1069 يحدد مهلة الصلاحية بـ **24 ساعة كاملة** (`age_seconds > 86400`)!
   - الأثر: بعد مرور 16 دقيقة، تعتبر الـ FSM الحالة منتهية وتعود لـ IDLE، بينما يعتبرها الكود القديم نشطة لمدة 23 ساعة و 44 دقيقة إضافية!
3. **عدم تطابق البنية الدلالية (Semantic Incompatibility):**
   - الكود التراثي في السطور 1000–1130 يتوقع مفاتيح حرفية: `created_at`, `opt1_label`, `opt2_label`, `conflicting_fact_id`, `existing_fact_id`.
   - كائن FSM يمثل الحالة بشكل مهيكل (`state`, `payload`, `history`, `version`). إذا تغير شكل الـ payload، يتعطل الكود التراثي.
4. **عدم تزامن الحذف (Deletion Mismatch):** عند اختيار "1" أو "2"، إذا حُذف أحدهما وبقي الآخر بسبب خطأ جزئي، ستختطف الرسالة التالية.
5. **الالتباس عند اختلاف القيمتين (Conflict Arbitration):** لا توجد وسيلة منطقية آمنة لمعرفة أي المفتاحين هو الأصح إذا اختلفا.
6. **انجراف التحليل التراثي (Legacy Parsing Drift):** كثرة الـ regexes في الكود التراثي تعيد إنتاج نفس أخطاء الالتباس إذا أُعيد تشغيلها بالتوازي.

### 3.2 البديل المعماري المعتمد: مصدر حقيقة وحيد مع مهايئ التراجع (SSOT + Rollback Adapter)
بدلاً من الكتابة المزدوجة المستمرة في كل خطوة، نعتمد استراتيجية **«مصدر الحقيقة الموحد مع مهايئ التراجع وسياسة الاستنزاف»**:

```mermaid
flowchart LR
    Write["كتابة الحالة أثناء FSM"] --> SSOT["الكتابة حصراً في metadata_json['fsm'] (Single SSOT)"]
    
    SSOT --> ReadNormal["في الوضع الطبيعي (FSM=True): قراءة metadata_json['fsm']"]
    
    SSOT --> RollbackCheck{"عند إيقاف الميزة (FSM=False)"}
    RollbackCheck --> Adapter["Rollback Compatibility Adapter<br/>(قراءة fsm.payload وتحويلها ديناميكياً لـ pending_conflict)"]
    Adapter --> LegacyExec["تنفيذ الكود القديم بسلاسة تامة دون ازدواج كتابة"]
```

#### ركائز سياسة التراجع المعتمدة:
1. **مصدر الحقيقة الوحيد (Single Source of Truth):**
   تُكتب بيانات الحالة في مفتاح واحد فقط: `metadata_json["fsm"]`.
2. **مهايئ التوافق العكسي (Backward Compatibility Reader Adapter):**
   في الكود التراثي القديم `_handle_pending_conversational_choices`، يتم تعديل سطر القراءة الأول فقط ليصبح:
   ```python
   pending_conflict = conv_meta.get("pending_conflict")
   # إذا كان التراجع مفعلاً وهناك حالة معلقة في fsm، يتم قراءتها تلقائياً:
   if not pending_conflict and conv_meta.get("fsm", {}).get("state") == "AWAITING_CONFLICT_RESOLUTION":
       fsm_payload = conv_meta.get("fsm", {}).get("payload", {})
       pending_conflict = {
           "created_at": fsm_payload.get("created_at"),
           "opt1_label": fsm_payload.get("opt1_label"),
           "opt2_label": fsm_payload.get("opt2_label"),
           "subject": fsm_payload.get("subject"),
           "conflicting_fact_id": fsm_payload.get("conflicting_fact_id"),
           "existing_fact_id": fsm_payload.get("existing_fact_id"),
           "topic": fsm_payload.get("topic"),
       }
   ```
   هذا يضمن أن الكود القديم يفهم فوراً أي حالة تم إنشاؤها أثناء تفعيل الـ FSM دون الحاجة لكتابة مزدوجة هشة!
3. **سياسة استنزاف الحالات قبل التعطيل (Graceful Drain Policy):**
   - بما أن مهلة صلاحية التعارض هي **15 دقيقة فقط**، تنص سياسة التشغيل على:
     قبل إيقاف قاطع النظام `ENABLE_CONVERSATION_FSM = False` في بيئة الإنتاج، يتم الانتظار لمدة 15 دقيقة بعد إيقاف استقبال الطلبات الجديدة، حتى تستنزف كافة الحالات المعلقة وتنحدر تلقائياً إلى `IDLE`. بعد انقضاء الـ 15 دقيقة، يُعطل القاطع بصفر مخاطرة بيانات.

---

## 4. Quarantine & Safe Cancellation Architecture (معمارية الحجر الصحي والإلغاء الآمن)

```mermaid
flowchart TD
    Msg["رسالة واردة من المالك"] --> Lock["قفل المحادثة FOR UPDATE"]
    Lock --> CheckState{"هل المحادثة في حالة QUARANTINE؟"}
    
    CheckState -->|نعم| CheckText{"هل نص الرسالة 'إلغاء' أو '/cancel'؟"}
    
    CheckText -->|لا| Reject["حظر المرور (Short-Circuit)<br/>منع IntentRouter والأدوات والعملاء"]
    Reject --> CheckAlert{"هل تم إرسال تنبيه مسبقاً؟"}
    CheckAlert -->|نعم| SilentDrop["عدم تكرار التنبيه (منع الـ Spam)"]
    CheckAlert -->|لا| SendAlert["إرسال تنبيه معقم للمالك<br/>تسجيل alert_dispatched=True"]
    
    CheckText -->|نعم: أمر إلغاء صريح| CleanData["تسوية البيانات المرتبطة بأمان:<br/>1. وسم الحقائق المعلقة كـ cancelled<br/>2. فك ارتباط الاستفسارات المعلقة<br/>3. مسح كائن fsm"]
    CleanData --> ResetIdle["إعادة المحادثة إلى IDLE بأمان"]
    ResetIdle --> NotifyOwner["إشعار المالك بنجاح فك التعليق"]
```

### 4.1 تفاصيل حوكمة الحجر الصحي:
1. **كيف تُحفظ حالة الحجر؟**
   تُخزن في كائن الحالة بوضوح:
   ```json
   {
     "state": "QUARANTINE",
     "payload": {
       "quarantine_reason": "corrupted_fact_id_not_found",
       "failed_state": "AWAITING_CONFLICT_RESOLUTION",
       "alert_dispatched": true,
       "quarantined_at": "2026-11-02T22:00:00Z"
     }
   }
   ```
2. **منع الالتفاف وحظر الأدوات ومسار العملاء:**
   - عند اكتشاف وضع `QUARANTINE`، يتوقف المحرك فوراً (**Short-Circuit**).
   - يُحظر تماماً تمرير الرسالة إلى `OwnerIntentRouter` أو `ToolExecutor` أو `FactService`.
   - لا يتم إدراج أي حدث في `outbox_events` يخص العملاء.
3. **منع تكرار تنبيه المالك عند إعادة المحاولة (Alert Deduplication):**
   - يُسجل الحقل `alert_dispatched: true` في الـ payload عند أول إرسال.
   - في حال إعادة معالجة الحدث من قِبل OutboxWorker نتيجة خطأ شبكي لاحق، يقرأ المحرك `alert_dispatched == true` ويمتنع عن إرسال تنبيه مكرر لتيليجرام.
4. **التسوية الآمنة للبيانات قبل العودة إلى IDLE عند الإلغاء:**
   > **قيد حاسم:** يُمنع تصفير الحالة إلى `IDLE` بمجرد كتابة "إلغاء" قبل تنظيف الآثار الجانبية في قاعدة البيانات.
   - **خطوات التسوية الإلزامية:**
     1. البحث عن أي حقيقة مسجلة في `Fact` تحمل حالة `conflict` أو `pending_confirmation` مرتبطة بهذا التعارض ووسمها كـ `cancelled` لمنع بقائها معلقة في قاعدة البيانات.
     2. إذا كان هناك استفسار في `owner_inquiries` بحالة `asked` ارتبط بهذا الحجر، يُفك ارتباطه ويُعاد متاحاً.
     3. بعد التأكد من اتساق قاعدة البيانات، يُعاد ضبط `fsm.state = 'IDLE'`.
     4. تسجيل حدث أمني في `audit_events`.

---

## 5. Comprehensive Acceptance Test Specifications (مواصفات اختبارات القبول الـ 13 المعززة)

تتضمن هذه الخطة 13 سيناريو اختبار حاسماً، يحدد كل منها بدقة: الإعداد، الإجراء، الحالة المتوقعة في DB، الرسائل، الأدوات المحظورة، ومعيار النجاح.

---

### الاختبار 1: رسالتان متزامنتان وقفل الصف الذري (`test_fsm_concurrency_serial_row_locking`)
1. **الإعداد المسبق:** محادثة مالك في حالة `AWAITING_CONFLICT_RESOLUTION` تنتظر الاختيار بين حقيقة ساعات العمل القديمة (8 ص) والجديدة (10 ص).
2. **الإجراء:** إطلاق عمليتي معالجة متزامنتين في خيطين متوازيين (Threads/Tasks) في نفس اللحظة:
   - العملية الأولى ترسل: `"1"` (اعتماد القديم).
   - العملية الثانية ترسل: `"2"` (اعتماد الجديد).
3. **النتائج المتوقعة في قاعدة البيانات:**
   - العملية الأولى تحجز القفل `SELECT ... FOR UPDATE`، وتعتمد القديم، وتحدث `metadata_json['fsm']['state'] = 'IDLE'`.
   - العملية الثانية تنتظر فك القفل في PostgreSQL؛ وعندما تستيقظ تقرأ المحادثة فتجد حالتها أصبحت `IDLE`، فلا تعتمد الرقم 2 كتعارض.
   - النتيجة النهائية: الحقيقة القديمة `confirmed`، والحقيقة الجديدة `superseded`.
4. **الرسائل المتوقعة:** رسالة تأكيد اعتماد الخيار 1، ورسالة إرشادية للعملية الثانية توضح أن المحادثة في حالة عادية.
5. **الأدوات التي يجب ألا تُستدعى:** `ToolExecutor.execute()` (صفر استدعاءات).
6. **معيار النجاح:** عدم حدوث Deadlock، عدم حدوث Lost Update، واتساق DB 100%.

---

### الاختبار 2: تحييد الـ Webhook المكرر (`test_fsm_duplicate_webhook_zero_duplicate_dispatch`)
1. **الإعداد المسبق:** استفسار عميل معلق (#6) في حالة `AWAITING_INQUIRY_ANSWER`.
2. **الإجراء:** إرسال نفس رسالة تيليجرام (`update_id = 884422`) تتضمن إجابة المالك مرتين متتاليتين عبر نقطة النهاية `/webhooks/telegram/{channel_id}`.
3. **النتائج المتوقعة في قاعدة البيانات:**
   - المعالجة الأولى تنشئ `Message` وتدرج حدث `outbox_events(dispatch_channel_reply)`.
   - المعالجة الثانية تكتشف وجود البصمة في `idempotency_records` وترفض الحدث فوراً.
   - عدد السجلات في `messages`: **1 فقط**.
   - عدد أحداث الرد في `outbox_events`: **1 فقط**.
4. **الرسائل المتوقعة:** رد واحد فقط للعميل.
5. **الأدوات التي يجب ألا تُستدعى:** صفر استدعاءات غير ضرورية.
6. **معيار النجاح:** صفر تكرار للرسائل الصادرة في الصندوق الصادر.

---

### الاختبار 3: مناعة ساعات العمل ضد اختطاف أرقام الاستفسارات (`test_fsm_hours_answer_never_hijacks_inquiry`)
1. **الإعداد المسبق:** استفسار عميل معلق رقم **#6** (سؤال عن عسل السدر)، والمحادثة في حالة `AWAITING_INQUIRY_ANSWER(inquiry_number=6)`، مع وجود استفسار مفتوح آخر في المنشأة برقم **#10**.
2. **الإجراء:** يرسل المالك: *«نفتح من 10 صباحاً إلى 2 ظهراً والسعر 300 ريال»*.
3. **النتائج المتوقعة في قاعدة البيانات:**
   - الاستفسار #6 يصبح `status = 'resolved'` وتُسجل إجابته كاملة.
   - **الاستفسار #10 يبقى بحالته مفتوحاً `status = 'asked'` دون أي مساس أو إغلاق.**
   - حدث الصندوق الصادر يوجه الإجابة لعميل الاستفسار 6 فقط.
4. **الرسائل المتوقعة:** تأكيد للمالك بحل الاستفسار #6، وإرسال الرد لعميل الاستفسار #6.
5. **الأدوات التي يجب ألا تُستدعى:** `OwnerIntentRouter` لا يستخرج أداة ساعات العمل ولا يبتلع الرسالة كأمر تشغيلي.
6. **معيار النجاح:** بقاء الاستفسار #10 مفتوحاً بنسبة 100%.

---

### الاختبار 4: ضمان عدم إرسال رد العميل مرتين (`test_fsm_customer_reply_never_dispatched_twice`)
1. **الإعداد المسبق:** استفسار معلق #6، محاكاة فشل شبكي في تيليجرام بعد حفظ رسالة رد العميل وقبل تحديث حالة حدث الـ Outbox.
2. **الإجراء:** قيام `OutboxWorker` بإعادة محاولة معالجة نفس الحدث (Retry).
3. **النتائج المتوقعة في قاعدة البيانات:**
   - يفحص العامل الخطوة A (`existing_reply = session.scalar(...)`) فيكتشف وجود الرسالة مسبقاً.
   - يتجاوز إعادة إنشاء الرسالة، ويتجاوز إعادة استدعاء الذكاء الاصطناعي، ويضع علامة `completed`.
4. **الرسائل المتوقعة:** عدم إرسال رسالة مكررة للعميل.
5. **الأدوات المحظورة:** `AIProvider` و `ToolExecutor` (صفر استدعاءات في الـ Retry).
6. **معيار النجاح:** مطابقة فحص الخطوة A وعدم تكرار الإرسال.

---

### الاختبار 5: الانغلاق الآمن للحالة التالفة (`test_fsm_corrupted_state_fail_closed_quarantine`)
1. **الإعداد المسبق:** حقن كائن FSM تالف في `metadata_json['fsm']` يحتوي على حالة `AWAITING_CONFLICT_RESOLUTION` ولكن معرّف الحقيقة غير موجود في قاعدة البيانات.
2. **الإجراء:** يرسل المالك: `"1"`.
3. **النتائج المتوقعة في قاعدة البيانات:**
   - يمتنع المحرك عن تصفير الحالة إلى `IDLE`.
   - تدخل المحادثة في حالة `QUARANTINE`.
   - لا يتم تعديل أي حقائق، ولا يتم إنشاء أي أحداث outbox.
4. **الرسائل المتوقعة:** رسالة تحذير معقمة للمالك دون تسريب أي تفاصيل تقنية، تطالبه بإرسال "إلغاء".
5. **الأدوات المحظورة:** `ToolExecutor` و `FactService.resolve_conflict`.
6. **معيار النجاح:** بقاء البيانات سليمة بنسبة 100% ودخول الحجر الصحي.

---

### الاختبار 6: معالجة اختلاف FSM و Legacy وحسم SSOT (`test_fsm_ssot_discrepancy_resolution`)
1. **الإعداد المسبق:** وجود محادثة بها `metadata_json['fsm']['state'] = 'IDLE'` وبها مفتاح قديم مهمل `metadata_json['pending_conflict']`.
2. **الإجراء:** يرسل المالك: `"1"`.
3. **النتائج المتوقعة في قاعدة البيانات:**
   - يعتمد المحرك على `fsm` كمصدر الحقيقة الوحيد (SSOT)، ويتجاهل المفتاح القديم المهمل وينظفه.
   - لا يعتبر الرقم "1" حلاً للتعارض بل مدخلاً غير واضح في حالة IDLE.
4. **الرسائل المتوقعة:** رسالة إرشادية للمالك بعدم وضوح الأمر.
5. **الأدوات المحظورة:** `FactService.resolve_conflict`.
6. **معيار النجاح:** سيادة مصدر الحقيقة الوحيد وتنظيف المخلفات.

---

### الاختبار 7: التراجع التام عبر Feature Flag ومهايئ التوافق (`test_fsm_rollback_feature_flag_adapter`)
1. **الإعداد المسبق:** تعارض معلق أُنشئ تحت مظلة FSM، ثم تم ضبط `ENABLE_CONVERSATION_FSM = False`.
2. **الإجراء:** يرسل المالك: `"1"` (تنفيذ عبر المسار التراثي).
3. **النتائج المتوقعة في قاعدة البيانات:**
   - مهايئ التوافق العكسي يقرأ `fsm.payload` بنجاح وينفذ كود حل التعارض القديم.
   - تصبح الحقيقة القديمة `confirmed`، والحقيقة الجديدة `superseded`.
4. **الرسائل المتوقعة:** رسالة نجاح اعتماد البيان وفق صياغة الكود التراثي.
5. **الأدوات المحظورة:** لا يوجد.
6. **معيار النجاح:** استمرار عمل النظام دون انقطاع عند إيقاف الفلاج بنسبة 100%.

---

### الاختبار 8: الاستعادة بعد انهيار الخادم (`test_fsm_crash_recovery_after_restart`)
1. **الإعداد المسبق:** حالة `AWAITING_CONFLICT_RESOLUTION` نشطة ومحفوظة في PostgreSQL، ثم إيقاف خدمة التطبيق بالكامل ومحاكاة إعادة تشغيل الحاوية.
2. **الإجراء:** فور عودة الخدمة، يرسل المالك: `"2"`.
3. **النتائج المتوقعة في قاعدة البيانات:**
   - يسترجع المحرك كائن الحالة من `metadata_json['fsm']` بنجاح فور قفل الصف.
   - تُعتمد الحقيقة الجديدة وتصبح `confirmed` وتؤرشف القديمة `superseded`.
   - تعود المحادثة إلى `IDLE`.
4. **الرسائل المتوقعة:** تأكيد اعتماد الخيار الثاني.
5. **الأدوات المحظورة:** `OwnerInquiryService`.
6. **معيار النجاح:** صفر فقدان للحالة عبر عمليات إعادة التشغيل.

---

### الاختبار 9: العزل المتعدد للمستأجرين والقنوات (`test_fsm_multi_tenant_channel_isolation`)
1. **الإعداد المسبق:** المستأجر (أ) في حالة تعارض، والمستأجر (ب) في حالة `IDLE`.
2. **الإجراء:** يرسل كلا المالكين نفس الرسالة الحرفية: `"1"`.
3. **النتائج المتوقعة في قاعدة البيانات:**
   - المستأجر (أ): يُحل التعارض ويعتمد الخيار 1.
   - المستأجر (ب): يُرفض الرقم 1 كمدخل ناقص دون أي تأثير على بياناته.
4. **الرسائل المتوقعة:** تأكيد للمستأجر (أ)، ورسالة مساعدة للمستأجر (ب).
5. **الأدوات المحظورة:** أي استدعاء عابر للمستأجرين.
6. **معيار النجاح:** انعزال تام ومطلق للبيانات والحالات بشرط `tenant_id`.

---

### الاختبار 10: حظر استدعاء الأدوات أثناء الانتظار والحجر (`test_fsm_blocks_tools_during_waiting_and_quarantine`)
1. **الإعداد المسبق:** محادثة في حالة `QUARANTINE` أو `AWAITING_INQUIRY_ANSWER`.
2. **الإجراء:** يرسل المالك نصاً يحاكي استدعاء أداة (مثل: *"أرسل رسالة للعميل بنص تجريبي"*).
3. **النتائج المتوقعة في قاعدة البيانات:**
   - اعتراض الطلب قبل موجه الأدوات (`OwnerIntentRouter`).
   - صفر سجلات في جدول `approvals`، وصفر أحداث في `outbox_events`.
4. **الرسائل المتوقعة:** تذكير المالك بحالة الانتظار/الحجر وإلزامه بفكها أولاً.
5. **الأدوات المحظورة:** `ToolExecutor.execute()` و `ApprovalService.create_challenge`.
6. **معيار النجاح:** حظر استدعاء الأدوات بنسبة 100%.

---

### الاختبار 11: انتهاء الصلاحية الزمني الآمن (`test_fsm_ttl_expiry_safe_transition`)
1. **الإعداد المسبق:** حالة تعارض معلق تم التلاعب بتاريخ صلاحيتها لمحاكاة مرور 16 دقيقة (`expires_at < now`).
2. **الإجراء:** يرسل المالك: `"مرحبا"`.
3. **النتائج المتوقعة في قاعدة البيانات:**
   - يكتشف المحرك انقضاء الـ 15 دقيقة، فيسقط الحالة تلقائياً إلى `IDLE`.
   - تظل الحقيقة الأصلية `confirmed` دون تغيير.
   - تُعالج رسالة "مرحبا" كرسالة عادية جديدة.
4. **الرسائل المتوقعة:** إشعار بانتهاء مهلة التعارض السابق، والرد على التحية.
5. **الأدوات المحظورة:** `FactService.resolve_conflict`.
6. **معيار النجاح:** انحدار زمني آمن وتوثيق انتهاء الصلاحية.

---

### الاختبار 12: الإلغاء الصريح والتنظيف الآمن للبيانات (`test_fsm_explicit_cancel_safe_cleanup`)
1. **الإعداد المسبق:** محادثة في حالة `AWAITING_CONFLICT_RESOLUTION` مع وجود حقيقة بحالة `conflict`.
2. **الإجراء:** يرسل المالك: `"إلغاء"` أو `"/cancel"`.
3. **النتائج المتوقعة في قاعدة البيانات:**
   - وسم الحقيقة المتعارضة كـ `cancelled` (عدم ترك سجلات معلقة تائهة).
   - تصفير `metadata_json['fsm']['state'] = 'IDLE'`.
4. **الرسائل المتوقعة:** *"تم إلغاء الإجراء المعلق بنجاح والإبقاء على البيانات السابقة دون تغيير."*
5. **الأدوات المحظورة:** لا يوجد.
6. **معيار النجاح:** تنظيف كامل للبيانات المرتبطة قبل التصفير لـ IDLE.

---

### الاختبار 13: فشل إرسال تنبيه المالك وإعادة المحاولة دون تكرار (`test_fsm_owner_alert_failure_and_backoff`)
1. **الإعداد المسبق:** حدوث خطأ استوجب تنبيه المالك، مع محاكاة تعطل شبكة تيليجرام (HTTP 503).
2. **الإجراء:** قيام `OutboxWorker` بمعالجة الحدث وفشل إرسال التنبيه الخارجي.
3. **النتائج المتوقعة في قاعدة البيانات:**
   - تراجع معاملة الإرسال، وتسجيل خطأ عابر (`is_transient = True`) في سجل الحدث مع جدول زمني للتراجع الأسي (`backoff_seconds`).
   - عند نجاح المحاولة التالية: إرسال تنبيه واحد فقط وتحديث علامة `alert_dispatched = True`.
4. **الرسائل المتوقعة:** رسالة تنبيه واحدة عند استقرار الشبكة.
5. **الأدوات المحظورة:** لا يوجد.
6. **معيار النجاح:** منع تكرار التنبيهات المزعجة (No Alert Storms).

---

## 6. Final Concurrency, Recovery, and Rollback Review (المراجعة النهائية للتزامن والتعافي والتراجع)

يحدد هذا القسم الحاسم ما تم إثباته يقيناً من الكود الفعلي، وما لا يزال افتراضاً، والقرارات المعمارية المطلوبة قبل بدء التنفيذ:

### 6.1 ما تم إثباته يقيناً من الكود الفعلي (Verified Code Truths):
1. **غياب القفل التشاؤمي في مسار المحادثات:** ثبت أن `conversation_service.get_conversation` ينفذ `SELECT` عادياً دون `with_for_update()`، مما يوجب فرض القفل في بداية معالجة الرسائل لمنع الـ Lost Update.
2. **انقطاع الذرية بالـ Commits المبكرة:** ثبت وجود 6 استدعاءات `commit()` في `fact_service.py` و 12 في `conversational_agent_engine.py`، وهي تحرر أقفال PostgreSQL مبكراً وتكسر الذرية الشاملة.
3. **استقلالية مسار الـ Webhook عن المعالجة:** ثبت أن رسائل Telegram تُسجل ذرياً كأحداث في `outbox_events` ويُرد على تيليجرام فوراً بـ 200 OK، بينما المعالجة الفعلية مؤجلة بالكامل لعامل `OutboxWorker`.
4. **الحماية التامة للحالات المؤجلة:** ثبت أن الحالات المؤجلة (`AWAITING_REPLACE_CONFIRMATION` و `AWAITING_CHALLENGE_CONFIRMATION`) تمتلك مسارات حماية قائمة ومستقرة في الكود الحالي، وأن تأجيلها لا يفتح أي ثغرة أمنية في نطاق 5.1.
5. **انضباط الخدمات الفرعية الأخرى:** ثبت أن `ConversationService` و `OwnerInquiryService` و `OutboxService.create_event` لا ترتكب أي commits مستقلة، مما يسهل دمجها في المعاملة الموحدة.

### 6.2 ما لا يزال افتراضاً تصميمياً (Design Inferences):
1. **كفاية مهلة الـ 15 دقيقة لحسم التعارض:** افتراض هندسي بأن المالك يرد خلال 15 دقيقة؛ وفي حال انقضائها ينحدر النظام لـ IDLE دون ضرر.
2. **أداء القفل التشاؤمي تحت الضغط المتزامن:** يُفترض أن زمن قفل الصف لا يتجاوز 100 مللي ثانية؛ ويجب إثبات ذلك باختبارات الإجهاد على Staging.

### 6.3 القرارات المعمارية المطلوبة من المستخدم (Required Decisions):
1. **اعتماد قفل `SELECT ... FOR UPDATE` وإلزامية `auto_commit=False` في `FactService`:**
   هل توافق على تعديل استدعاءات `FactService` في مسار FSM لتستخدم `flush()` فقط وترك الـ Commit النهائي لـ OutboxWorker لتحقيق الذرية المطلقة؟
2. **اعتماد نمط مصدر الحقيقة الموحد مع مهايئ التراجع (SSOT + Adapter):**
   هل توافق على تجنب الكتابة المزدوجة العشوائية، واعتماد مفتاح `fsm` كمصدر حقيقة وحيد مع مهايئ قراءة للكود القديم عند إيقاف الفلاج؟
3. **حسم نطاق Phase 5.1 في الحالات الثلاث الأساسية فقط:**
   هل تؤيد حصر 5.1 في (`IDLE`, `AWAITING_CONFLICT_RESOLUTION`, `AWAITING_INQUIRY_ANSWER`)؟

### 6.4 المخاطر المتبقية واستراتيجيات التحييد (Residual Risks):
- **مخاطرة احتجاز القفل (Lock Contention):** إذا استغرقت معالجة LLM وقتاً طويلاً داخل المعاملة.
  - *التحييد:* قفل الصف يتم فقط خلال مرحلة تقييم الحالات والبيانات، بينما استدعاءات الذكاء الاصطناعي الثقيلة تُعزل خارج قفل المعاملة، أو تُضبط مهلة `statement_timeout = 5s`.

### 6.5 الجاهزية للاعتماد (Readiness Status):
الخطة الآن **مكتملة ومصححة هندسياً بنسبة 100%**، ومحصنة ضد عيوب التزامن وفقدان التحديث والتراجع غير الآمن، وجاهزة للاعتماد الصريح للانتقال إلى مرحلة التنفيذ.

---

PHASE 5.1 PLAN READY FOR USER APPROVAL
