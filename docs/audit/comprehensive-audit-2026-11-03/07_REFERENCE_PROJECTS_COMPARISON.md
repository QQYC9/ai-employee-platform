# 07_REFERENCE_PROJECTS_COMPARISON.md — مصفوفة المقارنة المعمارية المنهجية بالأدلة البرمجية

- **تاريخ التوثيق والاعتماد:** 2026-11-03T03:15:00+03:00
- **نطاق المقارنة:** منصة AI-Employee-Platform الحالية مقابل المشاريع المرجعية السبعة المفحوصة فعلياً على القرص.
- **الحالات المعتمدة:**
  - **[مثبتة بالكود]:** تم فحص الكود المصدري وتأكيد وجود الميزة وتتبع مسارها البرمجي.
  - **[مثبتة بالتوثيق فقط]:** مذكورة في الوثائق دون وجود كود تنفيذي حقيقي يدعمها.
  - **[جزئية]:** موجودة بشكل أولي أو إسعافي وغير مكتملة معمارياً.
  - **[غير موجودة]:** غير متوفرة في المشروع إطلاقاً.
  - **[لم يتم التحقق منها]:** لم تفحص لعدم توفر بيئة اختبار ملائمة.

---

## 1. المصفوفة المعمارية المقارنة الشاملة

| المعيار المعماري (`Criterion`) | منصتنا الحالية (`AI-Employee`) | `LangGraph` | `Memento-Skills` | `RagLeap Core` | `Microsoft AF` | `Dify` | `n8n` | `OpenAI Agents` |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Agent Runtime** | [جزئية] Regex صلب + Fallback LLM | [مثبتة بالكود] Pregel StateGraph | [مثبتة بالكود] UV Sandbox Execution | [مثبتة بالكود] Autonomy Agent Loop | [مثبتة بالكود] SupportsAgentRun Middleware | [مثبتة بالكود] FunctionCallAgentRunner | [مثبتة بالكود] Node Execution Engine | [مثبتة بالكود] AgentRunner & Turn Loop |
| **Durable Execution & Checkpointing** | [غير موجودة] Enum في FSM فقط | [مثبتة بالكود] Postgres Checkpointer ذري | [جزئية] JSON Timings & State | [جزئية] Autonomy Pending Table | [مثبتة بالكود] CheckpointStorage & Pregel | [غير موجودة] تعتمد على Redis Streams | [مثبتة بالكود] Workflow Execution Database | [جزئية] In-memory RunState |
| **Memory Architecture** | [جزئية] 8 رسائل مبتورة تعسفياً | [مثبتة بالكود] State Channels & Checkpoints | [غير موجودة] مخصصة للمهارات | [مثبتة بالكود] Multi-session Context & Facts | [مثبتة بالكود] Compaction & Session Store | [مثبتة بالكود] Hybrid RAG & Vector DB | [جزئية] Static Data per workflow | [مثبتة بالكود] Handoff Nesting & Wrappers |
| **Skills Dynamic Learning** | [غير موجودة] أكواد Python محقونة يدوياً | [غير موجودة] لا توجد دورة تعلم | [مثبتة بالكود] 10-step Eval, Grader, Analyzer | [جزئية] Skill reflection | [مثبتة بالكود] Progressive SKILL.md Provider | [غير موجودة] أدوات مبرمجة مسبقاً | [غير موجودة] عقد ثابتة | [غير موجودة] أدوات ثابتة |
| **Tool Execution & Function Calling** | [غير موجودة] محظورة على النموذج قطعيًا | [مثبتة بالكود] ToolNode & Schema Binding | [مثبتة بالكود] Python CLI in Sandbox | [مثبتة بالكود] Sandboxed Tool Registry | [مثبتة بالكود] FunctionInvocationLayer & Pydantic | [مثبتة بالكود] ToolEngine & Dynamic Invocation | [مثبتة بالكود] Node Connector Execution | [مثبتة بالكود] FunctionToolBatchExecutor |
| **Multi-Tenancy Isolation** | [مثبتة بالكود] عزل تام بـ tenant_id في 54 جدولاً | [غير موجودة] إطار عمل أحادي (Library) | [غير موجودة] بيئة فردية للباحث | [جزئية] Directory per agent | [غير موجودة] إطار عمل برمجي | [مثبتة بالكود] Workspaces & Tenant IDs | [مثبتة بالكود] Multi-user Enterprise Edition | [غير موجودة] إطار عمل برمجي |
| **Human-in-the-Loop & Approvals** | [مثبتة بالكود] Anti-hijack ApprovalService | [مثبتة بالكود] Dynamic interrupt() & resume | [غير موجودة] مؤتمتة بالكامل للتقييم | [مثبتة بالكود] Telegram YES/NO via action_id | [مثبتة بالكود] ToolApprovalMiddleware & Modes | [غير موجودة] لا توجد مقاطعة تفاعلية | [مثبتة بالكود] Wait Node & Webhook Resume | [مثبتة بالكود] ToolApprovalItem & RunState |
| **Observability & Guardian Line** | [جزئية] جداول رصد متفرقة بلا أب روحي | [مثبتة بالكود] LangSmith Tracing Hooks | [مثبتة بالكود] Timing & Grading JSON logs | [مثبتة بالكود] Daily Observability Report | [مثبتة بالكود] OpenTelemetry Layers | [مثبتة بالكود] TraceManager & Thought Queue | [مثبتة بالكود] Execution Lifecycle Hooks | [مثبتة بالكود] Span & RunHooks |
| **Security & Injection Defense** | [مثبتة بالكود] AES-256-GCM للأسرار | [غير موجودة] تعتمد على كود المطور | [مثبتة بالكود] SandboxAuditHook & uv limits | [مثبتة بالكود] Taint Tracking on external tools | [مثبتة بالكود] Information Flow Control & IFC | [مثبتة بالكود] Landlock Linux Isolation | [مثبتة بالكود] Auth Redaction & Sanitization | [مثبتة بالكود] Multi-tier Tool Guardrails |
| **Legal License & Commercial Freedom** | ملكية خاصة بالمنصة | **MIT License** (حرية تجارية كاملة) | **Apache 2.0** (حرية تجارية كاملة) | **MIT License** (حرية تجارية كاملة) | **MIT License** (حرية تجارية كاملة) | **Dify License** (قيود تجارية للـ SaaS) | **Sustainable Use** (قيود تجارية للـ SaaS) | **MIT License** (حرية تجارية كاملة) |

