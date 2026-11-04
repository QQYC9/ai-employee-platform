# البحث المعماري المتعمق في المشاريع المرجعية السبعة (Reference Projects Research)
## 06_REFERENCE_PROJECTS_RESEARCH.md

- **تاريخ التوثيق والتحديث الميداني:** 2026-11-03T03:18:00+03:00
- **بيئة البحث:** المستودعات الأصلية المحلية في `D:\AI-Employee-Platform-Research`
- **المنهجية:** فحص الكود المصدري الأصلي سطراً بسطر في الملفات المحورية، وتثبيت الـ Commit والترخيص وتتبع مسارات التشغيل بالأدلة البرمجية القاطعة.

---

### المشروع 1: LangGraph (LangChain AI)
* **المستودع الرسمي:** `https://github.com/langchain-ai/langgraph.git`
* **الالتزام المثبت:** `4c52e129eb1ab69a3da58b799f67929f77d81149` (Release 1.2.17)
* **الترخيص القانوني:** **MIT License** (مفتوح المصدر بالكامل ومسموح بالاستخدام التجاري دون قيود).
* **الملفات المفحوصة في الكود الفعلي:**
  1. `libs/checkpoint-postgres/langgraph/checkpoint/postgres/base.py` (الأسطر 45–80)
  2. `libs/checkpoint-postgres/langgraph/checkpoint/postgres/aio.py` (الأسطر 250–310, 418–450)
  3. `libs/langgraph/langgraph/types.py` (الأسطر 903–1047)
  4. `libs/langgraph/langgraph/pregel/_algo.py` (الأسطر 156–186)
* **الأدلة البرمجية ومسارات التشغيل المثبتة بالكود:**
  - **مخطط الجداول الثلاثة في PostgreSQL (`base.py:45-80`):**
    - جدول `checkpoints`: المفتاح الأساسي `PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)`.
    - جدول `checkpoint_blobs`: المفتاح الأساسي `PRIMARY KEY (thread_id, checkpoint_ns, channel, version)` لتخزين البيانات الكبيرة دون تكرار (Deduplication).
    - جدول `checkpoint_writes`: لحفظ الكتابات الوسيطة لكل مهمة بشكل ذري.
  - **الذرية وسرعة خطوط الأنابيب (`aio.py:250-310`):**
    - تفصل الدالة `aput` القيم البسيطة لتُخزن في حقل `jsonb`، وتضع الكتل الكبيرة في `checkpoint_blobs`.
    - في حال دعم قاعدة البيانات للـ Pipeline، تُنفذ العمليات عبر `cur.executemany` دون انتظار، أو عبر معاملة ذرية صريحة `async with cur.connection.transaction():` لضمان التراجع الكامل في حال الفشل.
  - **التعليق الديناميكي والاستئناف المتين (`types.py:903-1047`):**
    - استدعاء `answer = interrupt("...")`: تقرأ مسودة التشغيل `scratchpad` وتحسب رقم المقاطعة `idx`.
    - في المرة الأولى: تطلق استثناء `raise GraphInterrupt(...)` وتُحفظ الحالة في PostgreSQL.
    - عند الاستئناف عبر `Command(resume=...)`: يُعاد تشغيل العقدة من البداية، وعند الوصول لنفس المقاطعة `idx` تجد القيمة في `scratchpad.resume`، وتتحقق منها بـ Pydantic عبر `_validate_resume`، ثم **تُرجع القيمة مباشرة دون إطلاق أي استثناء!**
* **ما نأخذه لمنصتنا:** تبني نمط `StateGraph` مع `Postgres Checkpointer` لحل مشكلة فقدان سياق المحادثة الممتدة وانقطاع الاتصال.

---

