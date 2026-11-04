# خريطة مكونات المستودع وتدفقات التنفيذ والبيانات (AI-Employee-Platform)
## 02_REPO_COMPONENT_MAP.md

- **تاريخ التوثيق:** 2026-11-03T02:28:00+03:00
- **المستودع الرئيسي:** `D:\AI-Employee-Platform`
- **حالة الالتزام:** `8c28bc2 docs: update Phase 5.1 FSM implementation plan`

---

## 1. شجرة التطبيقات والحزم (Application & Package Tree)

```text
D:\AI-Employee-Platform\
├── apps/
│   ├── agent/                 # FastAPI REST API Backend (/api/v1)
│   │   ├── main.py            # نقطة البداية، تسجيل Routers، الـ Middleware وعزل المستأجرين
│   │   └── api/v1/            # 28 موجه API متخصص (Agents, Tasks, Memory, Channels, Campaigns...)
│   ├── tenant-dashboard/      # بوابة صاحب العمل / المستأجر (React 18 + Vite + TS + Tailwind)
│   └── admin-dashboard/       # بوابة المشرف العام على المنصة (SuperAdmin Portal)
├── packages/
│   ├── models/                # نماذج قاعدة البيانات (SQLAlchemy 2.0 ORM: tenant.py, domain.py)
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
│   ├── migrations/            # سلال الترحيلات (Alembic versions: 23 migration file)
│   └── caddy/                 # Reverse Proxy والتوجيه الآمن للشهادات
└── tests/                     # أكثر من 115 ملف اختبار تكاملي ووحدوي
```

---

## 2. حدود المسؤولية لكل حزمة (Package Responsibility Boundaries)

| الحزمة / المكون | نطاق المسؤولية التقنية | المكونات التي تعتمد عليها | الاعتماديات المباشرة |
| :--- | :--- | :--- | :--- |
| `packages.core` | إدارة دورة اتصال قاعدة البيانات (AsyncSession)، التكوين (`config.py`)، التشفير (`crypto.py`) | كافة الحزم والتطبيقات | SQLAlchemy, Pydantic, Cryptography |
| `packages.models` | تعريف المخططات العلائقية: `Tenant`, `User`, `Agent`, `Conversation`, `Message`, `Fact`, `Task`, `OutboxEvent` | `services`, `auth`, `agent` | `core`, SQLAlchemy 2.0 |
| `packages.auth` | فك وتشفير الـ JWT، استخراج `tenant_id`، التحقق من الصلاحيات والـ RBAC | `apps.agent`, `services` | `models`, PyJWT, FastAPI security |
| `packages.services` | عصب المنظومة: تنفيذ منطق الأعمال، تنسيق المهام، محرك الـ FSM، محرك المحادثة | `apps.agent`, `connectors` | `models`, `core`, `ai_providers` |
| `packages.connectors` | معالجة Webhooks الواردة من Telegram و WhatsApp، وتنسيق حمولة الإرسال | `services.channel_service` | `httpx`, `crypto`, `models` |
| `packages.memory` | استخراج الحقائق والكيانات من المحادثات وتخزينها في جدول `facts` | `services.conversational_agent_engine` | `models`, `ai_providers` |
| `packages.context` | استرجاع الحقائق وترتيبها حسب الأهمية وحقنها في الـ Prompt | `services.conversational_agent_engine` | `memory`, `models` |
| `packages.tools` | عقود الأدوات (`BaseTool`), فحص الصلاحيات، والتنفيذ المعزول | `services.agent_orchestrator` | `models`, `auth` |
| `packages.self_development` | التعلم الذاتي، واكتشاف الفجوات، وتوليد الأدوات الديناميكية | `services.capability_service` | `tools`, `models` |

---

## 3. تدفقات التنفيذ والبيانات الفعلية (End-to-End Traces)

### أ. تدفق الرسالة الواردة عبر القناة (Inbound Channel Message Flow)
1. **الاستقبال:** يدخل طلب HTTP Webhook من Telegram عبر `POST /api/v1/webhooks/telegram/{channel_id}` في `apps/agent/api/v1/webhooks.py`.
2. **التحقق والعزل:** يتم استدعاء `ChannelService.get_channel` واسترجاع القناة المشفرة مع التأكد من مطابقة `secret_token`.
3. **تسجيل المحادثة:** استدعاء `ConversationService.get_or_create_conversation` مع عزل `tenant_id`، ثم إنشاء سجل `Message` في حالة `received`.
4. **التوجيه إلى المحرك التحاوري:** يُرسل الطلب إلى `ConversationalAgentEngine.process_message` أو محرك الـ FSM المحدث `ConversationFSMService`.
5. **استرجاع السياق والذاكرة:** يقوم `ContextRetriever` بالبحث عن الحقائق المرتبطة بالمستأجر من جدول `facts`.
6. **توليد الرد:** استدعاء `ResilientProvider` عبر `AIProviderFactory` (النموذج الأساسي Gemini أو OpenRouter).
7. **إرسال الرد (Transactional Outbox):** يُمنع إرسال الرسالة إلى Telegram فوراً بالـ HTTP المتزامن؛ بل يتم كتابة سجل `OutboxEvent` في نفس المعاملة (Database Transaction) مع الرد.
8. **العامل الخلفي (OutboxWorker):** يقوم `OutboxWorker` بحجز الحدث باستخدام `SELECT ... FOR UPDATE SKIP LOCKED`، ثم يستدعي `ChannelService.dispatch_outbox_event` لإرسال الرسالة لـ Telegram عبر `TelegramConnector`، وتحديث حالة الحدث إلى `dispatched`.

### ب. تدفق المهام الممتدة والموافقات (Task Execution & Approvals Flow)
1. يطلب المستخدم مهمة إدارية أو ترويجية (مثل حملة تسويقية).
2. يتحقق `ActionPolicyService` من مستوى حساسية الإجراء ومستوى استقلالية الوكيل.
3. إذا تطلب الإجراء موافقة، يُنشئ `ApprovalService` سجلاً في `approvals` ويُولد رابطاً فريداً أو إشعاراً لمالك النشاط (`OwnerInquiry`).
4. عند موافقة المالك عبر لوحة التحكم أو تيليجرام، يتم تحديث `approval.status = APPROVED` وتفعيل العامل التنفيذي `TaskExecutionService`.

### ج. نقاط الفشل والاختناقات المعمارية المكتشفة (Bottlenecks & Failure Modes)
- **الاعتماد الكثيف على الـ Prompt الأحادي:** محرك المحادثة يحاول استيعاب الاستفسار، الذاكرة، والتصنيف في طلب LLM واحد دون آلة حالة صلبة، مما يسبب تذبذب الردود وتناقضها.
- **التشابك في `packages/services`:** احتواء المجلد على 48 خدمة متداخلة المسؤوليات تزيد من صعوبة تتبع دورة الحياة الشاملة بدون طبقة Orchestration موحدة (Workflow Graph).
- **غياب قناة الأب الروحي المنفصلة:** مسار إشعارات المالك الحالي (`owner_inquiry_service.py`) مدمج داخل نفس قناة المستأجر، مما يتعارض مع الرؤية التي تفرض وجود قناة تيليجرام خاصة ومنفصلة تماماً بالمؤسس/المنشئ.
