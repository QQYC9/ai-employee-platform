# 06_REFERENCE_PROJECTS_RESEARCH.md — البحث المعماري المتعمق في المشاريع المرجعية السبعة

- **تاريخ الاعتماد:** 2026-11-03T03:12:00+03:00
- **بيئة البحث:** المستودعات الأصلية المحلية على القرص في `D:\AI-Employee-Platform-Research`
- **المنهجية:** فحص الكود المصدري الأصلي سطراً بسطر في الملفات المحورية، وتثبيت الـ Commit والترخيص وتتبع مسارات التشغيل بالأدلة البرمجية القاطعة، وتفويض مسارات بحثية تخصصية متوازية.

---

## 1. المشروع 1: LangGraph (LangChain AI)

- **المستودع الرسمي:** `https://github.com/langchain-ai/langgraph.git`
- **الالتزام المثبت (Commit Hash):** `4c52e129eb1ab69a3da58b799f67929f77d81149` (Release v1.2.17)
- **الترخيص القانوني:** **MIT License** (مفتوح المصدر بالكامل ومسموح بالاستخدام التجاري دون قيود).
- **الملفات المفحوصة في الكود الفعلي:**
  1. `libs/checkpoint-postgres/langgraph/checkpoint/postgres/base.py` (L45–L80)
  2. `libs/checkpoint-postgres/langgraph/checkpoint/postgres/aio.py` (L250–L310, L418–L450)
  3. `libs/langgraph/langgraph/types.py` (L903–L1047)
  4. `libs/langgraph/langgraph/pregel/_algo.py` (L156–L186)

### الأدلة البرمجية ومسارات التشغيل المثبتة بالكود:
1. **مخطط الجداول الثلاثة في PostgreSQL (`base.py:45-80`):**
   - جدول `checkpoints`: المفتاح الأساسي `PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)`.
   - جدول `checkpoint_blobs`: المفتاح الأساسي `PRIMARY KEY (thread_id, checkpoint_ns, channel, version)` لتخزين البيانات الكبيرة دون تكرار (Deduplication).
   - جدول `checkpoint_writes`: لحفظ الكتابات الوسيطة لكل مهمة بشكل ذري.
2. **الذرية وسرعة خطوط الأنابيب (`aio.py:250-310`):**
   - تفصل الدالة `aput` القيم البسيطة لتُخزن في حقل `jsonb`، وتضع الكتل الكبيرة في `checkpoint_blobs`.
   - في حال دعم قاعدة البيانات للـ Pipeline، تُنفذ العمليات عبر `cur.executemany` دون انتظار، أو عبر معاملة ذرية صريحة `async with cur.connection.transaction():` لضمان التراجع الكامل في حال الفشل.
3. **التعليق الديناميكي والاستئناف المتين (`types.py:903-1047`):**
   - استدعاء `answer = interrupt("...")`: تقرأ مسودة التشغيل `scratchpad` وتحسب رقم المقاطعة `idx`.
   - في المرة الأولى: تطلق استثناء `raise GraphInterrupt(...)` وتُحفظ الحالة في PostgreSQL.
   - عند الاستئناف عبر `Command(resume=...)`: يُعاد تشغيل العقدة من البداية، وعند الوصول لنفس المقاطعة `idx` تجد القيمة في `scratchpad.resume`، وتتحقق منها بـ Pydantic عبر `_validate_resume`، ثم **تُرجع القيمة مباشرة دون إطلاق أي استثناء!**

### ما نأخذه لمنصتنا:
تبني نمط `StateGraph` مع `Postgres Checkpointer` لحل مشكلة فقدان سياق المحادثة الممتدة وانقطاع الاتصال.

---

## 2. المشروع 2: Memento-Skills (Memento Teams)

