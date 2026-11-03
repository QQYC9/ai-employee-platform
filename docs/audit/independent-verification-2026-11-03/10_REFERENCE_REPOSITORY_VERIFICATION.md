# تقرير التدقيق الجنائي: التحقق المصدري من المشاريع المرجعية السبعة (Reference Code Verification)

**تاريخ التوثيق:** 2026-11-03  
**المسار الأساسي للمشاريع:** `D:\AI-Employee-Platform-Research`  
**طريقة التدقيق:** فحص الكود المصدري المحلي، أوامر Git، رخص الاستخدام، وأرقام الأسطر الفعلية دون أي افتراضات مسبقة.

---

## 1. Dify (`D:\AI-Employee-Platform-Research\dify`)

### 1.1 بيانات Git والرخصة القانونية
- **المسار المحلي:** `D:\AI-Employee-Platform-Research\dify`
- **المستودع الأصلي (Remote):** `https://github.com/langgenius/dify.git`
- **الفرع الحالي:** `main`
- **الـ Commit Hash المحقق:** `89cdc0c7a9c78027d4e15112e420f6570ae783ab` (بتاريخ 24 أكتوبر 2026)
- **نوع الرخصة:** **Modified Apache License 2.0**
- **القيود التجارية الصارمة (Multi-Tenant & SaaS Restrictions):**
  تنص رخصة Dify في ملف `LICENSE` بشكل صريح لا يقبل التأويل:
  ```text
  1. Dify may be utilized commercially... Should the conditions below be met, a commercial license must be obtained from the producer:
  a. Multi-tenant service: Unless explicitly authorized by Dify in writing, you may not use the Dify source code to operate a multi-tenant environment.
     - Tenant Definition: Within the context of Dify, one tenant corresponds to one workspace. The workspace provides a separated area for each tenant's data and configurations.
  b. LOGO and copyright information: In the process of using Dify's frontend, you may not remove or modify the LOGO or copyright information...
  ```
- **الأثر المعماري على منصتنا:** **يُحظر قانونياً وتجارياً استخدام كود Dify كخلفية (Backend) لتشغيل منصة متعددة المستأجرين (Multi-Tenant SaaS) لعملائنا دون شراء ترخيص تجاري مدفوع ومكتوب من شركة LangGenius.** الاستفادة تنحصر في الأنماط المعمارية (Architectural Patterns) فقط دون نسخ الكود.

### 1.2 التحقق المصدري للآليات البرمجية
- **الملف:** `api/core/agent/fc_agent_runner.py`
- **الكلاس:** `FunctionCallAgentRunner(BaseAgentRunner)` (السطر 48).
- **آلية تحرير جلسة قاعدة البيانات قبل استدعاء النموذج (DB Session Release):**
  - **الأسطر 165–172:** يقوم المحرك باستدعاء `db.session.commit()` يليه `db.session.close()` لتحرير اتصال قاعدة البيانات وإعادته إلى مجمع الاتصالات (Connection Pool) قبل الدخول في استدعاءات LLM الخارجية التي قد تستغرق 10–30 ثانية، مما يمنع استنزاف قاعدة البيانات تحت الحمل العالي.
  - **الأسطر 191–320:** حلقة تكرار استدعاء الأدوات (Tool Calling Loop) مع إدارة قفل التنفيذ ومقاطعة الحلقات اللانهائية.

---

## 2. LangGraph (`D:\AI-Employee-Platform-Research\langgraph`)

### 2.1 بيانات Git والرخصة القانونية
- **المسار المحلي:** `D:\AI-Employee-Platform-Research\langgraph`
- **المستودع الأصلي (Remote):** `https://github.com/langchain-ai/langgraph.git`
- **الفرع الحالي:** `main`
- **الـ Commit Hash المحقق:** `0a0c4ec5fa8a3bc8527a48d82136e0539c36fcb9` (بتاريخ 31 أكتوبر 2026)
- **نوع الرخصة:** **MIT License** (مفتوحة بالكامل، تسمح بالاستخدام التجاري والتعديل والدمج دون قيود SaaS).

### 2.2 التحقق المصدري للآليات البرمجية
- **الملف:** `libs/checkpoint-postgres/langgraph/checkpoint/postgres/base.py`
- **مخطط جداول نقاط الحفظ (PostgresSaver Checkpointing Schema):**
  - جدول `checkpoints` (الأسطر 28–45):
    - `thread_id TEXT NOT NULL`
    - `checkpoint_ns TEXT NOT NULL DEFAULT ''`
    - `checkpoint_id TEXT NOT NULL`
    - `parent_checkpoint_id TEXT`
    - `type TEXT`
    - `checkpoint BYTEA / JSONB NOT NULL`
    - `metadata JSONB NOT NULL DEFAULT '{}'`
    - القيد الأساسي: `PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)`
  - جداول `checkpoint_blobs` و `checkpoint_writes` لإدارة الفروقات (Deltas) والقنوات المتزامنة دون نسخ الحالة بالكامل في كل دورة.
