# التدقيق الأمني الشامل والاعتمادية ومصفوفة المخاطر (Security & Reliability Audit)
## 09_SECURITY_RELIABILITY_AUDIT.md

- **تاريخ التوثيق:** 2026-11-03T03:00:00+03:00
- **الهدف:** تحليل كافة التهديدات الأمنية ومخاطر الاعتمادية، ربطها بالأدلة الميدانية، وتحديد آليات التخفيف والاختبارات اللازمة.

---

## 1. مصفوفة تدقيق المخاطر الأمنية (Security Threat Matrix)

| التهديد الأمني (Threat) | مسار الحدوث المحتمل في الكود | مستوى الخطورة | الدليل البرمجي الحالي | استراتيجية التخفيف المعمارية (Mitigation) | الاختبار التوكيدي المطلوب |
| :--- | :--- | :---: | :--- | :--- | :--- |
| **تسريب بيانات المستأجرين (Cross-Tenant Leakage)** | استعلام قاعدة بيانات يفتقر لشرط `where tenant_id = ...` | **حرج (Critical)** | `packages/auth/tenant_context.py` و `models/domain.py` | فرض Tenant Isolation Guardrail على مستوى ORM و Session Middleware | اختبار استعلامات متعمدة بـ `tenant_id` غير مصرح والتأكد من حجبها |
| **تجاوز الموافقات البشرية (Approval Bypass)** | استدعاء الأداة مباشرة دون المرور بـ `ActionPolicyService` | **حرج (Critical)** | `packages/services/approval_service.py` | دمج عتبة الاستقلالية داخل نواة المحرك (Core Autonomy Gate) بحيث يستحيل تشغيل أداة بدون Token موافقة صالح | محاولة استدعاء `execute_tool` مع تجاوز الـ Approval والتأكد من رفضها فوراً |
| **حقن الأوامر والهلوسة (Prompt & Tool Injection)** | إدخال نصوص خبيثة من العميل لإجبار الوكيل على كشف التعليمات أو تنفيذ إجراءات | **عالي (High)** | غياب Input/Output Guardrails صريحة في `conversational_agent_engine.py` | بناء عقدة `InputGuardrailNode` و `OutputGuardrailNode` مستوحاة من OpenAI Agents SDK | إرسال نصوص Jailbreak معروفة عبر Webhook واختبار حجبها |
| **تسميم الذاكرة والمعرفة (Memory/Knowledge Poisoning)** | قيام عميل بتقديم معلومات زائفة وتخزينها كحقيقة للنشاط | **عالي (High)** | `packages/services/fact_service.py` | حظر استخراج الحقائق المعتمدة إلا من قناة المالك الموثوقة أو بموافقته، مع تمييز مصدر الحقيقة (`Provenance`) | محاولة عميل تغيير ساعات العمل والتأكد من عزل مدخلاته عن الحقائق الدائمة |
| **تكرار تنفيذ الرسائل والمهام (Replay & Duplicate Execution)**| انقطاع الشبكة وإعادة إرسال طلب Webhook متكرر من Telegram | **متوسط (Medium)** | تم تخفيفه بنمط `IdempotencyRecord` و `OutboxWorker` | الحفاظ على قفل `SELECT FOR UPDATE SKIP LOCKED` وتخزين `update_id` القناة | محاولة إرسال نفس الرسالة 10 مرات متزامنة والتأكد من معالجتها مرة واحدة |
| **استنزاف التوكنز والتكلفة (Token/Cost Exhaustion)** | دخول الوكيل في حلقة حوارية مفرغة أو طلبات ضخمة متكررة | **متوسط (Medium)** | `packages/services/ai_usage_service.py` | تطبيق Budget Guards المستوحاة من RagLeap Core مع إيقاف آلي عند تجاوز الحد المالي للمستأجر | محاكاة تجاوز الميزانية والتأكد من رفض الاستدعاءات التالية بلباقة |
| **تسريب أسرار البوتات والتكاملات (Secret Exposure)** | كتابة التوكنز في السجلات (Logs) أو استرجاعها بدون تعقيم | **حرج (Critical)** | `packages/core/crypto.py` | تعقيم كافة السجلات وحجب الأسرار بـ `******` وتشفيرها الدائم بـ AES-256-GCM | فحص مخرجات الـ Logs للتأكد من انعدام التوكنز الصريحة |

---

## 2. تدقيق الاعتمادية والاستعادة من الأعطال (Reliability & Recovery Audit)

1. **التعافي عند انهيار الخادم (Crash Recovery):**
   - المعمارية القديمة كانت تفقد حالة المحادثة الجارية لأنها لحظية.
   - المعمارية المستهدفة تحفظ كل خطوة كـ Checkpoint في PostgreSQL؛ مما يضمن أن أي رسالة قيد المعالجة تستأنف تلقائياً بمجرد عودة الخدمة.
2. **عزل أعطال موفري الذكاء الاصطناعي (AI Provider Failover):**
   - تم التحقق من وجود `ResilientProvider` في `packages/ai_providers/resilient_provider.py` وهو يدعم التحويل التلقائي (Fallback) من Gemini إلى OpenRouter عند حدوث خطأ 429 أو 500، ويجب الإبقاء عليه.
3. **سلامة النسخ الاحتياطي (Database Consistency):**
   - بما أن كافة البيانات التشغيلية والـ Checkpoints مخزنة في PostgreSQL، فإن النسخ الاحتياطي المعياري لقاعدة البيانات يضمن استعادة النظام بالكامل مع سجلاته دون أي فجوات.
