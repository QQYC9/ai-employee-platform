# 04_FILE_AND_CALLGRAPH_COVERAGE.md — تغطية الملفات والرسم البياني للاستدعاءات والشيفرات الميتة

- **تاريخ التدقيق:** 2026-11-03T03:38:00+03:00
- **المنهجية:** مطابقة استدعاءات الدوال عبر Python AST ومترجم الشيفرة بدقة رياضية، والتمييز الصريح بين:
  1. كود حي يُستدعى في مسار التشغيل الرئيسي (Hot Path).
  2. كود ميت غير مستدعى إطلاقاً (Dead Code / 0 Callers).
  3. كود مكرر ومزدوج بين أكثر من ملف بصياغات متناقضة (Code Duplication).
  4. كود مستدعى داخل دوال ميتة (Dead Execution Tree).

---

## 1. جدول تغطية الملفات الصريح (File & Subsystem Coverage)

| الملف الفعلي (`File Path`) | إجمالي الأسطر | حالة القراءة ونطاق الفحص | نسبة التغطية المقروءة | كود حي أم ميت؟ | ملاحظات التدقيق التشكيكي |
| :--- | :---: | :--- | :---: | :---: | :--- |
| `packages/services/conversational_agent_engine.py` | 5,290 | قراءة تفصيلية: L50–L165, L215–L920, L1289–L2990, L3080–L3500, L3580–L3860, L4020–L4550, L4970–L5290 | ~65% (مركزة على المسارات الحساسة) | **مزيج** (كود تشغيلي صلب + كود ميت) | لا توجد دوال باسم `_generate_llm_reply` أو `_handle_business_hours_inquiry` (تم نفي الادعاء السابق). دالة `_process_owner_message` تمتد 1,702 سطراً منفردة! |
| `packages/services/owner_intent_router.py` | 1,081 | قراءة L1–L450, L650–L800, L950–L1081 | ~70% | **مزيج** (معامل ميت + كود مكرر) | المعامل `self.ai_provider` محقون في L157 وميت تماماً في باقي الملف (0 استخدامات). دالة `_extract_business_knowledge` مكررة من المحرك. |
| `packages/services/conversation_fsm_service.py` | 443 | قراءة كاملة L1–L443 | 100% | **حي** | آلة حالة بسيطة مبنية بـ Enums لمنع تشتت الحوار الإسعافي، ولا تملك Checkpoints في قاعدة البيانات. |
| `packages/services/fact_service.py` | 1,413 | قراءة L1–L350, L550–L850, L1200–L1413 | ~60% | **حي** | تعتمد على pgvector و `tenant_id`، لكن منطق حل النزاعات يعتمد على حداثة التاريخ ويفتقر لمعيار الثقة والمصدر. |
| `packages/services/outbox_worker.py` | 1,243 | قراءة L1–L280, L380–L450, L920–L1243 | ~65% | **حي** | يستخدم `with_for_update(skip_locked=True)` لحجز الأحداث وحماية المعاملات، ويعالج السقوط بـ `recover_stale_events`. |
| `packages/services/outbox_service.py` | 370 | قراءة كاملة L1–L370 | 100% | **حي** | تعليمة `with_for_update(skip_locked=True)` مستدعاة في L197 (عند السحب) وفي L330 (عند التعافي من السقوط). |
| `packages/services/idempotency_service.py` | 226 | قراءة كاملة L1–L226 | 100% | **حي** | يقفل الصفوف بـ `with_for_update()` ويحسب Hash المعاملات لمنع التلاعب وتكرار الإرسال. |
| `packages/services/channel_service.py` | 828 | قراءة L1–L260, L510–L620, L700–L828 | ~60% | **حي** | فجوة أمنية في L543: استرجاع الرسالة عبر `where(Message.id == cached_id)` دون قيد `tenant_id`. |
| `packages/services/approval_service.py` | 857 | قراءة L1–L320, L600–L857 | ~55% | **حي** | فحص التوكن المشفر والمهلة ومكافحة التلاعب قبل التنفيذ. |
| `packages/services/audit_service.py` | 199 | قراءة كاملة L1–L199 | 100% | **حي** | فجوة أمنية في L179: تحديث السجل عبر `where(AuditEvent.id == event_id)` دون قيد `tenant_id`. |
| `packages/core/crypto.py` | 164 | قراءة كاملة L1–L164 | 100% | **حي** | تشفير AES-256-GCM متماثل ومصادق (AEAD). |
| `packages/connectors/telegram.py` | 418 | قراءة كاملة L1–L418 | 100% | **حي** | يجزئ الرسائل عند 4,000 حرف، ويتحقق من Secret Token عبر `hmac.compare_digest`. |
| `packages/connectors/whatsapp.py` | 313 | قراءة كاملة L1–L313 | 100% | **حي** | يتحقق من توقيع HMAC-SHA256 لـ Meta، ويجزئ الرسائل عند 4,000 حرف. |
| `packages/models/domain.py` | 2,707 | فحص الهياكل والجداول والفهارس | ~50% (انتقائي للجداول المحورية) | **حي** | يحتوي على 52 جدولاً مع فهارس وقيود فريدة على مستوى المستأجر. |
| `packages/models/tenant.py` | 70 | قراءة كاملة L1–L70 | 100% | **حي** | يحتوي على جدولي `tenants` و `users`. |

