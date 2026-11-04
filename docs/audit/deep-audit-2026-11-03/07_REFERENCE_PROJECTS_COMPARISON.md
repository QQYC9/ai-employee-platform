# مصفوفة المقارنة المعمارية المنهجية بالأدلة (Reference Projects Comparison Matrix)
## 07_REFERENCE_PROJECTS_COMPARISON.md

- **تاريخ التوثيق:** 2026-11-03T02:56:00+03:00
- **المنهجية:** مقارنة معمارية دقيقة تفصل بين: (مثبت بالكود / مثبت بالتوثيق فقط / جزئي / غير موجود / لم يتم التحقق منه).

---

## 1. جدول المقارنة المعمارية الشاملة

| المحور المعماري | المنصة الحالية (Current AI-Emp) | LangGraph | Memento-Skills | RagLeap Core | Dify | MS Agent Framework | OpenAI Agents SDK | n8n |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **محرك التشغيل (Runtime)** | خطي أحادي (Monolith) | **StateGraph حلقي** | Task Execution | Agent Loop | Workflow DSL | Semantic Agent | Loop + Hand-offs | Node Workflow |
| **التنفيذ المتين (Durable Execution)** | غير موجود (لحظي) | **مثبت بالكود (Checkpoints)** | جزئي | جزئي (State) | مثبت بالكود | جزئي | غير موجود | مثبت بالكود |
| **الذاكرة (Memory)** | سطحي (Key-Value) | Checkpoint State | Skill Memory | Vector / DB | **Hybrid RAG** | Context Store | Session Context | Workflow State |
| **المهارات (Skills)** | مبرمجة يدوياً | Nodes/Functions | **Eval-Driven Evolution** | Tools | Workflow Tools | Kernel Plugins | Functions | Custom Nodes |
| **الأدوات (Tools)** | قائمة داخلية | ToolNode | Tool Dispatcher | Sandboxed Tools | Tool Integrations| Kernel Functions | Python Tools | 400+ Nodes |
| **إنشاء الوكلاء (Agent Creation)** | سجل DB + Prompt | كود Python | Prompt + Config | Agent Config | Visual DSL | **Declarative Manifest**| Python Agent | Workflow Config |
| **المهام الطويلة (Long-Running)** | تكرار Outbox فقط | **مثبت (Interrupt/Resume)** | أوفلاين | مجدولة | Workflows | جزئي | غير موجود | **مثبت (Wait/Resume)** |
| **تعدد الوكلاء (Multi-Agent)** | غير مدعوم | **مخطط تنسيق شبكي** | Grader/Analyzer | جزئي | Multi-app | Group Chat | **Handoffs مثبتة** | Sub-workflows |
| **عزل المستأجرين (Multi-Tenancy)**| **مثبت بالكود (JWT+DB)**| غير مدمج (تطبيق العميل)| غير موجود (محلي)| جزئي | **مثبت بالكود (Workspaces)**| غير مدمج | غير موجود | مدمج في EE فقط |
| **الموافقات البشرية (Human Approval)**| جزئي (Approvals table)| **مثبت (Interrupt before)**| مراجعة يدوية | Autonomy Gate | User Review | جزئي | Guardrail Check | **Wait for Webhook** |
| **المراقبة والتدقيق (Observability)**| سجلات تدقيق أولية | LangSmith Traces | Log Bus | **Structured Telemetry**| App Logs & Traces| Application Insights | Trace Exporters | Execution Log |
| **التقييم الذاتي (Evaluation)** | غير موجود | LangSmith Evals | **كامل ومثبت (run_eval)**| benchmarks | Dataset Evals | Prompt Flow | غير مدمج | غير موجود |
| **التعلم المستمر (Continuous Learning)**| نظري غير مفعل | غير مدمج | **مثبت (Evolution loop)**| غير مدمج | تحديث المعرفة | غير مدمج | غير مدمج | غير مدمج |
| **الأمان والحماية (Security)** | **AES-GCM + RBAC** | كود المستخدم | عزل أدوات | Budget Guards | API Auth | Policies | **Guardrails صريحة** | Credential Vault |
| **الترخيص القانوني (License)** | ملكية خاصة | **MIT** | **Apache 2.0** | **MIT** | Dify Restricted | **MIT** | **MIT** | Sustainable/Fair Code |
| **الملاءمة لبناء المنصة (Suitability)**| نقطة البداية | **عالية جداً (للمحرك)** | **عالية جداً (للتطوير)**| **عالية جداً (للأب الروحي)**| متوسطة (كمصدر إلهام)| متوسطة (للبطاقة) | جيدة (للحواجز) | منخفضة (ثقيل) |

---

## 2. الخلاصة التركيبية للمقارنة
1. **أفضل نمط للمحرك التحاوري والتنفيذ المتين:** نمط **LangGraph** (StateGraph + PostgreSQL Checkpointing).
2. **أفضل نمط للتطور المهني المستمر للوكيل:** نمط **Memento-Skills** (Analyzer + Grader + Eval Sandbox).
3. **أفضل نمط لـ "الأب الروحي" وحوكمة الاستقلالية:** نمط **RagLeap Core** (Autonomy Thresholds + Structured Telemetry Sink).
4. **أفضل نمط لحواجز الحماية والتسليم بين الوكلاء:** نمط **OpenAI Agents SDK** (Input/Output Guardrails + Handoffs).
5. **أفضل نمط للذاكرة والمعرفة:** نمط **Dify** للبحث الهجين (Vector + BM25) بعد إعادة كتابته بأكوادنا الخاصة.