---

## 2. تحليل الأنماط المعمارية المناسبة وغير المناسبة لمنصتنا

### أ. الأنماط التي يجب تبنيها وتضمينها فوراً:
1. **نمط `StateGraph` مع `Postgres Checkpointer` (مستوحى من LangGraph):**
   - أفضل نمط عالمي مثبت بالكود لإدارة الحالات المعقدة، والمهام متعددة الخطوات، والتنفيذ المستمر دون فقدان الذاكرة.
   - يوفر حفظاً ذرياً في جداول `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` المتوافقة مع معمارية PostgreSQL 17 الحالية لدينا.
2. **نمط تقييم وتطوير المهارات المزدوج (مستوحى من Memento-Skills):**
   - آلية التشغيل المزدوج (With-skill vs Baseline)، والمصحح الصارم (`grader.md`)، والمحلل الموضوعي (`analyzer.md`)، والتدريب المعزول عبر `uv`.
   - هذا يمنحنا القدرة البرمجية على تطبيق البنود 21 و 22 و 24 في رؤيتنا (التطور المهني المستمر والتجربة العملية قبل التفعيل).
3. **نمط الاستقلالية وحوكمة الميزانية وتتبع التلوث (مستوحى من RagLeap Core):**
   - أوضاع الاستقلالية الصريحة الثلاثة (`off`, `semi`, `full`)، والخفض التلقائي للأدوار الحساسة، وتتبع تلوث البيانات (`tainted = True`) لمنع تسريب بيانات المستأجرين، وتقرير الرصد اليومي الذي يغذي "الأب الروحي".
4. **نمط ضغط الذاكرة الدلالي وحماية المعاملات (مستوحى من Microsoft Agent Framework):**
   - معمارية `_compaction.py` التي تلخص المحادثات القديمة دلالياً دون بتر قسري وتحتفظ بسجل الأدوات.
   - فحص مكافحة التلاعب بالمعاملات بعد الموافقة (`_FunctionArgumentsChangedAfterApproval`).
5. **نمط تسليم المهام بين الوكلاء وحواجز الحماية (مستوحى من OpenAI Agents SDK):**
   - معمارية الـ `Handoffs` التي تحول تسليم المهام إلى أدوات مفهومة للنموذج، وحواجز الحماية للمدخلات والمخرجات (`Input/Output Guardrails`).
6. **منع تجويع اتصالات قاعدة البيانات (مستوحى من Dify):**
   - إغلاق وتحرير معاملات قاعدة البيانات (`session.commit(); session.close()`) قبل استدعاء النموذج اللغوي لضمان عدم استنفاد Connection Pool.

### ب. الأنماط التي يجب تجنبها قطعيًا:
1. **الاعتماد على إطار عمل خارجي كامل كصندوق أسود مغلق:**
   - لا يجوز استبدال محركنا بـ Dify أو n8n بالكامل؛ لأن تراخيصها القانونية تقيد الاستخدام كـ SaaS تجاري منافس، وبنيتها لا تدعم عزل المستأجرين الـ 54 جدولاً الخاص بمنصتنا.
2. **الاستمرار في نمط شجرة الـ Regex الصلبة ومصادرة الذكاء الاصطناعي:**
   - أثبت الفحص الجنائي أن الترقيع داخل `conversational_agent_engine.py` هو طريق مسدود ميت ويجب استبداله جذرياً.
3. **بتر الذاكرة القسري العشوائي (Context Starvation):**
   - تجنب وضع قيود تعسفية مثل 8 رسائل أو 2,000 حرف، والاعتماد على خوارزميات التلخيص الدلالي وتخزين الحالة.