---

## 2. خريطة الاستدعاءات الحقيقية (Real Call Graph & Dependencies)

```mermaid
graph TD
    subgraph WebhookLayer [طبقة الويب هوك]
        WH[webhooks.py]
    end

    subgraph ServiceLayer [طبقة الخدمات]
        CS[channel_service.py]
        IS[idempotency_service.py]
        ENG[conversational_agent_engine.py]
        OIR[owner_intent_router.py]
        FS[fact_service.py]
        OIS[owner_inquiry_service.py]
        OS[outbox_service.py]
    end

    subgraph ProviderLayer [طبقة النماذج]
        RP[resilient_provider.py]
    end

    subgraph WorkerLayer [طبقة العمال]
        OW[outbox_worker.py]
        CONN[telegram.py / whatsapp.py]
    end

    WH -->|L414 / L369| CS
    CS -->|L533| IS
    CS -->|L555| ENG
    ENG -->|L290 (is_owner)| OIR
    ENG -->|L575| CS
    ENG -->|L608| FS
    ENG -->|L5180| RP
    ENG -->|L912| OS
    OIR -->|L405| OIS
    OIR -.->|L157 (ميت تماماً)| RP
    OW -->|L954| OS
    OW -->|L384| CS
    CS -->|L180| CONN
```

---

## 3. الكود الميت والازدواجية الفادحة المثبتة بالأدلة (Dead & Duplicated Code)

1. **الثابت الميت `MAX_TOOL_CALL_ITERATIONS = 3` (`conversational_agent_engine.py:98`):**
   - مُعرّف كمتغير كلاس في السطر L98، ولم يُستدعَ قط في أي سطر من أصل 5,290 سطراً في الملف، ولا في أي ملف آخر في المشروع (0 استدعاءات حقيقية).
2. **المعامل الميت `self.ai_provider` (`owner_intent_router.py:157`):**
   - يتم تمرير `ai_provider` إلى `__init__` وتخزينه في `self.ai_provider = ai_provider`، لكنه لا يُستدعى في أي سطر من أصل 1,081 سطراً في الراوتر!
3. **الدالة الميتة `_extract_business_knowledge` (`conversational_agent_engine.py:3594`):**
   - تمتد لـ 266 سطراً داخل المحرك، ولا تُستدعى من أي دالة أخرى في المحرك؛ في المقابل يمتلك `owner_intent_router.py` نسخته المكررة منها في L657 ويستدعيها في L405!
4. **شجرة الكود الميت لـ `_clean_business_name` (`conversational_agent_engine.py:3580`):**
   - مستدعاة فقط في السطرين L3637 و L3668 داخل دالة `_extract_business_knowledge` الميتة، مما يجعل الشجرة بأكملها (L3580–L3859) كوداً ميتاً محشوراً داخل المحرك دون أي أثر تشغيلي.