- **المستودع الرسمي:** `https://github.com/Memento-Teams/Memento-Skills.git`
- **الالتزام المثبت (Commit Hash):** `ee9b9a45efd093d669c06fe318b4b1dceb246d19` (Tag: v0.4.0)
- **الترخيص القانوني:** **Apache License 2.0**
- **الملفات المفحوصة في الكود الفعلي:**
  1. `builtin/skills/skill-creator/SKILL.md` (L94–L118, L177–L241)
  2. `builtin/skills/skill-creator/agents/grader.md` (L1–L150)
  3. `builtin/skills/skill-creator/agents/analyzer.md` (L1–L150)
  4. `builtin/skills/skill-creator/scripts/run_eval.py` (L53–L228)
  5. `builtin/skills/skill-creator/scripts/run_loop.py` (L28–L49, L84–L143)
  6. `middleware/sandbox/uv.py` (L44–L66, L92–L261, L321–L355)
  7. `core/skill/execution/hooks/sandbox_audit.py` (L39–L98)

### الأدلة البرمجية ومسارات التشغيل المثبتة بالكود:
1. **التحميل التدريجي للمهارة (`SKILL.md:94-118`):** توفير نافذة السياق عبر 3 مستويات: Metadata (~100 كلمة دائماً بالذاكرة للإطلاق)، Body (<500 سطر يُقرأ عند الاستدعاء)، ومصادر ملحقة (`scripts/`, `references/`).
2. **التشغيل المزدوج المتزامن (`SKILL.md:177-196`):** تنفيذ نسختين متوازيتين لكل حالة اختبار (With-skill run مقابل Baseline run دون مهارة)، واقتناص مؤشرات الأداء الفورية في `timing.json` (`total_tokens`, `duration_ms`).
3. **المصحح الصارم (`grader.md:89-102`):** تقييم موضوعي يرفض أي استيفاء شكلي أو بالصدفة، ويتحقق من الادعاءات الجوهرية (Factual, Process, Quality claims)، ويصدر تقريراً مهيكلاً `grading.json`.
4. **المحلل العمياء والمقترحات المهيكلة (`analyzer.md:52-89`):** كشف الهوية بعد مقارنة عمياء، وإعطاء درجة الالتزام بالتعليمات (1-10)، وصياغة مقترحات تطوير مهيكلة (`priority`, `category`, `suggestion`, `expected_impact`).
5. **منع فرط التخصيص (`run_loop.py:28-49`):** تقسيم بيانات الاختبار (Train/Test Split مع Stratified sampling) وفقاً لحقل `should_trigger` لضمان عدم تدريب الوكيل على أسئلة الامتحان.
6. **عزل الـ Sandbox (`middleware/sandbox/uv.py:92-261`):** إنشاء بيئات بايثون افتراضية مؤقتة فورية باستخدام `uv`، وحجب النوافذ في ويندوز (`CREATE_NO_WINDOW`)، ومراقبة الحدود عبر `SandboxAuditHook` لمنع التعديل خارج مجلد العمل (`is_safe_within_workspace`).

### ما نأخذه لمنصتنا:
الأساس الهندسي لتطبيق البنود 21 و 22 و 24 في رؤيتنا (التطور المهني المستمر للوكلاء ومحرك اختبار وتقييم المهارات قبل اعتمادها).

---

## 3. المشروع 3: RagLeap Core

- **المستودع الرسمي:** `https://github.com/ragleap/ragleap-core.git`
- **الالتزام المثبت (Commit Hash):** `b9bb6fbc1f7c8ef0427cb817ffc495578ab0531b` (Tag: ragleap-ops-v0.6.2)
- **الترخيص القانوني:** **MIT License**
- **الملفات المفحوصة في الكود الفعلي:**
  1. `core/autonomy.py` (L7–L12, L23–L31, L265–L295, L317–L381)
  2. `core/agent_loop.py` (L12–L14, L40–L41, L53–L58, L72–L109, L160–L176, L295–L315, L337–L372)
  3. `core/budget.py` (L9–L18, L44–L46, L69–L85, L130–L162)
  4. `core/observability.py` (L36–L141)