### المشروع 2: Memento-Skills (Memento Teams)
* **المستودع الرسمي:** `https://github.com/Memento-Teams/Memento-Skills.git`
* **الالتزام المثبت:** `ee9b9a45efd093d669c06fe318b4b1dceb246d19`
* **الترخيص القانوني:** **Apache License 2.0**
* **الملفات المفحوصة في الكود الفعلي:**
  1. `builtin/skills/skill-creator/SKILL.md` (الأسطر 94–118, 177–241)
  2. `builtin/skills/skill-creator/agents/grader.md` (الأسطر 1–150)
  3. `builtin/skills/skill-creator/agents/analyzer.md` (الأسطر 1–150)
  4. `builtin/skills/skill-creator/scripts/run_eval.py` (الأسطر 53–228)
  5. `builtin/skills/skill-creator/scripts/run_loop.py` (الأسطر 28–49, 84–143)
  6. `middleware/sandbox/uv.py` (الأسطر 44–66, 92–261, 321–355)
  7. `core/skill/execution/hooks/sandbox_audit.py` (الأسطر 39–98)
* **الأدلة البرمجية ومسارات التشغيل المثبتة بالكود:**
  - **التحميل التدريجي للمهارة (`SKILL.md:94-118`):** توفير نافذة السياق عبر 3 مستويات: Metadata (~100 كلمة دائماً بالذاكرة للإطلاق)، Body (<500 سطر يُقرأ عند الاستدعاء)، ومصادر ملحقة (`scripts/`, `references/`).
  - **التشغيل المزدوج المتزامن (`SKILL.md:177-196`):** تنفيذ نسختين متوازيتين لكل حالة اختبار (With-skill run مقابل Baseline run دون مهارة)، واقتناص مؤشرات الأداء الفورية في `timing.json` (`total_tokens`, `duration_ms`).
  - **المصحح الصارم (`grader.md:89-102`):** تقييم موضوعي يرفض أي استيفاء شكلي أو بالصدفة، ويتحقق من الادعاءات الجوهرية (Factual, Process, Quality claims)، ويصدر تقريراً مهيكلاً `grading.json`.
  - **المحلل العمياء والمقترحات المهيكلة (`analyzer.md:52-89`):** كشف الهوية بعد مقارنة عمياء، وإعطاء درجة الالتزام بالتعليمات (1-10)، وصياغة مقترحات تطوير مهيكلة (`priority`, `category`, `suggestion`, `expected_impact`).
  - **منع فرط التخصيص (`run_loop.py:28-49`):** تقسيم بيانات الاختبار (Train/Test Split مع Stratified sampling) وفقاً لحقل `should_trigger` لضمان عدم تدريب الوكيل على أسئلة الامتحان.
  - **عزل الـ Sandbox (`middleware/sandbox/uv.py:92-261`):** إنشاء بيئات بايثون افتراضية مؤقتة فورية باستخدام `uv`، وحجب النوافذ في ويندوز (`CREATE_NO_WINDOW`)، ومراقبة الحدود عبر `SandboxAuditHook` لمنع التعديل خارج مجلد العمل (`is_safe_within_workspace`).
* **ما نأخذه لمنصتنا:** الأساس الهندسي لتطبيق البنود 21 و 22 و 24 في رؤيتنا (التطور المهني المستمر للوكلاء).

---

### المشروع 3: RagLeap Core
* **المستودع الرسمي:** `https://github.com/ragleap/ragleap-core.git`
* **الالتزام المثبت:** `b9bb6fbc1f7c8ef0427cb817ffc495578ab0531b` (Release v0.6.2)
* **الترخيص القانوني:** **MIT License**
* **الملفات المفحوصة في الكود الفعلي:**
  1. `core/autonomy.py` (الأسطر 7–12, 23–31, 265–295, 317–381)
  2. `core/agent_loop.py` (الأسطر 12–14, 40–41, 53–58, 72–109, 160–176, 295–315, 337–372)
  3. `core/budget.py` (الأسطر 9–18, 44–46, 69–85, 130–162)
  4. `core/observability.py` (الأسطر 36–141)
