# فهرس الأدلة البرمجية القابلة للتحقق (Evidence Index)
## 04_EVIDENCE_INDEX.md

- **تاريخ التوثيق:** 2026-11-03T02:32:00+03:00
- **المعايير:** كل دليل يربط المرجع، الـ commit/version، المسار الدقيق، أرقام الأسطر/الرموز، وما يثبته هندسياً.

---

## 1. أدلة منصة AI-Employee-Platform (Local Platform Evidence)

| معرف الدليل | المكون | المسار الدقيق | الرمز / السطر | ما يثبته هندسياً |
| :--- | :--- | :--- | :--- | :--- |
| **EVID-001** | محرك المحادثة الحالي | `packages/services/conversational_agent_engine.py` | L219 `def process_message` | تنفيذ المحادثة عبر تسلسل متصل داخل دالة واحدة طويلة تعتمد على فحص نصوص وقواعد بدلاً من آلة حالة صلبة ومستقلة، مما يسبب تشتت التفاعل. |
| **EVID-002** | العامل الخلفي للرسائل | `packages/services/outbox_worker.py` | L90 `class OutboxWorker` | الاعتماد على نمط Transactional Outbox وحجز الأحداث لمنع تكرار الإرسال وضمان تسليم رسائل القنوات بنجاح عند الأعطال. |
| **EVID-003** | استخراج وتخزين الحقائق | `packages/services/fact_service.py` | `class FactService` | تخزين حقائق النشاط بشكل سطحي (Key-Value في جدول `facts`) دون ربطها بتاريخ صلاحية أو تصنيف تراكمي أو دلالي، مما يحد من تراكم المعرفة لسنة وأكثر. |
| **EVID-004** | عزل المستأجرين | `packages/auth/tenant_context.py` | `get_tenant_context` | إنفاذ عزل المستأجرين على مستوى الـ Context عبر فك توكن JWT واستخراج `tenant_id`. |
| **EVID-005** | تشفير الأسرار | `packages/core/crypto.py` | `SecretsEncryptionService` | تشفير الـ Bot Tokens وحسابات التكامل باستخدام AES-256-GCM قبل حفظها في قاعدة البيانات. |
| **EVID-006** | مسار التحاور المحدث | `packages/services/conversation_fsm_service.py` | `class ConversationFSMService` | محاولة حديثة لإدخال آلة حالة محدودة للمحادثة لكنها لا تزال تفتقر إلى Persistent Checkpointing عبر الجلسات الطويلة. |

---

## 2. أدلة المشاريع المرجعية الخارجية (Reference Projects Evidence)

| معرف الدليل | المشروع | الالتزام (Commit) | المسار والرمز | ما يثبته هندسياً |
| :--- | :--- | :--- | :--- | :--- |
| **EVID-REF-01** | **LangGraph** | `4c52e12` | `libs/checkpoint-postgres/langgraph/checkpoint/postgres/aio.py:AsyncPostgresSaver` | إمكانية حفظ حالة المخطط التفاعلي بعد كل خطوة في PostgreSQL، ودعم ميزة `interrupt_before` للـ Human-in-the-Loop والاستئناف المتين. |
| **EVID-REF-02** | **Memento-Skills** | `ee9b9a4` | `daemon/skills/skill-creator/scripts/run_eval.py` & `agents/grader.md` | دورة تقييم مغلقة لا تعتمد أي مهارة جديدة للوكيل إلا بعد اختبارها في بيئة معزولة وقياس مؤشرات نجاحها رقمياً قبل النشر. |
| **EVID-REF-03** | **RagLeap Core** | `b9bb6fb` | `core/autonomy.py` & `core/budget.py` | حوكمة مستويات استقلالية الوكيل (Assistant vs Approval vs Autonomous) مع سقف استهلاك مالي للموارد لمنع استنزاف التوكنز أو تجاوز الصلاحيات. |
| **EVID-REF-04** | **RagLeap Core** | `b9bb6fb` | `core/observability.py` | وجود خط تتبع ورصد مركزي ومستقل يسجل كافة أحداث الوكلاء، وهو النموذج المثالي لتغذية "الأب الروحي" (Guardian Telemetry) بمعلومات جنائية موثوقة. |
| **EVID-REF-05** | **Dify** | `89cdc0c` | `api/core/rag/datasource/` & `retrieval/` | تطبيق البحث الهجين (Hybrid Search: Vector Embeddings + Full-Text Keyword BM25 + Re-ranking) لرفع دقة استرجاع السياق المؤسسي للوكلاء. |
| **EVID-REF-06** | **OpenAI Agents SDK** | `0dc4cf1` | `src/agents/guardrails.py` & `agent.py:handoff` | حواجز حماية إجبارية تُنفّذ قبل وبعد استدعاءات النماذج، وآلية رسمية لتسليم المهام بين عدة وكلاء متخصصين (Multi-Agent Handoff). |
| **EVID-REF-07** | **Microsoft Agent Framework**| `67ba500` | `declarative-agents/` | بطاقات تعريف الوكيل التعاقدية الشاملة التي تعرض قدراته وحدوده وصلاحياته بوضوح قبل تفعيله للمستأجر. |