### الأدلة البرمجية ومسارات التشغيل المثبتة بالكود:
1. **أوضاع الاستقلالية الثلاثة (`autonomy.py:7-12, 317-381`):** `off` (تجاهل الإجراء)، `semi` (توليد `action_id` عشوائي من 8 خانات، وتخزينه في `autonomy_pending` وإرسال رسالة للمالك عبر Telegram/WhatsApp تتطلب الرد بـ `YES <id>` أو `NO <id>`)، و `full` (تنفيذ مباشر مع التوثيق في `autonomy_log`).
2. **الخفض القسري للأدوار الحساسة (`autonomy.py:23-31, 336-347`):** الأدوار الحساسة (القانون، المالية، الصحة عبر `is_sensitive_role`) تُخفض قسرياً من `full` إلى `semi`.
3. **تتبع التلوث ومنع تسريب البيانات (`agent_loop.py:12-14, 298, 314-315`):** قراءة أي بيانات عبر أدوات التلويث (`fetch_page`, `mcp_call`, `read_file`) تحول الجلسة إلى `tainted = True`؛ مما يجبر أي استدعاء خارجي لاحق (`send_webhook`, `send_email`) على التحول قسرياً لطلب موافقة المالك (`force_semi = True`)!
4. **حوكمة الميزانية (`budget.py:135-162`):** تسجيل كل استهلاك في جدول `llm_usage`، وتحديد سقف يومي وشهري لكل دور، مع إطلاق تحذير عند 80% وسياسة Fail-Open لمنع تعليق النظام.
5. **تقرير الرصد اليومي (`observability.py:85-141`):** دالة `generate_observability_report()` التي تجمع بيانات اليوم (معدل الأخطاء، الـ Latency، ونسبة الـ Fallback والـ Reflection Concerns) لرفعها في التقرير اليومي.
6. **الاستئناف غير المتزامن (`agent_loop.py:337-372`):** عند وصول موافقة المالك، تُستأنف الدورة في خيط خلفي مستقل (`_spawn(go)` عبر `threading.Thread(daemon=True)`).

### ما نأخذه لمنصتنا:
التصميم الهندسي المباشر لنظام الاستقلالية وبطاقة الوكيل وحماية البيانات الملوثة وخط رصد "الأب الروحي".

---

## 4. المشروع 4: Dify (LangGenius)

- **المستودع الرسمي:** `https://github.com/langgenius/dify.git`
- **الالتزام المثبت (Commit Hash):** `89cdc0c7a9c78027d4e15112e420f6570ae783ab`
- **الترخيص القانوني:** **Dify Open Source License** (قيود تجارية تمنع تقديم Dify كمنصة SaaS منافسة دون ترخيص تجاري).
- **الملفات المفحوصة في الكود الفعلي:**
  1. `api/core/agent/fc_agent_runner.py` (L1–L571)
  2. `api/core/agent/base_agent_runner.py`
  3. `api/core/tools/tool_engine.py`
  4. `dify-agent-runtime/internal/landlock/`

### الأدلة البرمجية ومسارات التشغيل المثبتة بالكود:
1. **تشغيل Function-Calling المتكرر المنضبط (`fc_agent_runner.py:120-250`):**
   - حلقة تشغيل `while function_call_state and iteration_step <= max_iteration_steps:`
   - حقن الأدوات المهيكلة في `model_instance.invoke_llm(tools=prompt_messages_tools)`.
   - استخراج استدعاءات الأدوات وتمريرها فورياً إلى `ToolEngine.agent_invoke`.
2. **منع احتجاز أقفال قاعدة البيانات أثناء استدعاء الذكاء الاصطناعي (`fc_agent_runner.py:166-167`):**
   - السطران الحرجان:
     ```python
     session.commit()
     session.close()
     ```
   - يتم تحرير جلسة قاعدة البيانات بالكامل قبل انتظار بث الـ LLM، مما يمنع تجويع الـ Connection Pool!
3. **العزل المتعدد الصارم في تنفيذ الأدوات (`fc_agent_runner.py:326-338`):**
   - تمرير `tenant_id` و `user_id` صراحة لكل استدعاء أداة لضمان عزل الوصول.
