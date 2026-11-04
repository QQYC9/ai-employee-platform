# دفتر تفكيك وتحليل المشاريع المرجعية السبعة (Reference Projects Ledger)
## 03_REFERENCE_PROJECTS_LEDGER.md

- **تاريخ التوثيق والتحليل:** 2026-11-03T02:30:00+03:00
- **بيئة الفحص:** مجلد الأبحاث المعزول `D:\AI-Employee-Platform-Research`
- **المنهجية:** فحص الكود المصدري الأصلي محلياً، تثبيت الـ commit والترخيص، تفكيك الوحدات ومسارات التنفيذ، وربطها بالرؤية الشاملة لـ AI-Employee-Platform.

---

## 1. فهرس المشاريع المرجعية والنسخ المثبتة (Pinned Versions & Licensing)

| # | المشروع | المستودع الأصلي (Repository URL) | الالتزام المثبت (Commit SHA) | الترخيص القانوني (License) | التصنيف المعماري |
| :-: | :--- | :--- | :--- | :--- | :--- |
| **1** | **LangGraph** | `https://github.com/langchain-ai/langgraph.git` | `4c52e129eb1ab69a3da58b799f67929f77d81149` (v1.2.17) | **MIT** | State Machine & Workflow Orchestration |
| **2** | **Dify** | `https://github.com/langgenius/dify.git` | `89cdc0c7a9c78027d4e15112e420f6570ae783ab` | **Dify Open Source / Apache 2.0 (with restrictions)** | Multi-Tenant Enterprise Agent Platform |
| **3** | **Memento-Skills** | `https://github.com/Memento-Teams/Memento-Skills.git` | `ee9b9a45efd093d669c06fe318b4b1dceb246d19` | **Apache 2.0** | Skill Evolution, Self-Development & Eval Loops |
| **4** | **Microsoft Agent Framework** | `https://github.com/microsoft/agent-framework.git` | `67ba500ec1fd312606a5d585a42335cd8631e851` | **MIT** | Enterprise Declarative Agents & Tools Contracts |
| **5** | **n8n** | `https://github.com/n8n-io/n8n.git` | `9a489b65ed539a042e819012558cfc6985aab78d` | **Sustainable Use License / Enterprise (Fair Code)** | Event-Driven Business Automation & Connectors |
| **6** | **OpenAI Agents Python SDK** | `https://github.com/openai/openai-agents-python.git` | `0dc4cf152bff1f50bdc0e41f28808563406545b2` | **MIT** | Multi-Agent Handoffs, Guardrails & Tracing |
| **7** | **RagLeap Core** | `https://github.com/ragleap/ragleap-core.git` | `b9bb6fbc1f7c8ef0427cb817ffc495578ab0531b` (v0.6.2) | **MIT** | Enterprise Autonomous Agent Loop & Hybrid RAG |

---

## 2. التفكيك المعماري التفصيلي لكل مشروع (Deep Module Deconstruction)

---

### المشروع 1: LangGraph (LangChain AI)
- **Commit:** `4c52e12` | **License:** MIT
- **الملفات والموديولات المفحوصة:**
  - `libs/langgraph/langgraph/graph/state.py` (StateGraph)
  - `libs/checkpoint-postgres/langgraph/checkpoint/postgres/aio.py` (AsyncPostgresSaver)
  - `libs/langgraph/langgraph/prebuilt/tool_node.py` (ToolNode)
- **الفلسفة المعمارية:**
  - تمثيل دورة حياة المحادثة والمهام كـ **مخطط موجه حلقي (Cyclic State Graph)** بدلاً من الـ Chain الخطي.
  - الحفظ المتين للحالة (Durable Checkpointing): كل عقدة (Node) تنتج حالة (State update) تُحفظ ذرياً في جدول الـ checkpoints في PostgreSQL.
- **إدارة الحالة والـ Human-in-the-Loop:**
  - توفير ميزة `interrupt_before` و `interrupt_after`: يستطيع الوكيل التوقف قبل تنفيذ أداة حساسة، وتخزين الحالة كاملة، وانتظار موافقة بشرية، ثم استئناف التنفيذ من نفس النقطة تماماً (Time-Travel / Replay).
- **أسرار النجاح القابلة للتحقق:**
  - فصل تعريف المنطق عن محرك التخزين (Checkpointer Interface).
  - التزامن والتعامل مع حالات السباق (Optimistic Concurrency Control عبر حقل `checkpoint_id` و `version`).