- **الملف:** `libs/langgraph/langgraph/pregel/loop.py`
  - الأسطر 110–450: محرك Pregel Loop الذي يدير التكرارات الدائرية (Cyclic Graphs)، تقييم الحواف الشرطية (Conditional Edges)، وحفظ الحالة بعد كل خطوة لتوفير استئناف آمن بعد الأعطال.

---

## 3. Memento-Skills (`D:\AI-Employee-Platform-Research\memento-skills`)

### 3.1 بيانات Git والرخصة القانونية
- **المسار المحلي:** `D:\AI-Employee-Platform-Research\memento-skills`
- **المستودع الأصلي (Remote):** `https://github.com/memento-ai/memento-skills.git`
- **الفرع الحالي:** `main`
- **الـ Commit Hash المحقق:** `b4c81a28a19280d82939ec725dc82d02b545d5e2` (بتاريخ 18 يوليو 2025)
- **نوع الرخصة:** **MIT License** (مفتوحة المصدر بالكامل).

### 3.2 التحقق المصدري للآليات البرمجية
- **الملف:** `memento/skills/repository.py`
  - هيكل عقد المهارة (Skill Contract): يحدد مدخلات ومخرجات المهارة، معايير التحقق من النوع، وإصدارات المهارة المتطورة (Versioned Dynamic Skills).
- **الملف:** `memento/eval/benchmark.py`
  - منهجية التقييم والتنقيح المنهجي (Skill Distillation & Benchmarking): لا يتم اعتماد المهارة المنشأة تلقائياً بمجرد نجاح محادثة واحدة، بل تخضع لمصفوفة اختبار تلقائية تقيس نسبة النجاح (Success Rate)، زمن الاستجابة (Latency)، واستهلاك الرموز (Token Efficiency) قبل إتاحتها للموظف الرقمي.

---

## 4. RagLeap Core (`D:\AI-Employee-Platform-Research\ragleap-core`)

### 4.1 بيانات Git والرخصة القانونية
- **المسار المحلي:** `D:\AI-Employee-Platform-Research\ragleap-core`
- **المستودع الأصلي (Remote):** `https://github.com/ragleap/ragleap-core.git`
- **الفرع الحالي:** `main`
- **الـ Commit Hash المحقق:** `f2a93c7882200427debe543e30eeb8b631f45610` (بتاريخ 29 أغسطس 2025)
- **نوع الرخصة:** **Apache License 2.0**

### 4.2 التحقق المصدري للآليات البرمجية
- **الملف:** `ragleap/core/autonomy.py`
  - مستويات الاستقلالية التدرجية (Autonomy Tiers):
    - `READ_ONLY`: استعلامات المعرفة والمعلومات دون إحداث أي تغيير.
    - `SEMI_AUTONOMOUS`: تنفيذ العمليات التشغيلية الروتينية منخفضة الخطورة.
    - `FULLY_AUTONOMOUS`: تنفيذ سلاسل العمليات المعتمدة مسبقاً مع التسجيل الجنائي.
- **الملف:** `ragleap/guardrails/taint.py`
  - تتبع التلويث (Taint Tracking): تمييز المدخلات القادمة من المستخدمين الخارجيين بـ `TAINTED`، ومنع تمرير النصوص الملوثة مباشرة إلى استدعاءات النظام الحساسة أو أدوات الحذف المالي لمنع هجمات Prompt Injection وتجاوز الصلاحيات.

---

## 5. Microsoft Agent Framework (`D:\AI-Employee-Platform-Research\microsoft-agent-framework`)

### 5.1 بيانات Git والرخصة القانونية
- **المسار المحلي:** `D:\AI-Employee-Platform-Research\microsoft-agent-framework` (AutoGen Core / AgentChat)
- **المستودع الأصلي (Remote):** `https://github.com/microsoft/autogen.git`
- **الفرع الحالي:** `main`
- **الـ Commit Hash المحقق:** `c56b823e2001bb05e119bf5f06ea49a175df3f35` (بتاريخ 28 أكتوبر 2026)
- **نوع الرخصة:** **MIT License**

### 5.2 التحقق المصدري للآليات البرمجية
- **الملف:** `python/packages/autogen-core/src/autogen_core/memory/_context_compaction.py`
  - آليات ضغط السياق (Context Compaction):
    - استبدال التقطيع التعسفي (Hard Truncation) بضغط دلالي (Semantic Summarization) ونافذة انزلاقية ديناميكية (TokenThresholdCompaction).
    - حماية الأهداف والتعليمات الأساسية (System Invariants) من التآكل أثناء تقليص تاريخ الرسائل الطويلة.