4. **عزل بيئة التشغيل عبر Landlock في Go (`dify-agent-runtime`):**
   - استخدام ميزات Linux Landlock LSM لتقييد وصول الأدوات البرمجية على القرص.

### ما نأخذه لمنصتنا:
بنية استدعاء الأدوات المتكررة، تحرير أقفال قاعدة البيانات قبل استدعاء الـ LLM، والبحث الهجين (Hybrid RAG).

---

## 5. المشروع 5: Microsoft Agent Framework

- **المستودع الرسمي:** `https://github.com/microsoft/agent-framework.git`
- **الالتزام المثبت (Commit Hash):** `67ba500ec1fd312606a5d585a42335cd8631e851`
- **الترخيص القانوني:** **MIT License**
- **الملفات المفحوصة في الكود الفعلي:**
  1. `python/packages/core/agent_framework/_agents.py` (L287–L423, L1999–L2162)
  2. `python/packages/core/agent_framework/_tools.py` (L587–L1664, L5577–L6497)
  3. `python/packages/core/agent_framework/_compaction.py` (L1–L120, L2393 سطراً)
  4. `python/packages/core/agent_framework/_skills.py` (L1–L100, L5604 سطراً)
  5. `python/packages/core/agent_framework/_harness/_tool_approval.py` (L378–L768)
  6. `python/packages/core/agent_framework/security.py` (L1–L100)
  7. `python/packages/declarative/agent_framework_declarative/_models.py` (L987–L1022)

### الأدلة البرمجية ومسارات التشغيل المثبتة بالكود:
1. **ضغط الذاكرة الدلالي وحفظ السياق (`_compaction.py`):**
   - معمارية تجميع الرسائل في وحدات دلالية (`GroupKind: Literal["system", "user", "assistant_text", "tool_call"]`).
   - استبدال الرسائل القديمة بملخصات مع الاحتفاظ بـ `origin_session_ids` وتتبع مصدر كل أداة دون بتر تعسفي.
2. **بروتوكول الوكيل الصريح وبطاقة القدرات (`AgentManifest`):**
   - التصريح الدقيق عن قدرات الوكيل، وأدواته، ومستوى الأمان في ملف YAML تعاقدي قبل التفعيل.
3. **أوضاع الموافقة وحماية المعاملات من التلاعب (`_tools.py` & `_tool_approval.py`):**
   - `ApprovalMode: Literal["always_require", "never_require"]`.
   - فحص `_FunctionArgumentsChangedAfterApproval`: إذا تم التلاعب بالمعاملات بين لحظة الموافقة ولحظة التنفيذ، يتم الإيقاف الفوري لمنع هجمات التسلل.
4. **التحكم في تدفق المعلومات ومنع حقن الموجهات (`security.py`):**
   - تصنيف المدخلات بـ `IntegrityLabel` و `ConfidentialityLabel`.
   - عزل المدخلات غير الموثوقة في `ContentVariableStore` وتمريرها عبر `quarantined_llm` قبل السماح لها بالتأثير على الأدوات الحساسة.

### ما نأخذه لمنصتنا:
خوارزمية ضغط الذاكرة الدلالي (`_compaction.py`)، بطاقة الوكيل التعاقدية (`AgentManifest`)، وتأمين الموافقات ضد التلاعب بعد الاعتماد.

---

## 6. المشروع 6: OpenAI Agents Python SDK

- **المستودع الرسمي:** `https://github.com/openai/openai-agents-python.git`
- **الالتزام المثبت (Commit Hash):** `0dc4cf152bff1f50bdc0e41f28808563406545b2` (v0.7.0+)
- **الترخيص القانوني:** **MIT License**
- **الملفات المفحوصة في الكود الفعلي:**
  1. `src/agents/agent.py` (L187–L1171)
  2. `src/agents/run.py` (L279–L2935)
  3. `src/agents/run_internal/run_loop.py` & `turn_resolution.py`
  4. `src/agents/handoffs/__init__.py` (L126–L227) & `history.py` (L28–L120)
  5. `src/agents/guardrail.py` & `tool_guardrails.py` (L18–L160)
  6. `src/agents/run_state.py` (L842–L1450)