* **الأدلة البرمجية ومسارات التشغيل المثبتة بالكود:**
  - **أوضاع الاستقلالية الثلاثة (`autonomy.py:7-12, 317-381`):** `off` (تجاهل الإجراء)، `semi` (توليد `action_id` عشوائي من 8 خانات، وتخزينه في `autonomy_pending` وإرسال رسالة للمالك عبر Telegram/WhatsApp تتطلب الرد بـ `YES <id>` أو `NO <id>`)، و `full` (تنفيذ مباشر مع التوثيق في `autonomy_log`).
  - **الخفض القسري للأدوار الحساسة (`autonomy.py:23-31, 336-347`):** الأدوار الحساسة (القانون، المالية، الصحة عبر `is_sensitive_role`) تُخفض قسرياً من `full` إلى `semi`.
  - **تتبع التلوث ومنع تسريب البيانات (`agent_loop.py:12-14, 298, 314-315`):** قراءة أي بيانات عبر أدوات التلويث (`fetch_page`, `mcp_call`, `read_file`) تحول الجلسة إلى `tainted = True`؛ مما يجبر أي استدعاء خارجي لاحق (`send_webhook`, `send_email`) على التحول قسرياً لطلب موافقة المالك (`force_semi = True`)!
  - **حوكمة الميزانية (`budget.py:135-162`):** تسجيل كل استهلاك في جدول `llm_usage`، وتحديد سقف يومي وشهري لكل دور، مع إطلاق تحذير عند 80% وسياسة Fail-Open لمنع تعليق النظام.
  - **تقرير الرصد اليومي (`observability.py:85-141`):** دالة `generate_observability_report()` التي تجمع بيانات اليوم (معدل الأخطاء، الـ Latency، ونسبة الـ Fallback والـ Reflection Concerns) لرفعها في التقرير اليومي.
  - **الاستئناف غير المتزامن (`agent_loop.py:337-372`):** عند وصول موافقة المالك، تُستأنف الدورة في خيط خلفي مستقل (`_spawn(go)` عبر `threading.Thread(daemon=True)`).
* **ما نأخذه لمنصتنا:** التصميم الهندسي المباشر لنظام الاستقلالية وبطاقة الوكيل وخط رصد "الأب الروحي".

---

### المشروع 4: Dify
* **المستودع الرسمي:** `https://github.com/langgenius/dify.git`
* **الالتزام المثبت:** `89cdc0c7a9c78027d4e15112e420f6570ae783ab`
* **الترخيص القانوني:** **Dify Open Source License** (قيود تجارية تمنع تقديمه كمنصة SaaS منافسة).
* **الملفات المفحوصة:** `api/core/rag/` و `api/core/model_runtime/` و `api/models/`.
* **ما نأخذه لمنصتنا:** تصميم البحث الهجين (Hybrid RAG: Vector + BM25) لجدول الحقائق المؤسسية وعزل المستأجرين (Workspaces)، مع كتابة كودنا الخاص 100% دون نسخ أي أسطر تجارية.

---

### المشروع 5: Microsoft Agent Framework
* **المستودع الرسمي:** `https://github.com/microsoft/agent-framework.git`
* **الالتزام المثبت:** `67ba500ec1fd312606a5d585a42335cd8631e851`
* **الترخيص القانوني:** **MIT License**
* **ما نأخذه لمنصتنا:** بطاقة الوكيل التعاقدية (Agent Manifest) التي تُعلن قدرات الوكيل ومستويات استقلاليته وحدوده بوضوح قبل التفعيل.

---

### المشروع 6: OpenAI Agents Python SDK
* **المستودع الرسمي:** `https://github.com/openai/openai-agents-python.git`
* **الالتزام المثبت:** `0dc4cf152bff1f50bdc0e41f28808563406545b2`
* **الترخيص القانوني:** **MIT License**
* **ما نأخذه لمنصتنا:** حواجز الحماية للمدخلات والمخرجات (Guardrails) وآلية تسليم المهام بين عدة وكلاء متخصصين (Handoffs).

---

### المشروع 7: n8n
* **المستودع الرسمي:** `https://github.com/n8n-io/n8n.git`
* **الالتزام المثبت:** `9a489b65ed539a042e819012558cfc6985aab78d`
* **الترخيص القانوني:** **Sustainable Use License**
* **ما نأخذه لمنصتنا:** هندسة معالجة أخطاء الـ Webhooks وإعادة المحاولة في موصلات القنوات.