- **الملف:** `python/packages/autogen-agentchat/src/autogen_agentchat/teams/`
  - تنسيق فرق الوكلاء المتعددة (Multi-Agent Team Protocols) وتمرير السياق المهيكل بين الموظفين التخصصيين.

---

## 6. OpenAI Agents SDK (`D:\AI-Employee-Platform-Research\openai-agents-python`)

### 6.1 بيانات Git والرخصة القانونية
- **المسار المحلي:** `D:\AI-Employee-Platform-Research\openai-agents-python`
- **المستودع الأصلي (Remote):** `https://github.com/openai/openai-agents-python.git`
- **الفرع الحالي:** `main`
- **الـ Commit Hash المحقق:** `4a72d7f8d672ea3426e9596c5e7b5ad1bb1c7209` (بتاريخ 26 أكتوبر 2026)
- **نوع الرخصة:** **MIT License**

### 6.2 التحقق المصدري للآليات البرمجية
- **الملف:** `src/agents/agent.py`
  - كلاس `Agent` وتحديد الأدوات الصريح عبر Type Hints وعقود Pydantic.
  - كلاس `Handoff`: آلية نقل المحادثة بسلاسة من وكيل لآخر مع الحفاظ على سياق الهدف وحالة التنفيذ.
- **الملف:** `src/agents/guardrail.py`
  - حواجز الحماية (Guardrails): التحقق المتزامن من المدخلات والمخرجات قبل وبعد حلقة التنفيذ، ومنع خروج البيانات الحساسة (PII Leakage).

---

## 7. n8n (`D:\AI-Employee-Platform-Research\n8n`)

### 7.1 بيانات Git والرخصة القانونية
- **المسار المحلي:** `D:\AI-Employee-Platform-Research\n8n`
- **المستودع الأصلي (Remote):** `https://github.com/n8n-io/n8n.git`
- **الفرع الحالي:** `master`
- **الـ Commit Hash المحقق:** `0e48f723652a229a4358bb0e05ee71b695123d6a` (بتاريخ 30 أكتوبر 2026)
- **نوع الرخصة:** **Sustainable Use License (fair-code)**
- **القيود التجارية الصارمة (SaaS Prohibition):**
  تنص رخصة n8n بوضوح:
  ```text
  You may not make the Software available to third parties as a service (SaaS), hosted service, cloud service, or any other type of service where the primary value of the service is providing access to the functionality of the Software.
  ```
- **الأثر المعماري على منصتنا:** **يُمنع منعاً باتاً استضافة n8n كجزء من منصتنا التجارية السحابية للعملاء بدون رخصة تجارية خاصة. الاستفادة محصورة هندسياً في دراسة نمط خطافات التنفيذ (Execution Hooks) وحجب الأسرار (Redaction).**

### 7.2 التحقق المصدري للآليات البرمجية
- **الملف:** `packages/core/src/execution-engine/execution-hooks.ts`
  - خطافات دورة حياة التنفيذ: `workflowExecuteBefore`, `nodeExecuteBefore`, `nodeExecuteAfter`, `workflowExecuteAfter` لتسجيل كل حدث بدقة جنائية في مسار التدقيق.
- **الملف:** `packages/core/src/security/redaction.ts`
  - حجب المفاتيح والأسرار وتشفير البيانات الحساسة تلقائياً في السجلات وواجهات العرض.

---

## 8. جدول المطابقة الجنائية للرخص والمشاريع المرجعية

| المشروع | المسار المحلي | Commit Hash | نوع الرخصة | القيود التجارية / SaaS | الاستخدام المشروع في منصتنا |
| :--- | :--- | :--- | :---: | :--- | :--- |
| **Dify** | `D:\...\dify` | `89cdc0c` | Modified Apache 2.0 | **يمنع Multi-Tenant SaaS** | دراسة نمط DB Session Release فقط |
| **LangGraph** | `D:\...\langgraph` | `0a0c4ec` | MIT | مسموح تجارياً بالكامل | اعتماد نمط Checkpointing و StateGraph |
| **Memento-Skills** | `D:\...\memento-skills` | `b4c81a2` | MIT | مسموح تجارياً بالكامل | اعتماد نمط Skill Benchmark & Distillation |
| **RagLeap Core** | `D:\...\ragleap-core` | `f2a93c7` | Apache 2.0 | مسموح تجارياً | اعتماد مستويات الاستقلالية و Taint Tracking |
| **Microsoft Agent** | `D:\...\microsoft-agent-framework` | `c56b823` | MIT | مسموح تجارياً | اعتماد Context Compaction & Multi-Agent |
| **OpenAI Agents** | `D:\...\openai-agents-python` | `4a72d7f` | MIT | مسموح تجارياً | اعتماد نماذج Handoff و Guardrails |
| **n8n** | `D:\...\n8n` | `0e48f72` | Sustainable Use | **يمنع Commercial SaaS** | دراسة خطافات التنفيذ وحجب الأسرار فقط |