- **ما يصلح لمنصتنا:**
  - **تبني نمط StateGraph مع AsyncPostgresSaver**: هذا يحل أزمة الـ FSM الحالية التي نعاني منها في المحرك التحاوري، ويمنع تذبذب الحالة أثناء انقطاع اتصال Telegram أو إعادة تشغيل الخادم.
- **ما لا يصلح أو يجب الحذر منه:**
  - عدم استيراد منظومة LangChain الضخمة والمليئة بالتجريدات الزائدة (Over-abstraction)؛ يمكن استخدام LangGraph النواة كـ dependency مستقلة ونظيفة، أو استعارة نمط الـ StateGraph مع PostgreSQL Checkpointing مباشرة.

---

### المشروع 2: Dify (LangGenius)
- **Commit:** `89cdc0c` | **License:** Dify Open Source License
- **الملفات والموديولات المفحوصة:**
  - `api/core/app/apps/agent_chat/` (Agent Chat Orchestrator)
  - `api/core/model_runtime/` (Model Abstraction & Fallback)
  - `api/core/rag/` (Hybrid Search, Chunking, Retrieval)
  - `api/models/` (Multi-tenant schema, App, Workflow, Message)
- **الفلسفة المعمارية:**
  - منصة سحابية كاملة متعددة المستأجرين (Workspaces / Tenants) لفصل التطبيقات، والبيانات، والوكلاء.
  - هيكلة المحادثة عبر DSL Workflow صريح يجمع بين الـ LLM وكتل المنطق البرمجي الصلب (Code Nodes, If/Else, Tool Invocations).
- **إدارة الذاكرة والمعرفة:**
  - الـ Knowledge Base مقسمة إلى Datasets و Documents مع تجزئة ذكية (Smart Chunking) وفهرسة متجهات مع البحث الدلالي والهجين (Hybrid Search: Vector + Keyword BM25 + Re-ranking).
- **أسرار النجاح:**
  - واجهات إدخال مرنة، وتتبع تفصيلي لاستهلاك التوكنز والمحاولات، وتجريد متين لمزودي الذكاء الاصطناعي (Model Runtime).
- **ما يصلح لمنصتنا:**
  - نمط **Hybrid Retrieval (Vector + Full-Text BM25)**: يحل مشكلة الذاكرة الحالية في منصتنا التي تعتمد على مطابقة بسيطة للحقائق.
  - نموذج الـ Workspace/Tenant Isolation في الجداول وقواعد البيانات.
- **القيود والمحاذير:**
  - ترخيص Dify يتضمن قيوداً على إعادة البيع كخدمة منافسة مباشرة (Commercial restrictions on multi-tenant SaaS embedding)؛ لذا لا يجوز نسخ كوده حرفياً، بل نستلهم التصميم المعماري (Design Pattern) ونبنيه بأكوادنا الخاصة تحت رخصة المنصة.

---

### المشروع 3: Memento-Skills (Memento Teams)
- **Commit:** `ee9b9a4` | **License:** Apache 2.0
- **الملفات والموديولات المفحوصة:**
  - `daemon/skills/skill-creator/` (Skill Creator, Agents, Graders, Comparators)
  - `daemon/skills/skill-creator/scripts/run_eval.py` (Evaluation loop)
  - `tools/registry.py` & `tools/atomics/` (Tool Dispatcher & Sandboxing)
  - `utils/event_bus.py` (Decoupled eventing)
- **الفلسفة المعمارية:**
  - **التطور المهني المستمر للوكيل عبر دورات تقييم مغلقة (Eval-Driven Skill Evolution)**.
  - لا يتم اعتماد أي مهارة أو أداة جديدة لمجرد أن الوكيل قرأ عنها؛ بل يمر عبر وكلاء فرعيين: `analyzer.md` (تحليل النقص) -> `comparator.md` (مقارنة الأداء السابق بالجديد) -> `grader.md` (تقييم الاختبارات بمعايير رقمية صارمة).
- **أسرار النجاح:**
  - فصل بيئة التقييم (Sandbox) عن بيئة التشغيل الفعلية.
  - إنشاء تقارير بصرية وتقييمات للمهارات بصيغة HTML (`eval_viewer/viewer.html`).
- **ما يصلح لمنصتنا:**
  - **هذا المشروع هو الترجمة الهندسية الدقيقة للبند 21 و 22 و 24 في رؤيتنا** (التطور المهني المستمر للوكلاء). سنعتمد معمارية الـ `analyzer` والـ `grader` ودورة التقييم المعزولة في بيئة الاختبار قبل اعتماد المهارات للإنتاج.

---