### الأدلة البرمجية ومسارات التشغيل المثبتة بالكود:
1. **آلية تسليم المهام بين الوكلاء المتخصصين (Handoffs):**
   - تحويل التسليم إلى استدعاء أداة `transfer_to_<agent_name>` يفهمها النموذج بسلاسة.
   - ضغط وحفظ تاريخ المحادثة السابقة داخل `<CONVERSATION HISTORY> ... </CONVERSATION HISTORY>` عبر `nest_handoff_history`.
   - انتقال دورة التشغيل فورياً في حلقة `AgentRunner` للوكيل الجديد دون فقدان السياق.
2. **حواجز الحماية متعددة الطبقات (Multi-Tier Guardrails):**
   - **Input Guardrails:** تعمل بالتوازي مع استدعاء النموذج أو بالتتابع؛ إذا أُطلق التنبيه (`tripwire_triggered=True`)، يتم إلغاء استدعاء النموذج فوراً لتوفير التكلفة والوقت.
   - **Output Guardrails:** تفحص المخرج النهائي وتمنع وصول أي تسريب للمستخدم.
   - **Tool Guardrails:** تدعم `reject_content(message)` لإبلاغ النموذج بالخطأ وتصحيح نفسه دون إسقاط الجلسة، أو `raise_exception` للوقف الفوري.
3. **حفظ الحالة القابلة للاستئناف (`RunState`):**
   - التقاط حالة التشغيل بالكامل عند طلب الموافقة البشرية (`ToolApprovalItem`) وحفظها في كائن قابل للتسلسل (`RunState.to_dict()`)، ثم الاستئناف المباشر عبر `Runner.run(input=run_state)`.

### ما نأخذه لمنصتنا:
تصميم تسليم المهام بين الوكلاء (Handoffs) وحواجز الحماية للمدخلات والمخرجات (Guardrails) وحفظ الحالة القابلة للاستئناف (`RunState`).

---

## 7. المشروع 7: n8n

- **المستودع الرسمي:** `https://github.com/n8n-io/n8n.git`
- **الالتزام المثبت (Commit Hash):** `9a489b65ed539a042e819012558cfc6985aab78d`
- **الترخيص القانوني:** **Sustainable Use License** (ترخيص مقيد تجارياً لخدمات الـ SaaS المنافسة).
- **الملفات المفحوصة في الكود الفعلي:**
  1. `packages/workflow/src/execution-status.ts`
  2. `packages/core/src/execution-engine/execution-lifecycle-hooks.ts` (L1–L133)
  3. `packages/core/src/execution-engine/workflow-execute.ts`
  4. `packages/workflow/src/auth-redaction.ts` & `credential-domain-restrictions.ts`

### الأدلة البرمجية ومسارات التشغيل المثبتة بالكود:
1. **خطافات دورة حياة التنفيذ (`ExecutionLifecycleHooks`):**
   - تعريف أحداث صريحة: `nodeExecuteBefore`, `nodeExecuteAfter`, `workflowExecuteBefore`, `workflowExecuteResume`, `workflowExecuteAfter`, `sendResponse`, `sendChunk`.
   - ربط الخطافات بحفظ التقدم تلقائياً في قاعدة البيانات ودفع التحديثات لحظياً عبر WebSockets/SSE.
2. **حجب الأسرار وتأمين بيانات الاعتماد (`auth-redaction.ts`):**
   - حجب تلقائي لأي بيانات اعتماد أو مفاتيح API تظهر في الـ Payload أو السجلات قبل تخزينها.
3. **معالجة الويب هوك غير المتزامنة (`sendResponse`):**
   - القدرة على الرد فورياً بـ 200 OK لموصل القناة مع استمرار تدفق المعالجة والخطوات في الخلفية.

### ما نأخذه لمنصتنا:
هيكلية خطافات دورة حياة التنفيذ (Execution Lifecycle Hooks) وحجب الأسرار التلقائي في سجلات التتبع.
