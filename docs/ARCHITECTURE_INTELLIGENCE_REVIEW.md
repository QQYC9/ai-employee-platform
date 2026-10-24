# AI Employee Platform — Architecture Intelligence Review
## الفحص المعماري الشامل، تحليل المشاريع المرجعية، ومصفوفة فجوات القدرات

> **التاريخ:** 24 أكتوبر 2026  
> **الصفة المعمارية:** Principal AI Systems Architect & Senior Software Engineer  
> **حالة الفرع:** `checkpoint/phase-12-knowledge-base`  
> **المستودع:** [AI-Employee-Platform](file:///d:/AI-Employee-Platform)  
> **المستند المعتمد:** [`docs/ARCHITECTURE_INTELLIGENCE_REVIEW.md`](file:///d:/AI-Employee-Platform/docs/ARCHITECTURE_INTELLIGENCE_REVIEW.md)  
> **نطاق المراجعة:** فحص الكود الحقيقي، تحليل 6 مشاريع وأطر مرجعية بالتفصيل، مصفوفة فجوات القدرات الـ 15، والتحسين الذاتي المستمر (Memento-Skills).

---

## 1. Executive Summary (الملخص التنفيذي)

تخوض منصة **AI Employee Platform** مرحلة معمارية حاسمة للانتقال من مجرد "محرك محادثة ونظام مهام مؤتمت" إلى **منصة موظفين رقميين مستقلين للأعمال والشركات متعددة المستأجرين (Multi-Tenant Enterprise Digital Employee Platform)**.

الرؤية المعمارية المعتمدة ترتكز على مبدأ موحد لا يقبل المساومة:

$$\mathbf{Shared\ Agent\ Engine\ +\ Tenant\text{-}Specific\ Business\ Brain,\ Memory,\ Policies,\ Credentials\ and\ Integrations}$$

### أبرز نتائج الفحص الميداني للكود الحقيقي:
1. **صلابة البنية التحتية الأساسية:** المنصة تمتلك بالفعل هيكلية متقدمة ومثبتة بـ **811 اختباراً آلياً (pytest)** تغطي عزل المستأجرين بنسبة 100%، ونمط الـ **Transactional Outbox (`OutboxEvent`)** مع قفل التنافسية `FOR UPDATE SKIP LOCKED`، والتشفير المصدق للأسرار `AES-256-GCM`، ونظام تدقيق أمني شامل (`AuditEvent`).
2. **ازدواجية محركات التخطيط والتنفيذ:** كشف الفحص عن وجود مسارين لتنفيذ المهام:
   - مسار أوركسترا المهام الموجه للأدوات: [`AgentOrchestrator`](file:///d:/AI-Employee-Platform/packages/services/agent_orchestrator.py) و[`TaskExecutionService`](file:///d:/AI-Employee-Platform/packages/services/task_execution_service.py).
   - مسار التفاعل اللحظي وقنوات التواصل: [`ConversationalAgentEngine`](file:///d:/AI-Employee-Platform/packages/services/conversational_agent_engine.py) و[`OwnerIntentRouter`](file:///d:/AI-Employee-Platform/packages/services/owner_intent_router.py).
   هذان المساران يعملان بكفاءة، لكنهما يحتاجان إلى توحيد دورة حياة الحالة (State Machine) مستلهمة من أنماط الرسوم البيانية الدائرية (`StateGraph`).
3. **وجود نواة متقدمة للتحسين الذاتي والمهارات الديناميكية:** تحتوي الحزمة [`packages/self_development`](file:///d:/AI-Employee-Platform/packages/self_development) على محرك تطوير ذاتي حقيقي يتضمن التحليل الساكن للأكواد (AST Static Analysis)، وفحص الحظر الأمني للأكواد الخبيثة، وبيئة معزولة (Sandbox)، والاعتماد المشروط بالمخاطر. هذا التنفيذ يمثل مطابقة مذهلة لأحدث أوراق البحث المرجعية (خصوصاً **Memento-Skills**)، لكنه يحتاج إلى ضبط دورة الربط بين التلقين التجاري اليومي وإنتاج المهارات البرمجية.
4. **القرارات الاستراتيجية المعتمدة رسمياً تجاه الأطر المرجعية الخارجية:**
   - **الرفض التام للتبني الشامل أو تضمين Dify و n8n:** الحفاظ على سيادة البيانات، وعزل المستأجرين بنسبة 100%، والامتثال الصارم لشروط التراخيص، ومنع ازدواجية حزم الخوادم وقواعد البيانات.
   - **الاستلهام المعماري الانتقائي الداخلي (Selective In-House Inspiration):** تبني نمط حزم المهارات والتعلم الانعكاسي من **Memento-Skills** داخل [`packages/self_development`](file:///d:/AI-Employee-Platform/packages/self_development) دون إدخال حزم خارجية للنواة، ونمط نقاط التوقف والاستئناف البشري (`Interrupt/Resume`) من **LangGraph**، وتصنيف الأدوار وأنماط الاستقلالية (`Semi/Full Autonomy`) من **RagLeap Core**.

---

## 2. حالة المشروع الحالي وفق أدلة الكود الفعلي (Current Repository State)

### 2.1 شجرة الملفات والتنظيم الهيكلي
تم تنظيم المنصة وفق معمارية Monorepo معيارية ونظيفة:
- [`apps/agent`](file:///d:/AI-Employee-Platform/apps/agent): تطبيق FastAPI الأساسي الذي يسجل 28 موجه API تحت البادئة `/api/v1`.
- [`apps/tenant-dashboard`](file:///d:/AI-Employee-Platform/apps/tenant-dashboard): لوحة تحكم مالك المنشأة (React 18 + Vite 5 + TypeScript + Tailwind CSS).
- [`apps/admin-dashboard`](file:///d:/AI-Employee-Platform/apps/admin-dashboard): بوابة الإدارة المركزية الفائقة للمنصة (Superadmin Portal).
- [`packages/`](file:///d:/AI-Employee-Platform/packages): حزم ومكتبات المنطق الأساسي المشترك، وتشمل:
  - `models`: نماذج ORM المقسمة بين المستأجرين [`packages/models/tenant.py`](file:///d:/AI-Employee-Platform/packages/models/tenant.py) وبيانات النطاق [`packages/models/domain.py`](file:///d:/AI-Employee-Platform/packages/models/domain.py).
  - `auth`: إدارة سياق المستأجر [`TenantContext`](file:///d:/AI-Employee-Platform/packages/auth/context.py) وفك رموز JWT ومحددات السرعة (Rate Limiting).
  - `core`: تهيئة قاعدة البيانات والتشفير المتماثل [`SecretsEncryptionService`](file:///d:/AI-Employee-Platform/packages/core/crypto.py).
  - `services`: 41 خدمة أعمال متخصصة (التخطيط، الصلاحيات، الموافقات، المهام، القنوات، الذاكرة، التتبع).
  - `self_development`: المحرك الداخلي لتوليد واختبار وتفعيل المهارات الذاتية والقدرات الديناميكية.
  - `connectors`: قنوات الربط أومني-تشانل (Telegram, WhatsApp Cloud API, Meta, Email, Webhooks).
  - `tools`: سجل الأدوات المعياري [`ToolRegistry`](file:///d:/AI-Employee-Platform/packages/tools/registry.py) ومنفذ الأدوات [`ToolExecutor`](file:///d:/AI-Employee-Platform/packages/tools/executor.py).
  - `memory` & `context`: استخراج وبناء وترتيب السياق التشغيلي ومطابقة الذاكرة الموجهة بالمستأجر.
  - `ai_providers`: بنية الموفرين المرنة التي تدعم Gemini وOpenAI وGroq مع آليات الفشل المرن وقطع الدائرة (`CircuitBreaker`).

### 2.2 مواصفات الحزم والاعتماديات ([`pyproject.toml`](file:///d:/AI-Employee-Platform/pyproject.toml))
الاعتماديات الحالية محددة بعناية وتعتمد على إصدارات إنتاجية حديثة ومستقرة:
- Python `>=3.13, <3.15` (يتم تشغيله حالياً على بيئة Python 3.14).
- FastAPI `>=0.141`, Pydantic `>=2.13`, SQLAlchemy `>=2.0`, Alembic `>=1.16`.
- برامج التشغيل: `psycopg[binary]>=3.2` (PostgreSQL 17 Driver), `cryptography>=42.0`, `pyjwt>=2.8`, `httpx>=0.27.0`.
- خلو المستودع من أي أطر ضخمة مفروضة قسراً (مثل LangChain Core القديم أو CrewAI)، مما يمنح المنصة خفة استثنائية وسرعة إقلاع عالية وتحكماً تاماً في كود الذاكرة وحلقات المعالجة.

### 2.3 تقييم القدرات الـ 15 في الكود الحالي (Status Assessment)

| # | القدرة المعمارية | الحالة الواقعية | الدليل من الكود المصدري | ملفات الاختبارات المحققة |
|---|-------------------|-----------------|--------------------------|---------------------------|
| 1 | **Agent Orchestration** | `IMPLEMENTED_AND_VERIFIED` | [`AgentOrchestrator`](file:///d:/AI-Employee-Platform/packages/services/agent_orchestrator.py) و[`AgentRuntime`](file:///d:/AI-Employee-Platform/packages/services/agent_runtime.py) | [`test_orchestrator_ai_planning.py`](file:///d:/AI-Employee-Platform/tests/test_orchestrator_ai_planning.py), [`test_planner_orchestrator.py`](file:///d:/AI-Employee-Platform/tests/test_planner_orchestrator.py) |
| 2 | **Task Planning & Execution** | `IMPLEMENTED_AND_VERIFIED` | [`TaskPlanner`](file:///d:/AI-Employee-Platform/packages/services/task_planner.py), [`GeminiTaskPlanner`](file:///d:/AI-Employee-Platform/packages/services/gemini_task_planner.py), [`TaskExecutionService`](file:///d:/AI-Employee-Platform/packages/services/task_execution_service.py) | [`test_phase9_task_execution.py`](file:///d:/AI-Employee-Platform/tests/test_phase9_task_execution.py), [`test_gemini_task_planner.py`](file:///d:/AI-Employee-Platform/tests/test_gemini_task_planner.py) |
| 3 | **Skills & Dynamic Capabilities** | `IMPLEMENTED_AND_VERIFIED` | [`CapabilityService`](file:///d:/AI-Employee-Platform/packages/services/capability_service.py), [`DynamicCapabilityTool`](file:///d:/AI-Employee-Platform/packages/self_development/dynamic_tool.py) | [`test_capability_api.py`](file:///d:/AI-Employee-Platform/tests/test_capability_api.py), [`test_autonomous_capability_and_goal_execution.py`](file:///d:/AI-Employee-Platform/tests/test_autonomous_capability_and_goal_execution.py) |
| 4 | **Tool Registry & Execution** | `IMPLEMENTED_AND_VERIFIED` | [`ToolRegistry`](file:///d:/AI-Employee-Platform/packages/tools/registry.py), [`ToolExecutor`](file:///d:/AI-Employee-Platform/packages/tools/executor.py), [`BaseRealTool`](file:///d:/AI-Employee-Platform/packages/tools/base.py) | [`test_real_tools.py`](file:///d:/AI-Employee-Platform/tests/test_real_tools.py), [`test_tool_assignment_guard.py`](file:///d:/AI-Employee-Platform/tests/test_tool_assignment_guard.py) |
| 5 | **Business Brain & Context** | `IMPLEMENTED_AND_VERIFIED` | [`BusinessBrainService`](file:///d:/AI-Employee-Platform/packages/services/business_brain_service.py), [`ContextBuilder`](file:///d:/AI-Employee-Platform/packages/context/builder.py) | [`test_phase12_knowledge_brain.py`](file:///d:/AI-Employee-Platform/tests/test_phase12_knowledge_brain.py), [`test_context_builder.py`](file:///d:/AI-Employee-Platform/tests/test_context_builder.py) |
| 6 | **Short & Long-Term Memory** | `IMPLEMENTED_AND_VERIFIED` | [`MemoryService`](file:///d:/AI-Employee-Platform/packages/memory/service.py), [`MemorySanitizer`](file:///d:/AI-Employee-Platform/packages/memory/sanitizer.py) | [`test_phase11_memory_context.py`](file:///d:/AI-Employee-Platform/tests/test_phase11_memory_context.py), [`test_memory_security_hardening.py`](file:///d:/AI-Employee-Platform/tests/test_memory_security_hardening.py) |
| 7 | **Learning & Evaluation** | `PARTIAL` | نماذج `Learning` و`LearningEvidence` موجودة بـ [`domain.py`](file:///d:/AI-Employee-Platform/packages/models/domain.py)؛ الاستخراج يتم محادثياً فقط عبر `_extract_business_knowledge` دون تقييم إحصائي مستمر لدرجة دقة الموظف. | [`test_phase12_knowledge_brain.py`](file:///d:/AI-Employee-Platform/tests/test_phase12_knowledge_brain.py) |
| 8 | **Human Approval & Governance** | `IMPLEMENTED_AND_VERIFIED` | [`ApprovalService`](file:///d:/AI-Employee-Platform/packages/services/approval_service.py), [`ActionPolicyService`](file:///d:/AI-Employee-Platform/packages/services/action_policy_service.py) | [`test_approval_service.py`](file:///d:/AI-Employee-Platform/tests/test_approval_service.py), [`test_approval_safety_hardening.py`](file:///d:/AI-Employee-Platform/tests/test_approval_safety_hardening.py) |
| 9 | **Proactive Observation & Action** | `IMPLEMENTED_AND_VERIFIED` | [`ProactiveWorkflowService`](file:///d:/AI-Employee-Platform/packages/services/proactive_workflow_service.py), [`CampaignService`](file:///d:/AI-Employee-Platform/packages/services/campaign_service.py) | [`test_proactive_workflow_engine.py`](file:///d:/AI-Employee-Platform/tests/test_proactive_workflow_engine.py), [`test_phase4d_campaigns_and_proactive_notifications.py`](file:///d:/AI-Employee-Platform/tests/test_phase4d_campaigns_and_proactive_notifications.py) |
| 10 | **Background Jobs & Outbox** | `IMPLEMENTED_AND_VERIFIED` | [`OutboxService`](file:///d:/AI-Employee-Platform/packages/services/outbox_service.py), [`OutboxWorker`](file:///d:/AI-Employee-Platform/packages/services/outbox_worker.py) | [`test_outbox_runtime_e2e.py`](file:///d:/AI-Employee-Platform/tests/test_outbox_runtime_e2e.py), [`test_outbox_worker.py`](file:///d:/AI-Employee-Platform/tests/test_outbox_worker.py) |
| 11 | **Integrations & Channels** | `IMPLEMENTED_AND_VERIFIED` | [`ChannelService`](file:///d:/AI-Employee-Platform/packages/services/channel_service.py), [`TelegramConnector`](file:///d:/AI-Employee-Platform/packages/connectors/telegram.py), [`WhatsAppCloudConnector`](file:///d:/AI-Employee-Platform/packages/connectors/whatsapp.py) | [`test_omnichannel_owner_and_customer.py`](file:///d:/AI-Employee-Platform/tests/test_omnichannel_owner_and_customer.py), [`test_phase4c_channel_integration_hardening.py`](file:///d:/AI-Employee-Platform/tests/test_phase4c_channel_integration_hardening.py) |
| 12 | **Tenant Isolation & Security** | `IMPLEMENTED_AND_VERIFIED` | [`TenantContext`](file:///d:/AI-Employee-Platform/packages/auth/context.py), [`SecretsEncryptionService`](file:///d:/AI-Employee-Platform/packages/core/crypto.py) | [`test_multi_tenancy_runtime.py`](file:///d:/AI-Employee-Platform/tests/test_multi_tenancy_runtime.py), [`test_tenant_context.py`](file:///d:/AI-Employee-Platform/tests/test_tenant_context.py) |
| 13 | **Tracing & Audit Observability** | `IMPLEMENTED_AND_VERIFIED` | [`ExecutionTracingService`](file:///d:/AI-Employee-Platform/packages/services/execution_tracing_service.py), [`AuditService`](file:///d:/AI-Employee-Platform/packages/services/audit_service.py) | [`test_phase2_batch1_execution_tracing_schema.py`](file:///d:/AI-Employee-Platform/tests/test_phase2_batch1_execution_tracing_schema.py), [`test_audit_service.py`](file:///d:/AI-Employee-Platform/tests/test_audit_service.py) |
| 14 | **Self-Improvement & Sandbox** | `IMPLEMENTED_AND_VERIFIED` | [`SelfDevelopmentEngine`](file:///d:/AI-Employee-Platform/packages/self_development/engine.py), [`ExecutionSandbox`](file:///d:/AI-Employee-Platform/packages/self_development/sandbox.py), [`CapabilitySecurityVerifier`](file:///d:/AI-Employee-Platform/packages/self_development/verifier.py) | [`test_phase17_self_development.py`](file:///d:/AI-Employee-Platform/tests/test_phase17_self_development.py), [`test_autonomous_capability_and_goal_execution.py`](file:///d:/AI-Employee-Platform/tests/test_autonomous_capability_and_goal_execution.py) |
| 15 | **Tenant & Admin Dashboards** | `IMPLEMENTED_AND_VERIFIED` | [`TenantDetailPage.tsx`](file:///d:/AI-Employee-Platform/apps/admin-dashboard/src/pages/TenantDetailPage.tsx), [`ChannelsPage.tsx`](file:///d:/AI-Employee-Platform/apps/tenant-dashboard/src/pages/ChannelsPage.tsx) | اختبارات Vitest في `apps/admin-dashboard/src/test` و`apps/tenant-dashboard/src/test` |

### 2.4 التصنيف المعماري الموحد لوضع القدرات الحالي
لتقديم رؤية حاسمة تمنع تكرار المجهود وتحدد مسار العمل بدقة:
- **ما هو موجود ويعمل بكفاءة مثبتة (`IMPLEMENTED_AND_VERIFIED`):**
  - عزل المستأجرين والتشفير بالأسرار `TenantContext` و`SecretsEncryptionService`.
  - المراسلة الخلفية الموثوقة وقفل التنافسية `OutboxWorker` (`FOR UPDATE SKIP LOCKED`).
  - سجل الأدوات المركزي وتنفيذها المقيد بالصلاحيات `ToolRegistry` و`ToolExecutor`.
  - إدارة المعرفة والذاكرة طويلة وقصيرة المدى `BusinessBrainService` و`MemoryService`.
  - قنوات التواصل الحية وقفل الهوية للمالك `ChannelService` و`TelegramConnector`.
- **ما هو موجود لكنه غير مكتمل أو غير متصل بالكامل (`PARTIAL`):**
  - دورة التقييم والتعلم المستمر الإحصائي `EvaluationService` لربط أداء الموظف بجداول `learnings`.
  - تكامل واجهات إدارة الذاكرة وتصحيحها في `Tenant Dashboard`.
- **ما هو مكرر أو متداخل ويحتاج إلى توحيد (`DUPLICATED_OR_FRAGMENTED`):**
  - مسار أوركسترا المهام المخططة عبر [`AgentOrchestrator`](file:///d:/AI-Employee-Platform/packages/services/agent_orchestrator.py) مقابل مسار الرد الحواري المباشر عبر [`ConversationalAgentEngine`](file:///d:/AI-Employee-Platform/packages/services/conversational_agent_engine.py). يحتاجان توحيد إدارة الحالة الدائرية.
- **ما هو ناقص فعلاً في حلقة العمل (`MISSING`):**
  - الربط التفاعلي المباشر بين رسائل المالك اليومية في قنوات التواصل (مثل تيليجرام) وبين إطلاق محرك `SelfDevelopmentEngine` لتوليد الأدوات غير الموجودة آلياً وطلب موافقته فوراً.
  - حقول إدخال معرف المالك الصريحة في واجهات إنشاء القنوات في لوحات التحكم.
- **ما ينبغي الاستفادة منه واستلهامه من المشاريع المرجعية:**
  - نمط مواصفات المهارة وحلقة القراءة والكتابة الانعكاسية من **Memento-Skills**.
  - نمط حفظ الحالة ونقاط التدقيق والتوقف البشري `interrupt/resume` من **LangGraph**.
  - أنماط بطاقات الأدوار الوظيفية والاستقلالية الثلاثية (`off`, `semi`, `full`) من **RagLeap Core**.
  - فلاتر استدعاء الوظائف المسبقة واللاحقة من **Semantic Kernel**.
- **ما يجب بناؤه داخلياً حصراً دون استيراد أطر عمل:**
  - موجه الحالة الموحد للمهام والمحادثات.
  - حاقن ومقنع الأسرار التلقائي في سجلات التتبع.
  - خدمة التقييم الذاتي للأعمال.

---

## 3. دراسة وتحليل المشاريع المرجعية الستة بالتفصيل (Detailed Reference Projects Analysis)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                REFERENCE PROJECTS ECOSYSTEM                                      │
├─────────────────────────┬─────────────────────────┬──────────────────────────────────────────────┤
│ 1. Memento-Skills       │ Continual Agent Learning│ Dynamic Skill Authoring & Read/Write Memory  │
│ 2. LangGraph            │ Graph Orchestration     │ StateGraph, Checkpointers, Interrupt/Resume  │
│ 3. Microsoft Frameworks │ Unified Agent Runtime   │ AutoGen (Actors) + Semantic Kernel (Plugins) │
│ 4. Dify                 │ LLMOps / App Platform   │ Visual Workflows, RAG, Prompt Engineering    │
│ 5. n8n                  │ Integration Engine      │ 400+ SaaS Connectors, Webhook Event Triggers │
│ 6. RagLeap Core         │ AI Business OS (OS-SaaS)│ 46 Business Roles, Semi/Full Autonomy Levels │
└─────────────────────────┴─────────────────────────┴──────────────────────────────────────────────┘
```

---

### 3.1 مشروع Memento-Skills

1. **المستودع والمصادر الرسمية:**
   - المستودع الرسمي: [`Memento-Teams/Memento-Skills`](https://github.com/Memento-Teams/Memento-Skills).
   - الورقة العلمية على ArXiv: [arXiv:2603.18743 [cs.AI]](https://arxiv.org/abs/2603.18743) ("Memento-Skills: Let Agents Design Agents"، مارس 2026، باحثون: Huichi Zhou et al.).
   - التوثيق الرسمي: [memento.run](https://memento.run).
2. **الغرض الحقيقي والمشكلة الأساسية:**
   - معالجة مشكلة "جمود الوكلاء" (Agent Rigidity). تقليدياً، تعتمد النماذج على قوائم أدوات ثابتة (Static Tool Lists) أو تتطلب إعادة تدريب دقيق مكلف (Fine-Tuning). يقدم Memento-Skills مفهوماً ثورياً: "Agents Design Agents"، حيث تُعامل القدرات كملفات مهارات منظمة (Structured Markdown + Python Code) قابلة للإنشاء والتعديل والاختبار والتحسين الذاتي المستمر دون تعديل أوزان النموذج.
3. **البنية المعمارية والمكونات الرئيسية:**
   - *Skill Library:* مستودع منظم للمهارات مقسم إلى شقين: وثيقة المهارة `SKILL.md` (التعليمات، القيود، الشروط) + كود بايثون للتنفيذ.
   - *Skill Router:* موجه ذكي مدرب سلوكياً على مطابقة النوايا مع المهارات المناسبة دون تحميل كل التوثيق في نافذة السياق.
   - *Reflective Learning Loop:* حلقة مغلقة لتقييم النتائج وإعادة كتابة المهارات الفاشلة.
4. **طريقة إدارة الوكلاء والمهام والحالة والذاكرة:**
   - يعتمد نمط الذاكرة المزدوجة (Read–Write Memory Architecture):
     - *Read Phase:* قراءة الذاكرة واختيار المهارة ذات الصلة بالسياق الحالي.
     - *Write Phase:* الانعكاس على نتيجة تنفيذ المهمة؛ إذا فشلت المهارة أو واجهت استثناءً، يحلل الوكيل الخطأ، ويولد تحسيناً للمهارة، ويختبرها في ساندبوكس، ويثبتها في الذاكرة.
5. **طريقة إضافة المهارات والأدوات:**
   - كل مهارة عبارة عن حزمة معيارية مستقلة ذاتية التوثيق (`self-contained skill package`) يتم تسجيلها ديناميكياً في سجل الأدوات بمجرد اجتياز الفحص والاختبار.
6. **أسلوب التعامل مع الأخطاء وإعادة المحاولة:**
   - كشف الخطأ في وقت التشغيل (Runtime Error Trace) -> تمرير Traceback للوكيل المعماري الداخلي -> توليد تصحيح برمجياً -> تشغيل حالات الاختبار المرفقة في الساندبوكس.
7. **آليات التقييم والاختبار والمراقبة:**
   - يتضمن أداة فحص ذاتي بيئي (`memento doctor`)، وأداة اختبار وحدات مصاحبة لكل مهارة مولدة، وسجل تدقيق تفصيلي لخطوات التطور.
8. **دعم التكاملات والموافقات البشرية:**
   - يدعم تشغيل CLI وتطبيق مكتبي (GUI)، وتكاملات رسائل مثل Feishu. لكنه يفتقر لنظام حوكمة مؤسسي صارم للموافقات البشرية المسبقة لمتعددي المستأجرين (RBAC).
9. **الترخيص وشروط الاستخدام:**
   - **Apache License 2.0** مفتوحة المصدر بالكامل، وتسمح بالاستخدام التجاري الحر والتعديل وإعادة التوزيع دون قيود.
10. **الاعتماديات والمتطلبات وتكلفة التبني:**
    - مكتبات بايثون قياسية، تكلفة منخفضة، لا تتطلب خوادم معقدة أو قواعد بيانات خاصة.
11. **المخاطر الأمنية:**
    - خطر حقن الأوامر وتوليد أكواد خبيثة (Code Injection) إذا تم تشغيل الأكواد المولدة مباشرة على نظام التشغيل المضيف دون ساندبوكس معزول كلياً.
12. **القرار للمنصة:**
    - **`INSPIRE_ONLY`**. تطابق فكري بنسبة 95% مع [`packages/self_development`](file:///d:/AI-Employee-Platform/packages/self_development). لن نقوم باستيراد الحزمة كاعتمادية بايثون خارجية لتجنب القيود التشغيلية، بل سنعتمد نمط مواصفات المهارات (Skill Specification Schema) وحلقة القراءة والكتابة الانعكاسية داخل محركنا الحالي المحكوم.

---

### 3.2 مشروع LangGraph

1. **المستودع والمصادر الرسمية:**
   - المستودع الرسمي: [`langchain-ai/langgraph`](https://github.com/langchain-ai/langgraph) (الإصدار المستقر 0.2+).
   - التوثيق الرسمي: [langchain-ai.github.io/langgraph](https://langchain-ai.github.io/langgraph/).
2. **الغرض الحقيقي والمشكلة الأساسية:**
   - حل قصور السلاسل الخطية البسيطة (DAGs / Linear Chains) عند بناء وكلاء أذكياء يتطلبون حلقات دائرية (Cycles)، واتخاذ قرارات متفرعة، وإدارة حالة ممتدة معقدة بين وكلاء متعددين.
3. **البنية المعمارية والمكونات الرئيسية:**
   - `StateGraph`: رسم بياني موجه بحالة مشتركة متطورة (State Schema).
   - `Nodes`: دوال بايثون أو وكلاء فرعيين ينفذون مهاماً محددة ويعدلون الحالة.
   - `Edges & Conditional Edges`: مسارات الانتقال الشرطية بين العقد بناءً على مخرجات الذكاء الاصطناعي.
   - `Checkpointers`: محركات تثبيت الحالة عند كل خطوة (PostgreSQL / Redis / SQLite / Memory).
4. **إدارة الوكلاء والمهام والحالة والذاكرة:**
   - إدارة حالة كاملة مبنية على إطار `Reducers` لدمج تحديثات الحالة بدقة، مع ذاكرة قصيرة المدى مدمجة في مسار التنفيذ، وذاكرة طويلة المدى عبر مخازن المستندات.
5. **طريقة إضافة المهارات والأدوات:**
   - تُعامل الأدوات كعقد ضمن الرسم البياني أو يتم استدعاؤها عبر `ToolNode` المعيارية.
6. **أسلوب التعامل مع الأخطاء والاستئناف:**
   - ميزة استئناف التنفيذ والسفر عبر الزمن (Time-Travel Debugging): بما أن كل خطوة مثبتة في Checkpointer، يمكن استئناف التنفيذ من أي عقدة سابقة عند حدوث خطأ دون إعادة تشغيل المسار من البداية.
7. **آليات التقييم والمراقبة والتتبع:**
   - تكامل أصيل ومباشر مع منصة **LangSmith** لمراقبة كل خطوة ومدخلاتها واستهلاك التوكنات وزمن الاستجابة.
8. **دعم التكاملات والعمليات الطويلة والموافقات البشرية:**
   - دعم كامل وتفوق معمارى في **Human-in-the-Loop** عبر أمر المقاطعة `interrupt()`؛ حيث يتوقف التنفيذ تماماً عند الخطوة الحساسة، وتُحفظ الحالة في قاعدة البيانات، ويُستأنف الرسم البياني فور إدخال المستخدم البشري.
9. **الترخيص وشروط الاستخدام:**
   - **MIT License** حرة ومفتوحة بالكامل للاستخدام التجاري.
10. **الاعتماديات والمتطلبات وتكلفة التبني:**
    - تتطلب تثبيت حزم `langchain-core` و`langgraph` وتوابعهما، مما يزيد حجم شجرة الاعتماديات ويعقد التوافق مع بيئات بايثون الحديثة جداً مثل 3.14.
11. **المخاطر الأمنية:**
    - التعقيد الزائد في إدارة الرسوم البيانية، وخطر التشابك غير الضروري وتآكل حدود عزل المستأجرين إذا لم تُصمم مفاتيح الـ Checkpoints بعزل تام للـ `tenant_id`.
12. **القرار للمنصة:**
    - **`INSPIRE_ONLY`**. لا نريد جلب حزم LangChain الضخمة التي استبعدتها المنصة عمداً للحفاظ على نقاء الأداء وسرعة الإقلاع. سنستلهم نمط آلة الحالة الدائرية (`State Machine`) ونقاط التدقيق وحلقات المقاطعة للاعتماد البشري (`interrupt/resume`)، ونطبقها مباشرة فوق جداولنا الحالية ([`tasks`](file:///d:/AI-Employee-Platform/packages/models/domain.py) و[`approvals`](file:///d:/AI-Employee-Platform/packages/models/domain.py) و[`outbox_events`](file:///d:/AI-Employee-Platform/packages/models/domain.py)).

---

### 3.3 مشروع Microsoft Agent Framework (وعلاقته بـ AutoGen و Semantic Kernel)

1. **توضيح العلاقة المعمارية بين المشاريع الثلاثة:**
   - **Microsoft AutoGen:** مشروع بحثي رائد ركز على المحادثات الديناميكية بين وكلاء متعددين يتناقشون ويتعاونون لحل المسائل عبر الرسائل ونموذج الفاعلين (Actor-based dynamic chat turns).
   - **Semantic Kernel (SK):** إطار عمل وحزمة SDK مؤسسية مخصصة لدمج الذكاء الاصطناعي في تطبيقات الشركات (.NET و Python) عبر حاوية حقن الاعتماديات (`Kernel`)، والإضافات (`Plugins`)، والمخططات (`Planners`)، وموصلات الذاكرة.
   - **Microsoft Agent Framework (MAF):** **المظلة الموحدة والخليفة الرسمي:** أعلنت مايكروسوفت توحيد وتطوير أفضل المفاهيم المعمارية من AutoGen (التنسيق متعدد الوكلاء والحوارات المتشعبة) مع القوة المؤسسية لـ Semantic Kernel (حقن التبعيات، فلاتر الأمان، والجاهزية المؤسسية) تحت إطار موحد مبني على حزم `Microsoft.Extensions.AI`.
   - **هل دراستهما منفصلتين ضرورية؟** نعم، لأن AutoGen يفيدنا في نمط الفاعلين غير المتزامنين وتوزيع المهام بين وكلاء متخصصين، بينما Semantic Kernel يفيدنا في نمط حوكمة استدعاء الأدوات عبر الفلاتر القبلية والبعدية (`Invocation Filters`).
2. **المستودعات والمصادر الرسمية:**
   - مستودع AutoGen: [`microsoft/autogen`](https://github.com/microsoft/autogen) (الإصدار الحديث 0.4).
   - مستودع Semantic Kernel: [`microsoft/semantic-kernel`](https://github.com/microsoft/semantic-kernel).
   - التوثيق الرسمي: [learn.microsoft.com/semantic-kernel](https://learn.microsoft.com/en-us/semantic-kernel/) و[microsoft.github.io/autogen](https://microsoft.github.io/autogen/).
3. **البنية المعمارية وإدارة الحالة:**
   - يعتمد AutoGen 0.4 نمط الفاعلين غير المتزامنين (Event-Driven Actors) وصناديق البريد غير المتزامنة ومفاهيم الاشتراك بالموضوعات (`Topics`).
   - يعتمد Semantic Kernel نمط سياق التنفيذ المشترك (`KernelArguments`) ومرشحات التدقيق.
4. **طريقة إضافة الأدوات وتسجيلها:**
   - عبر تعريف وظائف واضحة الأنواع مع شروح المعاملات (`Decorators & Type Annotations`)، مع ربطها بمخططات خطوة بخطوة (`Stepwise Planners`).
5. **التعامل مع الأخطاء والمراقبة:**
   - مرشحات ما بعد الاستدعاء (`Post-invocation filters`) تفحص الاستثناءات وتمنع تسريب تفاصيل النظام، مع توافق أصيل مع معايير **OpenTelemetry**.
6. **الترخيص وشروط الاستخدام:**
   - جميعها مرخصة برخصة **MIT License** الحرة تماماً والمتاحة للاستخدام التجاري.
7. **الاعتماديات والمخاطر:**
   - الاعتماد على مكدس ميكروسوفت يفرض قيوداً على هياكل البيانات ويميل إلى التعقيد المكتبي، فضلاً عن عدم ملاءمته الكاملة لبيئة التطوير الخفيفة الخاصة بنا.
8. **القرار للمنصة:**
   - **`INSPIRE_ONLY`**. سنستلهم نمط مرشحات الأمان القبلية والبعدية للأدوات (`Tool Filters`) داخل [`ToolExecutor`](file:///d:/AI-Employee-Platform/packages/tools/executor.py) ونمط تفويض الوكلاء المتخصصين، مع تجنب استيراد مكتبات ميكروسوفت كاعتمادية في النواة.

---

### 3.4 مشروع Dify (فصل الحقائق القانونية عن المخاطر التقنية)

1. **المستودع والمصادر الرسمية:**
   - المستودع الرسمي: [`langgenius/dify`](https://github.com/langgenius/dify).
   - التوثيق الرسمي: [docs.dify.ai](https://docs.dify.ai).
2. **الغرض الحقيقي والمشكلة الأساسية:**
   - توفير منصة تطوير وإدارة تطبيقات الذكاء الاصطناعي (LLMOps) بصرية وشاملة، تركز على تسهيل بناء خطوط سير العمل المرئية وتطبيقات RAG وخدمة العملاء.
3. **البنية المعمارية والمكونات الرئيسية:**
   - تطبيق متكامل موزع كخدمات مصغرة وحاويات متعددة: Next.js للواجهة، Flask/Python للخلفية، Celery لمعالجة المهام غير المتزامنة، Redis للتخزين المؤقت، Weaviate/PgVector لقواعد البيانات المتجهة، ومخازن S3/MinIO للمستندات.
4. **الحقائق القانونية المثبتة بخصوص الترخيص وشروط الاستخدام:**
   - كود Dify مرخص بموجب **Apache License 2.0 مع ملحق شروط Dify Open Source License**.
   - **الحقيقة القانونية المثبتة:** تنص شروط ترخيص Dify صراحة على قيود تجارية تمنع استغلال كود Dify لإعادة بيعه أو تقديمه مباشرة كخدمة سحابية منافسة متعددة المستأجرين (Commercial Multi-tenant SaaS / White-label AI Platform) دون الحصول على ترخيص تجاري مدفوع وشراكة رسمية من الشركة المالكة (LangGenius, Inc.).
   - استخدام Dify داخلياً لتشغيل تطبيقات المؤسسة مسموح، لكن تضمينه داخل منتجنا التجاري المباع للشركات كمنصة موظفين سحابية يضع المنصة في منطقة رمادية ومخاطر انتهاك للملكية الفكرية.
5. **المخاطر التقنية والتشغيلية (مفصولة عن القانونية):**
   - **تضارب البنية التحتية:** Dify ليس حزمة بايثون يمكن استيرادها بـ `pip`، بل هو نظام خادم كامل يتطلب 8 إلى 12 حاوية Docker قيد التشغيل وذاكرة لا تقل عن 8GB RAM، مما يرفع تكلفة الاستضافة بشكل هائل.
   - **كسر عزل المستأجرين (Tenant Isolation Conflict):** يمتلك Dify نظام جداول وصلاحيات ومستخدمين ومصادقة مستقلاً تماماً، وتضمينه سيؤدي إلى ازدواجية البيانات، واستحالة تطبيق قواعد `TenantContext` و`tenant_id` الخاصة بمنصتنا على عملياته الداخلية.
6. **القرار للمنصة:**
   - **`REJECT` (Core Embedding) / `INSPIRE_ONLY` (UI Design)**. رفض قاطع لأي محاولة لتضمين خادم Dify داخل منصتنا للأسباب القانونية والتقنية الموثقة. سنقتصر على استلهام تصميم واجهات لوحة التحكم الخاصة بالمعرفة وإحصائيات الاستهلاك في لوحة المستأجرين لدينا.

---

### 3.5 مشروع n8n (فصل الحقائق القانونية عن المخاطر التقنية)

1. **المستودع والمصادر الرسمية:**
   - المستودع الرسمي: [`n8n-io/n8n`](https://github.com/n8n-io/n8n).
   - التوثيق الرسمي: [docs.n8n.io](https://docs.n8n.io).
2. **الغرض الحقيقي والمشكلة الأساسية:**
   - منصة أتمتة تدفقات عمل وتكاملات واسعة النطاق توفر أكثر من 400 موصل SaaS جاهز ومحرر عقد رسومي لربط الأنظمة عبر الويب.
3. **البنية المعمارية والمكونات الرئيسية:**
   - مبني بالكامل على مكدس **Node.js / TypeScript** وVue.js، ويعتمد محرك تنفيذ قائم على تدفق البيانات (Data-flow Nodes) وقاعدة بيانات SQLite/PostgreSQL خاصة به.
4. **الحقائق القانونية المثبتة بخصوص الترخيص وشروط الاستخدام:**
   - n8n لا يستخدم ترخيصاً مفتوح المصدر تقليدياً معتمداً من OSI (مثل MIT أو Apache)، بل يخضع لترخيص **Sustainable Use License (Fair-code)**.
   - **الحقيقة القانونية المثبتة:** تنص شروط الاستخدام لترخيص n8n صراحة على أنه: *"You may not make the software available to third parties as a managed service, hosted service, or Software-as-a-Service (SaaS) where the functionality of n8n is offered directly or indirectly to paying customers without an Enterprise License Agreement from n8n GmbH."*
   - هذا يعني قانونياً أن استضافة n8n داخل منصتنا لتقديم خدمات تكامل أو أتمتة للمستأجرين التجاريين كجزء من اشتراك المنصة يُعد خرقاً مباشراً لشروط الترخيص ما لم نبرم اتفاقية تجارية مدفوعة مع الشركة المالكة.
5. **المخاطر التقنية والتشغيلية (مفصولة عن القانونية):**
   - **ازدواجية المكدس التقني:** إدخال بيئة Node.js كاملة إلى جانب بايثون 3.14 يزيد تعقيد البناء، ويزيد حجم الحاويات، ويتطلب إدارة دورة حياة وتحديثات ثنائية.
   - **انعدام عزل المستأجرين الأصيل في النسخة المجانية:** النسخة مفتوحة المصدر من n8n مصممة لاستخدام فردي أو داخلي لشركة واحدة (Single-tenant)، وتفتقر إلى العزل الصارم على مستوى الصفوف (`tenant_id`) الذي تتطلبه منصتنا لخدمة مئات الشركات المشتركة.
6. **القرار للمنصة:**
   - **`REJECT` كدمج داخلي**. لا يجوز تضمين n8n داخل حاويات المنصة لتفادي المخاطر القانونية والتقنية. نكتفي في المستقبل البعيد بتوفير موصل خارجي اختياري (`Generic Webhook Trigger`) لمن يمتلك خادم n8n خاصاً به خارج المنصة.

---

### 3.6 مشروع RagLeap Core

1. **المستودع والمصادر الرسمية:**
   - المستودع الرسمي: [`ragleap/ragleap-core`](https://github.com/ragleap/ragleap-core).
   - التوثيق الرسمي: [ragleap.com](https://ragleap.com).
2. **الغرض الحقيقي والمشكلة الأساسية:**
   - العمل كنظام تشغيل مفتوح المصدر للموظفين الرقميين المعتمدين على الأدوار (Role-Based AI Employees)، وتقديم بديل ذاتي الاستضافة لـ LangChain وCrewAI يدعم العمل مباشرة على مستندات وبيانات المنشأة.
3. **البنية المعمارية والمكونات الرئيسية:**
   - *Role Personas Library:* 46 دوراً وظيفياً للأعمال (HR, Sales, Customer Care, Operations, Legal).
   - *Graph RAG & Hybrid Retrieval:* محرك استرجاع هجين يدمج `pgvector` مع قواعد المعرفة البيانية Neo4j (`ragleap-rag`, `ragleap-graph`).
   - *Multi-Channel Messaging Engine:* موصلات اتصال مدمجة لتيليجرام وواتساب ودسكورد وواجهات صوتية.
   - *Multi-LLM Engine:* دعم 17+ موفر للنماذج بنمط Bring-Your-Own-Key (BYOK).
4. **إدارة الوكلاء والمهام والحالة والذاكرة:**
   - تقسيم الموظفين حسب التخصص التجاري، مع ربط كل دور بمهام وسياق محدد، وإدارة الحالة لكل مستند ومحادثة.
5. **طريقة إضافة المهارات والأدوات:**
   - عبر تعريف بطاقات الأدوار والأدوات التابعة لكل دور في ملفات تكوين.
6. **أسلوب التعامل مع الأخطاء:**
   - محاولة التبديل بين النماذج (Model Fallback) وإشعار المستخدم عند الفشل.
7. **آليات التقييم والمراقبة:**
   - تقارير تدقيق للردود وسجلات تتبع المحادثات.
8. **دعم التكاملات والموافقات البشرية:**
   - يدعم نظاماً ثلاثي المستويات لحوكمة استقلالية الموظف:
     - `off`: وضع الاستماع فقط والمساعدة الداخلية.
     - `semi`: وضع الموافقة الإلزامية؛ لا ينفذ الموظف أي إجراء خارجي دون موافقة بشرية.
     - `full`: وضع الاستقلالية الكاملة للقرارات والمهام المسموحة.
9. **الترخيص وشروط الاستخدام:**
   - **MIT License** حرة ومفتوحة بالكامل للاستخدام التجاري وإعادة التوزيع.
10. **الاعتماديات والمتطلبات وتكلفة التبني:**
    - خفيفة ومتوافقة تماماً مع بايثون وقواعد بيانات `pgvector`.
11. **المخاطر الأمنية:**
    - انخفاض المخاطر عموماً؛ الخطر الوحيد هو ضعف عزل المستأجرين في الكود الأصلي إذا تم تبنيه كاملاً دون تعديل، حيث صُمم في الأصل كـ Single-Tenant / Self-Hosted لشركة واحدة.
12. **القرار للمنصة:**
    - **`INTEGRATE_SELECTIVELY`**. الفلسفة العامة لـ RagLeap هي الأقرب حرفياً لرؤية مشروعنا. سنستلهم مواصفات الأدوار الوظيفية (Role Personas) ونموذج حوكمة الاستقلالية الثلاثي (`off`, `semi`, `full`)، مع دمجه في نظام الصلاحيات ومصفوفة الأمان الحالية للمنصة دون استبدال جداولنا.

---

## 4. مصفوفة فجوات القدرات المعمارية (Capability Gap Matrix)

| # | القدرة المستهدفة | الحالة في المنصة | الأدلة من الكود والاختبارات | المشاريع المرجعية | الفجوة الفعلية | الخيار المعماري | التوصية ومبررها | اختبار القبول (Acceptance Test) |
|---|-------------------|-------------------|-----------------------------|--------------------|-----------------|------------------|-------------------|----------------------------------|
| **1** | **Agent Orchestration** | `IMPLEMENTED_AND_VERIFIED` | [`AgentOrchestrator`](file:///d:/AI-Employee-Platform/packages/services/agent_orchestrator.py) و[`test_orchestrator_ai_planning.py`](file:///d:/AI-Employee-Platform/tests/test_orchestrator_ai_planning.py) | LangGraph, AutoGen 0.4 | الفصل الحالي بين محرك المهام ومحرك المحادثة يحتاج توحيد نموذج الحالة الدائري | استلهام تصميم (Inspire) | توحيد State Machine داخلي مستلهم من LangGraph دون استيراد حزم خارجية | تنفيذ مهمة مركبة متعددة الخطوات تشمل محادثة واستدعاء أداتين مع تتبع كامل للحالة |
| **2** | **Task Planning & Execution** | `IMPLEMENTED_AND_VERIFIED` | [`GeminiTaskPlanner`](file:///d:/AI-Employee-Platform/packages/services/gemini_task_planner.py) و[`TaskExecutionService`](file:///d:/AI-Employee-Platform/packages/services/task_execution_service.py) | Semantic Kernel | المخطط يولد خطوات JSON صلبة؛ يحتاج مرونة أكبر عند فشل خطوة لإعادة التخطيط التلقائي | تطوير داخلي (Enhance) | إضافة حلقة إعادة تخطيط ديناميكية (`Dynamic Re-planning loop`) في `TaskExecutionService` | إخفاق أداة متعمد في الخطوة 2 وإثبات أن المخطط يبتكر خطة بديلة تلقائياً وينجح |
| **3** | **Skills & Dynamic Capabilities** | `IMPLEMENTED_AND_VERIFIED` | [`SelfDevelopmentEngine`](file:///d:/AI-Employee-Platform/packages/self_development/engine.py), [`dynamic_tool.py`](file:///d:/AI-Employee-Platform/packages/self_development/dynamic_tool.py) | Memento-Skills | المهارات تسجل كأكواد في DB؛ ينقصها معيار حزم المهارات الشامل (Instruction + Code + Tests في ملف Markdown/JSON موحد) | استلهام مباشر (Inspire) | مواءمة محرك `packages/self_development` مع هيكل مواصفات Memento-Skills | توليد مهارة حسابية جديدة واختبارها واعتمادها وحفظ مواصفاتها بصيغة موحدة |
| **4** | **Tool Registry & Execution** | `IMPLEMENTED_AND_VERIFIED` | [`ToolRegistry`](file:///d:/AI-Employee-Platform/packages/tools/registry.py), [`ToolExecutor`](file:///d:/AI-Employee-Platform/packages/tools/executor.py) | Semantic Kernel, RagLeap | الأدوات محكومة بالصلاحيات وسياق المستأجر وتعمل بامتياز؛ ينقص فقط حاقن تلقائي للقيم الحساسة المقنعة | تطوير داخلي (Enhance) | الإبقاء الكامل على النواة الحالية مع إغلاق قنوات تسريب البيانات في السجلات | تمرير أداة تستخدم مفتاح API وتأكيد حجب المفتاح في سجلات التدقيق والمخرجات |
| **5** | **Business Brain & Context** | `IMPLEMENTED_AND_VERIFIED` | [`BusinessBrainService`](file:///d:/AI-Employee-Platform/packages/services/business_brain_service.py), [`ContextBuilder`](file:///d:/AI-Employee-Platform/packages/context/builder.py) | RagLeap Core, Dify | السياق الحالي يجمع الهوية والمنتجات والسياسات بدقة؛ ينقصه دعم التضمينات المتجهة الهجينة (Hybrid Vector Search) عند زيادة حجم الكتالوج | تطوير داخلي مجدول | تفعيل استعلامات `pgvector` الموجودة في البنية التحتية لحساب التشابه الدلالي للكتالوج الكبير | استرجاع أفضل 3 منتجات من كتالوج يضم 10,000 صنف بسرعة استجابة أقل من 50ms |
| **6** | **Short & Long-Term Memory** | `IMPLEMENTED_AND_VERIFIED` | [`MemoryService`](file:///d:/AI-Employee-Platform/packages/memory/service.py) و[`test_phase11_memory_context.py`](file:///d:/AI-Employee-Platform/tests/test_phase11_memory_context.py) | Memento-Skills | استخراج الذاكرة وتنقيتها وفصل المستأجرين ممتاز؛ ينقص إتاحة تصحيح الذاكرة الفاسدة يدوياً من لوحة التحكم | تكامل واجهات (UI) | ربط شاشة إدارة الذاكرة في `TenantDashboard` بمسارات الإلغاء والتعديل | تمكين مالك المنشأة من حذف ذكرى غير صحيحة وإثبات عدم استخدامها في الرد اللاحق |
| **7** | **Learning & Evaluation** | `PARTIAL` | نموذج [`Learning`](file:///d:/AI-Employee-Platform/packages/models/domain.py) موجود، التلقين يعمل محادثياً | Memento-Skills (Reflective Learning) | غياب مؤشر قياس الجودة الكمي (Evaluation Metrics) لقياس مدى التزام الموظف بسياسات المنشأة | تطوير داخلي (Adopt Pattern) | بناء خدمة تقييم دورية (`EvaluationService`) تحلل عينات المحادثات وتقيس الرضا ودقة الردود | تقرير أسبوعي يظهر دقة الردود، والأسئلة التي عجز الموظف عن إجابتها بنجاح |
| **8** | **Human Approval & Governance** | `IMPLEMENTED_AND_VERIFIED` | [`ApprovalService`](file:///d:/AI-Employee-Platform/packages/services/approval_service.py), [`test_approval_safety_hardening.py`](file:///d:/AI-Employee-Platform/tests/test_approval_safety_hardening.py) | RagLeap Core, LangGraph | النظام يطلب الموافقة ويقفل العمليات الحساسة بدقة؛ ينقص إشعار المالك اللحظي عبر التيليجرام بطلب الموافقة مع زر تفاعلي | تكامل قنوات (Channel Enhance) | إرسال رسالة تفاعلية في تيليجرام بزر اعتماد سريع مرتبط بـ UUID للموافقة | وصول إشعار بطلب موافقة إلى تيليجرام المالك مع معالجته فور الرد بكلمة "أوافق" |
| **9** | **Proactive Observation** | `IMPLEMENTED_AND_VERIFIED` | [`ProactiveWorkflowService`](file:///d:/AI-Employee-Platform/packages/services/proactive_workflow_service.py) و[`test_proactive_workflow_engine.py`](file:///d:/AI-Employee-Platform/tests/test_proactive_workflow_engine.py) | n8n | المهام الدورية والتقارير اليومية وحملات التوعية تعمل بامتياز؛ ينقص اكتشاف شذوذ المبيعات الاستباقي | تطوير داخلي | إضافة مشغل ذكي يكتشف انقطاع رسائل العملاء أو تراجع الطلبات ويرسل تنبيهاً تشخيصياً | محاكاة انخفاض مفاجئ في حركة المتجر وتلقي المالك تقريراً تشخيصياً يقترح حملة ترويجية |
| **10** | **Background Jobs & Outbox** | `IMPLEMENTED_AND_VERIFIED` | [`OutboxWorker`](file:///d:/AI-Employee-Platform/packages/services/outbox_worker.py), [`test_outbox_runtime_e2e.py`](file:///d:/AI-Employee-Platform/tests/test_outbox_runtime_e2e.py) | نمط Outbox موثق | المعمارية الإنتاجية مكتملة وموثوقة بنسبة 100% مع معالجة التنافسية وقفل الصفوف | الحفاظ عليها كما هي | الاستمرار في استخدام `OutboxWorker` كنواة حصرية لتسليم جميع الإجراءات الخارجية | اختبار ضغط تنافسي لـ 100 حدث Outbox في بيئة متعددة الخيوط دون أي تسليم مكرر |
| **11** | **Integrations & Connectors** | `IMPLEMENTED_AND_VERIFIED` | [`ChannelService`](file:///d:/AI-Employee-Platform/packages/services/channel_service.py), موصلات تيليجرام وواتساب | n8n | قنوات المراسلة مكتملة ومؤمنة؛ ينقص إضافة حقل صريح لمعرف المالك في واجهة إنشاء القنوات لتفادي الالتباس | تعديل واجهة أمامية | إضافة حقل `owner_telegram_id` و`owner_phone` في نماذج الإضافة بلوحة الإدارة | إنشاء قناة تيليجرام جديدة مع إدخال معرف المالك والتحقق من التعرف الفوري عليه |
| **12** | **Tenant Isolation & Security** | `IMPLEMENTED_AND_VERIFIED` | [`TenantContext`](file:///d:/AI-Employee-Platform/packages/auth/context.py), [`test_multi_tenancy_runtime.py`](file:///d:/AI-Employee-Platform/tests/test_multi_tenancy_runtime.py) | جميع الأطر المؤسسية | عزل المستأجرين محكم في جميع الجداول عبر `tenant_id` وتشفير الأسرار بـ AES-GCM | الحفاظ عليه كخط أحمر | منع أي استعلام cross-tenant تحت أي ظرف وضمان عدم اختراق السياق | اختبار اختراق يثبت فشل أي طلب يرسله مستخدم مستأجر لمحاولة قراءة بيانات مستأجر آخر |
| **13** | **Tracing & Observability** | `IMPLEMENTED_AND_VERIFIED` | [`ExecutionTracingService`](file:///d:/AI-Employee-Platform/packages/services/execution_tracing_service.py), [`AuditService`](file:///d:/AI-Employee-Platform/packages/services/audit_service.py) | LangSmith, Dify | تتبع الخطوات وتسجيل المدخلات والمخرجات المقنعة مكتمل بنسبة 100%؛ ينقص عرض الشجرة الرسومية في الواجهة | تحسين واجهة أمامية | عرض شجرة التتبع الزمني (Timeline Waterfall) في لوحة الإدارة لمتابعة كل استدعاء | فتح صفحة تفاصيل أي أثر تنفيذي في لوحة الإدارة ورؤية خطوات التنفيذ وزمن كل خطوة |
| **14** | **Self-Improvement Sandbox** | `IMPLEMENTED_AND_VERIFIED` | [`ExecutionSandbox`](file:///d:/AI-Employee-Platform/packages/self_development/sandbox.py), [`CapabilitySecurityVerifier`](file:///d:/AI-Employee-Platform/packages/self_development/verifier.py) | Memento-Skills | التحليل الساكن والحظر الأمني يعملان بامتياز؛ ينقص الربط التلقائي لدورة اقتراح المهارة عند تكرار طلب غير مدعوم | استلهام Memento-Skills | تفعيل دورة "كشف الفجوة -> مسودة مهارة -> فحص -> اعتماد المالك" عبر المحادثة | طلب المالك لحساب ضريبة القيمة المضافة، وتوليد الأداة تلقائياً، وطلب اعتماده، واستخدامها فوراً |
| **15** | **Dashboards (Admin/Tenant)** | `IMPLEMENTED_AND_VERIFIED` | [`apps/tenant-dashboard`](file:///d:/AI-Employee-Platform/apps/tenant-dashboard) و[`apps/admin-dashboard`](file:///d:/AI-Employee-Platform/apps/admin-dashboard) | Dify | الواجهات متكاملة وتدعم العربية (RTL)؛ ينقص استكمال بعض شاشات الإحصائيات الحية للذاكرة | تحسين واجهات | استكمال شاشات عرض الذاكرة ومؤشرات جودة الأداء في لوحة تحكم المستأجر | بناء لوحة العميل بنجاح (`npm run build`) وتصفح جميع أقسامها دون أي أخطاء برمجية |

---

## 5. مصفوفة قرارات التبني المعماري (Architecture Adoption Matrix)

| المشروع المرجعي | القرار المعماري | التوافق مع بايثون وFastAPI | عزل المستأجرين (Multi-Tenancy) | التوافق مع الصلاحيات والموافقات | التشغيل الذاتي والسيادة (Self-Host) | التكلفة التشغيلية والصيانة | قابلية المراقبة والاختبار | مخاطر تضارب المسؤوليات |
|---|---|---|---|---|---|---|---|---|
| **Memento-Skills** | **`INSPIRE_ONLY`** | 100% متوافق (بايثون خالص) | يتطلب تغليفه بسياق المستأجر | يتكامل بسلاسة عبر ساندبوكس المنصة | تشغيل ذاتي كامل مجاني | منخفضة جداً (ملفات وكود خفيف) | عالية جداً عبر فحص `memento doctor` | منعدمة عند اعتماد النمط داخلياً |
| **LangGraph** | **`INSPIRE_ONLY`** | متوافق جزئياً (يثقل بيئة بايثون) | يتطلب جهداً إضافياً لعزل الـ Checkpointer | متوافق جداً مع نمط المقاطعة البشرية | تشغيل ذاتي كامل | متوسطة (تحديثات متسارعة لحزم لانج تشين) | ممتازة جداً (Time-travel) | مخاطر تكرار منطق الـ Outbox والمهام |
| **Microsoft Agent Framework** | **`INSPIRE_ONLY`** | متوافق (AutoGen/SK بايثون) | محايد؛ يتطلب كوداً مخصصاً للعزل | يتوافق مع فلاتر الصلاحيات | تشغيل ذاتي كامل | متوسطة (مكتبات ضخمة) | جيدة جداً عبر OpenTelemetry | مخاطر فرض أنماط تصميم ميكروسوفت |
| **Dify** | **`REJECT (Core)` / `INSPIRE (UI)`** | غير متوافق (تطبيق خادم كامل منفصل) | صراع جذري في جداول المستأجرين | غير متوافق مع RBAC المنصة الحالي | يتطلب خوادم وحاويات ضخمة | باهظة (8-12 حاوية وذاكرة 8GB+) | ممتازة داخلياً لكنها معزولة عن نظامنا | تضارب كامل وتكرار بنية النظام كاملاً |
| **n8n** | **`REJECT` (Direct)** | غير متوافق (بيئة Node.js كاملة) | لا يدعم عزل المستأجرين مجاناً | نظام مستخدمين منفصل كلياً | تشغيل ذاتي يخضع لقيود الترخيص | باهظة وخطرة قانونياً (ترخيص تجاري) | جيدة عبر واجهته البصرية | تضارب في إدارة المهام والاتصالات |
| **RagLeap Core** | **`INTEGRATE_SELECTIVELY`** | 100% متوافق (بايثون + pgvector) | صُمم لشركة واحدة ويحتاج تغليف `tenant_id` | يتطابق مع نظام الموافقات الثلاثي | تشغيل ذاتي كامل ومجاني (MIT) | منخفضة جداً | ممتازة ومباشرة في الكود | منخفضة عند استلهام بطاقات الأدوار |

---

## 6. التركيز الخاص: Memento-Skills وحلقة التحسين الذاتي المستمر

يعتبر مفهوم **Memento-Skills** حجر الزاوية في بناء موظف رقمي يتعلم وينمو باستمرار دون الحاجة إلى تدخل المبرمج لكتابة كل أداة يدوياً.

### 6.1 دورة التحسين المحكومة للمهارات خطوة بخطوة

```mermaid
flowchart TD
    A["1. كشف الفجوة (Gap Detection)<br>طلب غير مدعوم أو تكرار فشل خطة"] --> B["2. اقتراح مسودة مهارة (Propose Spec)<br>تحديد المدخلات والمخرجات والشروط"]
    B --> C["3. الفحص الساكن والحظر الأمني (AST Security Verifier)<br>حظر eval, open, imports غير المسموحة"]
    C -->|فشل أمني| X["رفض فوري وتسجيل في سجل التدقيق"]
    C -->|اجتياز| D["4. التنفيذ والاختبار المعزول (Sandbox Execution)<br>تشغيل حالات اختبار في بيئة مؤقتة"]
    D -->|فشل وظيفي| B
    D -->|اجتياز| E{"5. تصنيف المخاطر والحوكمة (Risk Level)"}
    E -->|منخفضة (حسابية)| F["تفعيل تلقائي في سجل الأدوات للمستأجر"]
    E -->|متوسطة / عالية (حساسة/خارجية)| G["إنشاء طلب موافقة للمالك (Pending Approval)"]
    G -->|رفض المالك| Y["أرشفة المهارة"]
    G -->|موافقة المالك| F
    F --> H["6. المراقبة والتحسين (Monitoring & Metrics)<br>تتبع معدل النجاح وزمن الاستجابة"]
    H -->|تكرار أخطاء| I["إلغاء التفعيل والرجوع للإصدار السابق (Rollback)"]
```

### 6.2 تفاصيل مراحل الدورة
1. **كشف الفجوة (Gap Detection):** عندما يطلب مالك المنشأة أمراً لا يوجد له أداة مسجلة في [`ToolRegistry`](file:///d:/AI-Employee-Platform/packages/tools/registry.py) (مثل: حساب ضريبة القيمة المضافة لسلعة معينة، أو تحويل عملات)، يكتشف المحرك الفجوة بدلاً من الهلوسة عبر [`ContinuousImprovementService`](file:///d:/AI-Employee-Platform/packages/self_development/continuous_improvement.py).
2. **صياغة المواصفات (Propose Spec):** يولد الوكيل مواصفة مطابقة لـ [`CapabilitySpecification`](file:///d:/AI-Employee-Platform/packages/self_development/specification.py): اسم الأداة، المعاملات، النوع، وحالات اختبار قياسية (Test Cases).
3. **الفحص الأمني الساكن (AST Security Verifier):** يقوم [`CapabilitySecurityVerifier`](file:///d:/AI-Employee-Platform/packages/self_development/verifier.py) بفحص كود بايثون المقترح شجرة بشجرة (AST)، وتطبيق حظر صارم:
   - منع `eval`، `exec`، `open`، `__import__`، `getattr`، `compile`، واستدعاءات النظام.
   - منع استيراد أي مكتبة خارج القائمة البيضاء المسموحة (`math`، `json`، `re`، `datetime`، `decimal`، `hashlib`).
   > [!IMPORTANT]
   > **مبدأ الأمان المعماري:** **فحص AST ليس بديلاً عن الساندبوكس (Sandbox)، بل هو خط دفاع استباقي أول.** الفحص الساكن يكشف الأنماط الصريحة، بينما الساندبوكس يحمي النظام من أي سلوك تشغيلي غير متوقع أثناء التنفيذ الفعلي للكود.
4. **التنفيذ والاختبار في الساندبوكس المعزول (Sandbox Execution):**
   - يشغل [`ExecutionSandbox`](file:///d:/AI-Employee-Platform/packages/self_development/sandbox.py) الكود في عملية فرعية معزولة ومقيدة الموارد مع وقت زمني صارم (Timeout).
   - **تجريد الأسرار وحماية البيئة:** يُجرد الساندبوكس تماماً من أي متغيرات بيئة حساسة تخص المضيف (مثل `DATABASE_URL`، `JWT_SECRET_KEY`، مفاتيح مزودي الذكاء الاصطناعي، وبيانات الاعتماد).
   - **منع الوصول للملفات والشبكة وقاعدة البيانات:** لا يُمنح كود المهارة أي وصول لنظام الملفات المحلي، أو الاتصال بقاعدة البيانات، أو فتح مقابس شبكية (Sockets).
5. **تصنيف المخاطر وبوابة الموافقة (Approval Gate):**
   - *أدوات منخفضة المخاطر (Low Risk):* أدوات حسابية ومعالجة نصوص لا تستدعي شبكة خارجية -> تُفعل تلقائياً بعد اجتياز الاختبارات.
   - *أدوات متوسطة/عالية المخاطر (Medium/High Risk):* أدوات تطلب استدعاء Webhook خارجي أو توليد مستندات -> يُنشأ لها طلب اعتماد معلق برقم UUID في [`approvals`](file:///d:/AI-Employee-Platform/packages/models/domain.py) ولا تُفعل إلا بعد موافقة المالك صراحة.
6. **التسجيل وتتبع الإصدارات والتراجع (Versioning & Rollback):**
   - تُسجل في [`CapabilityVersion`](file:///d:/AI-Employee-Platform/packages/models/domain.py) برقم إصدار تصاعدي وتُربط حصرياً بـ `tenant_id`.
   - تدعم دالة [`disable_or_rollback`](file:///d:/AI-Employee-Platform/packages/self_development/engine.py) الرجوع الفوري للإصدار السابق إذا لوحظ تراجع في الأداء أو تكرار الأخطاء.

### 6.3 الفصل الصارم بين مستويات التغيير (Separation of Concerns)

1. **التعلم المعلوماتي (Information Learning):**
   - تعديل بيانات الكتالوج، الهوية، الأسعار، السياسات، ساعات العمل.
   - يتم تخزينه مباشرة في [`BusinessBrain`](file:///d:/AI-Employee-Platform/packages/models/domain.py) و[`Knowledge`](file:///d:/AI-Employee-Platform/packages/models/domain.py).
   - لا يتضمن أي كود برمجي؛ آمن بنسبة 100%.
2. **تحسين إعدادات وسلوك الوكيل (Agent Tuning):**
   - تعديل درجة الإيجاز، اللهجة، التعليمات المخصصة للمستأجر، تفضيلات الرد.
   - يتم في جدول [`agents`](file:///d:/AI-Employee-Platform/packages/models/domain.py)؛ آمن ومحكوم بسياسات المستأجر.
3. **إضافة مهارات ديناميكية (Dynamic Skills Creation):**
   - توليد أدوات برمجية جديدة (مثل حاسبة رسوم جمركية، محول عملات، مدقق صيغ).
   - تعمل حصرياً داخل الساندبوكس، وتخضع للفحص، ولا تُفعل إذا كانت خطرة إلا بموافقة المالك.
4. **تعديل كود المنصة الأساسي (Core Engine Modification):**
   - **محظور حظراً تاماً ومطلقاً على الوكلاء الرقميين.**
   - كود المنصة الأساسي (FastAPI routers, database schema, auth, outbox worker) لا يُعدل إلا عبر المطور البشري بواسطة Pull Requests خاضعة للمراجعة واختبارات CI/CD الكاملة.

---

## 7. التوصية المعمارية المستهدفة (Target Architecture Recommendation)

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 AI EMPLOYEE TARGET ARCHITECTURE                                 │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                     OMNI-CHANNEL TOUCHPOINTS                                    │
│  Telegram Bot (Owner/Customer) │ WhatsApp Cloud API │ Webhooks │ Tenant & Admin Dashboards      │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                      TENANT CONTEXT & RBAC                                      │
│           JWT Auth │ Row-Level Tenant Isolation │ AES-256-GCM Secrets Encryption                │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│                              STATEFUL AGENT ORCHESTRATION ENGINE                                │
│       Unified State Machine │ Owner Intent Router │ Customer Support Router                     │
│       Role & Autonomy Controls (Off / Semi-Autonomous / Fully Autonomous)                      │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│               DYNAMIC SKILLS & CONTINUAL LEARNING RUNTIME (Memento-Inspired)                   │
│       Gap Detection ──> AST Verifier ──> Isolated Sandbox ──> Approval Gate ──> Tool Registry  │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│                             DURABLE TASK & OUTBOX WORKER ENGINE                                 │
│       Transactional Outbox (SKIP LOCKED) │ Background Dispatch │ Exponential Backoff │ Metrics  │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│                            TENANT ISOLATED KNOWLEDGE & MEMORY BRAIN                             │
│       BusinessBrain (SSOT) │ Knowledge Base │ Long-Term Memories │ Conversation Transcripts     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 8. الفجوة المعمارية الأولى ذات الأولوية القصوى (Top Priority Capability Gap)

بعد المقارنة المعمارية الشاملة للأدلة والتبعيات، تم اختيار الفجوة التالية كـ **أعلى أولوية تنفيذية فورية**:

### **العنوان: إحكام حلقة Memento-Skills التفاعلية: ربط كشف الفجوة بتوليد المهارة وساندبوكس الاختبار واعتماد المالك عبر قنوات الاتصال**

#### 1. لماذا هذه الفجوة هي الأولوية القصوى؟
- **الأثر العملي على صفة "الموظف":** حالياً، إذا طلب المالك من البوت مهمة حسابية أو إدارية لا تملك أداة مسجلة، يعتذر الموظف أو يوجهه للدعم كأنه شات بوت تقليدي. سد هذه الفجوة يحول الموظف إلى كيان مستقل حقيقي قادر على بناء قدراته واختبارها واقتراحها للمالك مباشرة.
- **اكتمال المتطلبات المسبقة:** جميع قطع البنية التحتية المطلوبة لهذه القدرة مبنية ومختبرة بالفعل في المستودع (الساندبوكس، فاحص AST، سجل الأدوات، نظام الموافقات، وقنوات التيليجرام)، والفجوة تكمن فقط في "حلقة الربط التفاعلية" بين هذه المكونات.

#### 2. ما الموجود حالياً في المشروع؟
- محرك التطوير الذاتي [`SelfDevelopmentEngine`](file:///d:/AI-Employee-Platform/packages/self_development/engine.py) موجود ومختبر بـ [`test_phase17_self_development.py`](file:///d:/AI-Employee-Platform/tests/test_phase17_self_development.py).
- فاحص الأمان [`CapabilitySecurityVerifier`](file:///d:/AI-Employee-Platform/packages/self_development/verifier.py) وبيئة الساندبوكس [`ExecutionSandbox`](file:///d:/AI-Employee-Platform/packages/self_development/sandbox.py) يعملان بكفاءة.
- محرك المحادثة [`ConversationalAgentEngine`](file:///d:/AI-Employee-Platform/packages/services/conversational_agent_engine.py) يحتوي على كود مبدئي لـ `_check_and_handle_capability_gap` لكنه غير مربوط بحلقة طلب الاعتماد اللحظي عبر رسائل التيليجرام.

#### 3. ما التغيير المحدد المطلوب؟
1. تفعيل خطاف الربط (Hook) داخل `ConversationalAgentEngine._check_and_handle_capability_gap`؛ بحيث إذا كشف طلباً لمهارة مفقودة من المالك، يستدعي تلقائياً `SelfDevelopmentEngine.create_development_request` و`develop_and_test`.
2. إذا اجتاز الكود الساندبوكس، يُنشئ النظام تلقائياً طلب موافقة `Approval`، ويرسل رداً فورياً للمالك على القناة:
   > *"⚠️ اكتشفت أن هذه العملية تتطلب قدرة حسابية جديدة. قمت ببرمجتها واختبارها في بيئة معزولة بنجاح. للاعتماد والتفعيل، يرجى الرد بـ: 'أوافق على تفعيل الأداة [slug]'."*
3. عند رد المالك بالموافقة، تُفعل الأداة في `ToolRegistry` وتُستأنف المهمة الأصلية ويُعرض الناتج الحسابي فوراً.

#### 4. ما الملفات أو المكونات المتأثرة مبدئياً؟
- [`packages/services/conversational_agent_engine.py`](file:///d:/AI-Employee-Platform/packages/services/conversational_agent_engine.py): استكمال دالة ربط الفجوة واستئناف الهدف المعلق (`pending_goal`).
- [`packages/self_development/engine.py`](file:///d:/AI-Employee-Platform/packages/self_development/engine.py): ضمان تسجيل الأداة المفعلة في سجل أدوات المستأجر فور الموافقة.
- [`apps/admin-dashboard/src/pages/TenantDetailPage.tsx`](file:///d:/AI-Employee-Platform/apps/admin-dashboard/src/pages/TenantDetailPage.tsx) و[`apps/tenant-dashboard/src/pages/ChannelsPage.tsx`](file:///d:/AI-Employee-Platform/apps/tenant-dashboard/src/pages/ChannelsPage.tsx): إضافة حقول `owner_telegram_id` و`owner_phone` في نماذج قنوات الاتصال لضمان التعرف الدائم على المالك.

#### 5. ما اختبار القبول (Acceptance Test) الذي يثبت اكتمالها؟
- كتابة اختبار تكاملي شامل ينفذ السيناريو التالي:
  1. إرسال المالك رسالة عبر قناة تيليجرام: *"احسب لي زكاة عسل السدر لكمية 50 كيلو بسعر 200 ريال للكيلو بنسبة 2.5%"*.
  2. تأكيد إنشاء `DevelopmentRequest` و`DevelopmentRun` ونجاح فحص AST واختبار الساندبوكس.
  3. تأكيد إنشاء سجل `Approval` معلق وتلقي المالك لرسالة طلب الاعتماد برقم المعرف.
  4. إرسال المالك: *"أوافق على الطلب [approval_id]"*.
  5. التحقق من تفعيل المهارة واستئناف الحساب وصدور النتيجة الدقيقة للمالك فوراً: *"إجمالي الزكاة الواجبة: 250 ريال"*.

#### 6. كيف نتجنب تكرار مكونات موجودة بالفعل؟
- عدم إعادة كتابة ساندبوكس جديد؛ استخدام [`ExecutionSandbox`](file:///d:/AI-Employee-Platform/packages/self_development/sandbox.py) القائم.
- عدم إعادة كتابة فاحص أمني؛ استخدام [`CapabilitySecurityVerifier`](file:///d:/AI-Employee-Platform/packages/self_development/verifier.py) القائم.
- عدم إنشاء جدول موافقات جديد؛ استخدام جدول [`approvals`](file:///d:/AI-Employee-Platform/packages/models/domain.py) و[`ApprovalService`](file:///d:/AI-Employee-Platform/packages/services/approval_service.py) المعتمد.

---

## 9. التغييرات المطلوبة وأولوياتها (Prioritized Architecture Changes)

| الأولوية | التغيير المعماري المطلوب | المبرر الفني والفوائد | المكونات المتأثرة |
|---|---|---|---|
| **P0 (قصوى)** | إحكام حلقة Memento-Skills التفاعلية للقدرات الديناميكية | تمكين الموظف من سد فجواته واكتساب الأدوات واختبارها ذاتياً بموافقة المالك اللحظية. | [`packages/self_development`](file:///d:/AI-Employee-Platform/packages/self_development), [`conversational_agent_engine.py`](file:///d:/AI-Employee-Platform/packages/services/conversational_agent_engine.py) |
| **P0 (قصوى)** | إضافة حقول معرّف المالك في واجهات قنوات الاتصال | القضاء التام على مشكلة معاملة المالك كزبون وضمان الربط الفوري لـ `owner_identifiers`. | [`TenantDetailPage.tsx`](file:///d:/AI-Employee-Platform/apps/admin-dashboard/src/pages/TenantDetailPage.tsx), [`ChannelsPage.tsx`](file:///d:/AI-Employee-Platform/apps/tenant-dashboard/src/pages/ChannelsPage.tsx) |
| **P1 (عالية)** | توحيد آلة الحالة (Unified State Machine) ونقاط التوقف | دمج مسار أوركسترا المهام مع مسار المحادثات، ودعم استئناف المهام المعلقة بعد الموافقة البشرية (`Resume`). | [`agent_orchestrator.py`](file:///d:/AI-Employee-Platform/packages/services/agent_orchestrator.py), [`task_execution_service.py`](file:///d:/AI-Employee-Platform/packages/services/task_execution_service.py) |
| **P1 (عالية)** | إضافة درجات الاستقلالية الثلاثية للموظف (`off`, `semi`, `full`) | حماية المنشأة من أي تصرف غير مقصود للموظف وضبط صلاحيات التنفيذ التلقائي للأدوات التجارية. | [`packages/models/domain.py`](file:///d:/AI-Employee-Platform/packages/models/domain.py), [`action_policy_service.py`](file:///d:/AI-Employee-Platform/packages/services/action_policy_service.py) |
| **P2 (متوسطة)**| تفعيل البحث الدلالي الهجين للكتالوج الكبير عبر `pgvector` | الحفاظ على سرعة ودقة استرجاع المنتجات عندما يتجاوز كتالوج المستأجر آلاف الأصناف. | [`packages/context/retriever.py`](file:///d:/AI-Employee-Platform/packages/context/retriever.py), [`business_brain_service.py`](file:///d:/AI-Employee-Platform/packages/services/business_brain_service.py) |
| **P2 (متوسطة)**| شاشات إدارة الذاكرة وقاعدة المعرفة في لوحة المستأجر | إعطاء مالك المنشأة شفافية كاملة لرؤية الذكريات المسجلة وتصحيحها أو حذفها بنقرة زر. | [`apps/tenant-dashboard`](file:///d:/AI-Employee-Platform/apps/tenant-dashboard) |
| **P3 (منخفضة)**| خدمة التقييم المستمر وإحصائيات الجودة للمنصة | حساب معدل دقة الموظف في إرضاء العملاء واستخراج الأسئلة المتكررة التي لم تجد إجابة. | [`packages/services/audit_service.py`](file:///d:/AI-Employee-Platform/packages/services/audit_service.py) |

---

## 10. المخاطر والاعتماديات (Risks & Dependencies)

1. **المخاطر الأمنية:**
   - *خطر توليد كود خبيث:* محاولة الموظف كتابة كود يقرأ أسرار النظام.
   - *العلاج:* التحليل الساكن عبر AST وحظر كل دوال الإدخال/الإخراج والشبكة، وتجريد متغيرات البيئة في الساندبوكس.
2. **المخاطر التشغيلية:**
   - *تنافس معالجة الـ Outbox:* احتمال استهلاك نفس الحدث من خوادم متعددة.
   - *العلاج:* قفل الصفوف الصارم `FOR UPDATE SKIP LOCKED` والالتزام بحدود التراجع الأسي (Exponential Backoff).
3. **مخاطر عزل المستأجرين:**
   - *تسرب بيانات بين المنشآت.*
   - *العلاج:* عدم كتابة أي استعلام بدون تضمين `tenant_id`، وفرض `TenantContext` على مستوى طبقة البيانات وخدمات الذاكرة.
4. **مخاطر الرخص والاعتماد الخارجي:**
   - *العلاج:* الالتزام الصارم بعدم إدخال n8n أو Dify داخل كود المنصة للحفاظ على الملكية الفكرية والحرية التجارية.

---

## 11. خطة التنفيذ التفصيلية والمراحل القادمة (Implementation Roadmap)

```mermaid
flowchart LR
    P1["المرحلة 1:<br>إحكام حلقة المهارات وتكامل القنوات"] --> P2["المرحلة 2:<br>توحيد آلة الحالة ونقاط التوقف"]
    P2 --> P3["المرحلة 3:<br>تصنيف الأدوار ودرجات الاستقلالية"]
    P3 --> P4["المرحلة 4:<br>لوحات المؤشرات والتقييم المستمر"]
```

### المرحلة الأولى: إحكام حلقة Memento-Skills وتكامل مدخلات القنوات (الأولوية القصوى)
- **المهام:**
  1. تحديث واجهة إضافة القنوات في لوحتي التحكم لإتاحة إدخال معرف المالك (`owner_telegram_id` / `owner_phone`) مباشرة وحفظه مشفراً.
  2. ربط طلبات المالك في المحادثة مباشرة مع `SelfDevelopmentEngine` عندما يطلب عملية حسابية أو أداة غير متوفرة، وتوليد مسودة المهارة وعرضها للموافقة.
- **معيار القبول (Acceptance Criteria):**
  - إضافة قناة تيليجرام جديدة من واجهة الإدارة وإدخال معرف المالك بنجاح.
  - إرسال المالك طلباً لحساب الضريبة من تيليجرام، وتوليد الأداة في الساندبوكس، وطلب اعتماده، واستئناف التنفيذ فور قوله "أوافق".

### المرحلة الثانية: توحيد آلة الحالة ونقاط التوقف والاستئناف (LangGraph Pattern)
- **المهام:**
  1. توحيد دورة حياة تنفيذ المهام المركبة في محرك موحد يدعم حفظ وتثبيت الحالة في جدول `tasks` عند كل خطوة.
  2. تمكين استئناف المهام المعلقة بعد الموافقة البشرية بدقة متناهية (`Durable Resume`) دون إعادة تنفيذ الخطوات السابقة.
- **معيار القبول (Acceptance Criteria):**
  - إنشاء مهمة تتطلب 3 خطوات (استعلام -> اعتماد بشري -> إرسال خارجي).
  - إثبات توقف المهمة عند الخطوة 2 ودخولها حالة `awaiting_approval`، ثم استئنافها وتنفيذ الخطوة 3 فقط فور صدور الاعتماد.

### المرحلة الثالثة: تصنيف الأدوار الوظيفية ودرجات الاستقلالية (RagLeap Pattern)
- **المهام:**
  1. إضافة مصفوفة الاستقلالية الثلاثية للموظف في جدول `agents`:
     - `off`: وضع الاستماع فقط والمساعدة الداخلية.
     - `semi`: وضع الموافقة الإلزامية لكل إجراء خارجي (الوضع الافتراضي الأكثر أماناً).
     - `full`: وضع الاستقلالية الكاملة للإجراءات الآمنة مع قفل الإجراءات الحساسة بسياسات `ActionPolicy`.
  2. تجهيز نماذج أدوار وظيفية جاهزة (Sales Representative, Customer Care, Operations Manager).
- **معيار القبول (Acceptance Criteria):**
  - في وضع `semi`، يمتنع الموظف عن إرسال أي بريد أو إنشاء أي مهمة دون طلب موافقة.
  - في وضع `full`، ينفذ الموظف الردود والأدوات غير الحساسة ذاتياً، ويطلب الموافقة فقط للعمليات الحساسة (مثل الحذف أو الخصومات الكبيرة).

### المرحلة الرابعة: لوحات التقييم المستمر وإدارة الذاكرة في الواجهات
- **المهام:**
  1. إضافة شاشات إدارة الذاكرة وقاعدة المعرفة وتصحيحها في لوحة المستأجر (`Tenant Dashboard`).
  2. بناء خدمة قياس الجودة والتقييم الدوري (`EvaluationService`) لعرض نسبة نجاح المهام ودقة الردود في لوحة المنصة.
- **معيار القبول (Acceptance Criteria):**
  - قدرة مالك المنشأة على استعراض الذكريات المسجلة وحذف أو تصحيح أي ذكرى بنقرة زر واحدة.
  - عرض رسم بياني في لوحة التحكم يوضح عدد المهام المنجزة ومعدل الأخطاء وزمن استجابة النموذج.

---

## 12. القرارات المعمارية المثبتة رسمياً (Confirmed Architectural Decisions)

1. **اعتماد النمط الداخلي للمهارات (Memento-Skills Pattern):**
   - تطوير نظام مواصفات المهارات ذاتياً داخل [`packages/self_development`](file:///d:/AI-Employee-Platform/packages/self_development) مع فاحص AST وساندبوكس عزل بيئي، دون إضافة حزم خارجية إلى النواة في هذه المرحلة.
2. **استبعاد Dify و n8n كلياً من بنية المنصة وحاوياتها:**
   - الحفاظ على سيادة البيانات، وعزل المستأجرين، وتجنب ازدواجية التقنيات والقيود القانونية للتراخيص.
3. **مستوى استقلالية الساندبوكس:**
   - استخدام نمط Subprocess المعزول مع تجريد الأسرار وفحص AST حالياً في التطوير، مع توفير خيار الحاويات المنعزلة شبكياً (`--network none`) للإنتاج.
4. **حوكمة العمليات الحساسة:**
   - العمليات الحساسة (الحذف المجمع وتعديل الأسعار الكبرى وتصفير البيانات) تتطلب دوماً موافقة صريحة من المالك برقم المعرف UUID مهما كانت درجة استقلالية الموظف.

---

## 13. قائمة البنود التي تعذر التحقق منها تشغيلياً (Unverified Items)

- **الاتصال الحقيقي بـ WhatsApp Cloud API:** تم التحقق واختبار موصل الواتساب عبر المحاكاة الشاملة والوحدات الاختبارية (`WhatsAppCloudConnector`) وتشفير التوكنات، لكن لم يتم ربط رقم هاتف حقيقي فعلي على خوادم Meta لصعوبة توفير شريحة ورقم تجاري في بيئة الاختبار المحلية (تم التحقق التام بنجاح من تيليجرام فعلياً).
- **التشغيل الموزع عبر عدة خوادم (Multi-Node Celery/Redis Outbox Worker):** يعمل `OutboxWorker` حالياً بكفاءة تامة على خادم واحد بحاوية Docker ويعتمد `FOR UPDATE SKIP LOCKED`. التحقق من أداء قفل التنافسية عند وجود 10 خوادم متزامنة لم يتم إجراؤه في هذه المرحلة.

---

المستند محفوظ بالكامل وجاهز في: [`docs/ARCHITECTURE_INTELLIGENCE_REVIEW.md`](file:///d:/AI-Employee-Platform/docs/ARCHITECTURE_INTELLIGENCE_REVIEW.md).
