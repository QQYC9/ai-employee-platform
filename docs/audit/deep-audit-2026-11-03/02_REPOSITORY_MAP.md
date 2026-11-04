# الخريطة الهندسية والمعمارية لمستودع AI-Employee-Platform
## 02_REPOSITORY_MAP.md

- **تاريخ التوثيق:** 2026-11-03T02:46:00+03:00
- **الفرع الحالي:** `checkpoint/phase-12-knowledge-base` (Commit: `8c28bc2`)
- **نطاق الفحص:** التطبيقات، الحزم، الخدمات، النماذج، ومسارات التشغيل.

---

## 1. شجرة المكونات وتوزيع المسؤوليات المعمارية

```text
D:\AI-Employee-Platform\
├── apps/
│   ├── agent/                 # FastAPI REST API Backend (/api/v1)
│   │   ├── main.py            # نقطة البداية، تسجيل الـ Routers، Middleware عزل المستأجرين
│   │   ├── api/router.py      # الموجه الرئيسي لجميع نقاط النهاية
│   │   └── api/v1/            # 28 موجه API متخصص (Agents, Tasks, Memory, Channels, Campaigns...)
│   ├── tenant-dashboard/      # بوابة صاحب العمل / المستأجر (React 18 + Vite 5 + TS + Tailwind)
│   └── admin-dashboard/       # بوابة المشرف العام على المنصة (SuperAdmin Portal)
├── packages/
│   ├── models/                # 52 نموذج علائقي (SQLAlchemy 2.0 ORM: domain.py, tenant.py)
│   ├── auth/                  # إدارة هويات JWT وعزل سياق المستأجر (TenantContext)
│   ├── core/                  # التهيئة المركزية، قاعدة البيانات، وتشفير الأسرار (AES-256-GCM)
│   ├── services/              # 48 خدمة للأعمال (المحرك التحاوري، الـ FSM، الـ Outbox، الحملات...)
│   ├── connectors/            # بوابات القنوات الخارجية (Telegram, WhatsApp Cloud, Email, Webhook)
│   ├── memory/                # استخراج وتخزين وتطهير الذاكرة المؤسسية والكيانات
│   ├── context/               # محرك تجميع وحقن السياق الديناميكي لنماذج الذكاء الاصطناعي
│   ├── tools/                 # سجل الأدوات التنفيذية وفحص الصلاحيات وتنفيذها في Sandbox
│   ├── self_development/     # محرك التطوير الذاتي وتوليد المهارات الديناميكية
│   └── ai_providers/          # موفرات النماذج التوليدية (Gemini, OpenRouter, Mock, ResilientProvider)
├── infrastructure/
│   ├── migrations/            # 23 ملف ترحيل Alembic
│   └── caddy/                 # Reverse Proxy والتوجيه الآمن
└── tests/                     # 115 ملف اختبار تكاملي ووحدوي
```

---

## 2. جدول الكيانات والنماذج الرئيسية (Core Domain Entities)

| الكيان (Entity) | الملف المصدري ورقم السطر | الوظيفة الهندسية ومجال البيانات | علاقات العزل والتكامل |
| :--- | :--- | :--- | :--- |
| **`Tenant`** | `packages/models/tenant.py:10` | تمثيل المنشأة/النشاط التجاري المعزول | الكيان الأب لكافة الموارد |
| **`User`** | `packages/models/domain.py:11` | مستخدمو النظام (المالك، المشرف، الموظف) | يرتبط بـ `tenant_id` و `role` |
| **`Agent`** | `packages/models/domain.py:103` | الوكيل الرقمي المعين للمنشأة | يملك صلاحيات وقنوات وأدوار |
| **`EmployeePersona`** | `packages/models/domain.py:47` | الشخصية الوظيفية وسلوك الوكيل | اسم الموظف، هويته، ونبرة صوته |
| **`Conversation`** | `packages/models/domain.py:1031` | جلسة المحادثة بين العميل والوكيل | ترتبط بـ `customer_id` و `channel_id` |
| **`Message`** | `packages/models/domain.py:1098` | الرسائل الفردية (نص، اتجاه، حالة) | `received`, `sent`, `failed` |
| **`Fact`** | `packages/models/domain.py:803` | الحقائق المؤسسية المستخلصة | جدول الحقائق (Key-Value) |
| **`Memory`** | `packages/models/domain.py:855` | ذكريات الكيانات والعملاء | لتخزين تفضيلات وسياق العميل |
| **`Task`** | `packages/models/domain.py:312` | المهام التشغيلية المجدولة والجارية | ترتبط بالوكيل والموافقة |
| **`Approval`** | `packages/models/domain.py:376` | الموافقات البشرية المطلوبة للإجراءات | `PENDING`, `APPROVED`, `REJECTED` |
| **`ActionPolicy`** | `packages/models/domain.py:447` | سياسات الأفعال وتحديد الحساسية | تحدد ما إذا كان الإجراء يحتاج موافقة |
| **`OutboxEvent`** | `packages/models/domain.py:1519` | سجلات التسليم المضمون للرسائل | نمط Transactional Outbox |
| **`Campaign`** | `packages/models/domain.py:2208` | حملات التواصل الترويجية والتذكيرية | رسائل جماعية للجمهور المستهدف |
| **`OwnerInquiry`** | `packages/models/domain.py:2449` | استفسارات الوكيل الموجهة لصاحب العمل | أسئلة لملء الفراغات المعرفية |

---

## 3. خرائط التدفق الشاملة (End-to-End Traces)

### أ. تدفق الرسالة الواردة (Inbound Channel Webhook Trace)
```text
Telegram/WhatsApp Webhook 
  ──> POST /api/v1/webhooks/{channel_type}/{channel_id}
  ──> apps/agent/api/v1/webhooks.py
  ──> ChannelService.get_channel_with_secrets (فك التشفير AES-GCM)
  ──> ConversationService.get_or_create_conversation (Scoped to Tenant)
  ──> تسجيل Message(status='received')
  ──> ConversationalAgentEngine.process_message / ConversationFSMService
  ──> ContextRetriever (جلب الـ Facts والـ Persona)
  ──> ResilientProvider (استدعاء Gemini / OpenRouter)
  ──> تسجيل Message(status='sent') + كتابة OutboxEvent (في نفس المعاملة DB Transaction)
  ──> OutboxWorker (خلفي: SELECT FOR UPDATE SKIP LOCKED)
  ──> ChannelService.dispatch_outbox_event (إرسال HTTP متين لـ Telegram API)
  ──> تحديث OutboxEvent(status='dispatched')
```

### ب. تدفق مهام الموافقات البشرية (Human-in-the-Loop Trace)
```text
طلب إجراء حساس من الوكيل 
  ──> ActionPolicyService.evaluate_action(tenant_id, action_name, payload)
  ──> اكتشاف أن الإجراء يتطلب موافقة المالك
  ──> ApprovalService.create_approval(...)
  ──> إنشاء OwnerInquiry وإرسال إشعار للمالك عبر OutboxWorker
  ──> المالك يضغط "موافق" أو "رفض" عبر لوحة التحكم أو رابط التحقق
  ──> ApprovalService.decide_approval(approval_id, decision)
  ──> TaskExecutionService.execute_task(...)
```