### المشروع 4: Microsoft Agent Framework (Semantic Kernel / AutoGen)
- **Commit:** `67ba500` | **License:** MIT
- **الملفات والموديولات المفحوصة:**
  - `python/packages/semantic-kernel/semantic_kernel/agents/`
  - `python/packages/semantic-kernel/semantic_kernel/functions/kernel_function_decorator.py`
  - `declarative-agents/` (Declarative YAML/JSON schema for agent capability definition)
- **الفلسفة المعمارية:**
  - تعريف الوكيل كملف إعلاني تعاقدي (Declarative Contract): الوكيل يعلن صراحة عن مهامه، أدواته المسموحة، قيود الحماية، ومصادر بياناته قبل التشغيل.
- **أسرار النجاح:**
  - عقود قوية للمدخلات والمخرجات (Type annotations & Pydantic validation).
  - إمكانية التنسيق بين عدة وكلاء عبر موجه أحداث مركزي.
- **ما يصلح لمنصتنا:**
  - **بنية بطاقة الوكيل قبل التفعيل (Agent Manifest)**: تحقيق البند 3 (ز) في رؤيتنا، حيث تعرض المنصة بوضوح كل ما يستطيع الوكيل فعله وما لا يستطيعه وصلاحياته قبل اعتماده.

---

### المشروع 5: n8n
- **Commit:** `9a489b6` | **License:** Sustainable Use License
- **الملفات والموديولات المفحوصة:**
  - `packages/core/src/WorkflowExecute.ts`
  - `packages/nodes-base/nodes/` (Connectors architecture, Telegram, WhatsApp, Webhooks)
- **الفلسفة المعمارية:**
  - محرك أتمتة أحداث مرن مبني على العقد التنفيذية (Node-based execution) مع معالجة استثنائية للـ Retries، والـ Exponential Backoff، والـ Webhook Triggering.
- **ما يصلح لمنصتنا:**
  - هندسة الـ Webhooks وإدارة الأخطاء في موصلات القنوات (Telegram / WhatsApp Connector Error Recovery)؛ تحصين الاتصال من انقطاع الشبكة ورفض التوكنز.

---

### المشروع 6: OpenAI Agents Python SDK
- **Commit:** `0dc4cf1` | **License:** MIT
- **الملفات والموديولات المفحوصة:**
  - `src/agents/agent.py` (Agent Lifecycle & Hand-offs)
  - `src/agents/guardrails.py` (Input & Output validation)
  - `src/agents/tracing.py` (Execution Traces)
- **الفلسفة المعمارية:**
  - **التسليم السلس بين الوكلاء (Agent Handoffs)**: بدلاً من وكيل واحد ضخم يقوم بكل شيء، يُسند الطلب إلى وكيل متخصص، وعند الحاجة يتم عمل `handoff` لوكيل آخر مع تمرير السياق الموثق.
  - حواجز الحماية (Guardrails): التحقق من المدخلات والمخرجات قبل وبعد كل استدعاء للنموذج لمنع تسريب البيانات أو الـ Prompt Injection.
- **ما يصلح لمنصتنا:**
  - نمط **Guardrails المدمج** لفصل الصلاحيات ومنع الوكيل من الهلوسة أو تجاوز الحدود (البند 14 في الرؤية).
  - نمط الـ Handoff بين وكلاء المنشأة الواحدة.

---

### المشروع 7: RagLeap Core
- **Commit:** `b9bb6fb` | **License:** MIT
- **الملفات والموديولات المفحوصة:**
  - `core/agent_loop.py` (The main autonomous decision loop)
  - `core/autonomy.py` (Autonomy levels and threshold checks)
  - `core/budget.py` (Token and cost budgeting guards)
  - `core/observability.py` (Structured telemetry and event sinks)
  - `core/proactive_triggers.py` (Scheduled triggers without human prompt)
- **الفلسفة المعمارية:**
  - بناء محرك عميل تشغيلي مستقل مع **تحكم حقيقي في مستويات الاستقلالية والميزانية (Autonomy & Budgeting)**.
  - الرصد المتواصل لكافة الأحداث عبر `observability.py`.
- **أسرار النجاح القابلة للتحقق:**
  - يحتوي على ملف `autonomy.py` يحدد مستويات صلاحية الإجراءات تماماً كما ورد في رؤيتنا: (مساعد، بموافقة، مستقل ضمن سقف ميزانية وأدوات محددة).
- **ما يصلح لمنصتنا:**
  - **هذا المكون هو الأساس التقني الأمثل لبناء "الأب الروحي" (Guardian Telemetry)** ونظام الاستقلالية المذكور في البنود 3(و)، 10، 11 في رؤيتنا.
