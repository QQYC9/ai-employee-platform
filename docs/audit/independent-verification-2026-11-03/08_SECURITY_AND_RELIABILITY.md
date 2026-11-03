# 08_SECURITY_AND_RELIABILITY.md — التقييم الأمني التشكيكي وثغرات العزل والاعتمادية

- **تاريخ التدقيق:** 2026-11-03T03:52:00+03:00
- **المنهجية:** كشف الثغرات الأمنية ونقاط الضعف الحقيقية دون تسويق أو افتراض سلامة مطلقة، وتحديد أثر كل ثغرة، ومسار استغلالها، والحل الهندسي الإلزامي.

---

## 1. الثغرات الأمنية المكتشفة في الكود الفعلي (Vulnerability Ledger)

### الثغرة 1: انعدام تقييد المستأجر في استعلامات الموافقة وتجاوز صلاحيات المسؤول
- **الملف والأسطر:** `packages/services/approval_service.py` (L390, L804, L845) و `packages/services/task_execution_service.py` (L352).
- **الكود الفعلي:**
  ```python
  user = self.db.scalar(select(User).where(User.id == decision_by_user_id))
  ```
- **مسار الاستغلال:**
  عند اتخاذ قرار موافقة، يستعلم الكود عن دور المستخدم لمعرفة هل يملك صلاحية الاعتماد أم لا (`_is_role_authorized`). ولكن لأن الاستعلام يفتقر لشرط `User.tenant_id == tenant_id`، فإذا مرر المهاجم `decision_by_user_id` لمسؤول في منشأة أخرى، سيتعرف النظام عليه كمسؤول ويمنح الموافقة على إجراءات المنشأة الحالية!
- **درجة الخطورة:** **High**
- **الحل الهندسي:** تعديل الاستعلام فوراً إلى:
  ```python
  select(User).where(User.id == decision_by_user_id, User.tenant_id == tenant_id)
  ```

---

### الثغرة 2: تسرب القنوات في رسائل تصعيد العمال (Outbox Worker Cross-Tenant Payload)
- **الملف والأسطر:** `packages/services/outbox_worker.py` (L698, L842).
- **الكود الفعلي:**
  ```python
  channel = session.scalar(select(Channel).where(Channel.id == UUID(channel_id_str)))
  ```
- **مسار الاستغلال:**
  عند تنفيذ حدث تصعيد للمالك (`_handle_owner_escalation`) أو إشعار مهمة (`_handle_task_notification`)، يسترجع العامل القناة عبر معرّفها فقط دون التحقق من `Channel.tenant_id == event.tenant_id`. إذا حدث خطأ أو تلاعب في محتوى الـ payload يحمل `channel_id` لمنشأة ثانية، سيتم إرسال الرسالة عبر بوت تلك المنشأة.
- **درجة الخطورة:** **Medium**
- **الحل الهندسي:** إضافة قيد المستأجر:
  ```python
  select(Channel).where(Channel.id == UUID(channel_id_str), Channel.tenant_id == event.tenant_id)
  ```

---

### الثغرة 3: جدولان تابعان للمستأجر يفتقران لعمود `tenant_id` في التصميم
- **الملف والأسطر:** `packages/models/domain.py` (L1266: `learning_evidence` و L1414: `report_items`).
- **المشكلة:**
  الجدولان لا يمتلكان عمود `tenant_id`، بل يعتمدان على علاقة مفتاح أجنبي بجدولي `learnings` و `daily_reports`.
- **الأثر:**
  1. غياب إمكانية فرض فهارس مباشرة على `tenant_id` للاستعلام السريع.
  2. صعوبة تطبيق سياسات الحذف التلقائي للمستأجر (Cascading Isolation) وحظر الاستعلامات المباشرة دون Joins.
- **درجة الخطورة:** **Low / Architectural Debt**
- **الحل الهندسي:** إضافة عمود `tenant_id` مع فهرس مركب ومفتاح أجنبي في ترحيل Alembic القادم.

---

### الثغرة 4: فجوة الاستعلام في كاش التكرار
- **الملف والسطر:** `packages/services/channel_service.py` (L543).
- **الكود الفعلي:**
  ```python
  existing_msg = self.db.scalar(select(Message).where(Message.id == UUID(cached["message_id"])))
  ```
- **مسار الاستغلال:**
  الاستعلام يفتقر لشرط `Message.tenant_id == tenant_id`. إذا تلوث سجل الكاش بمعرّف رسالة تخص مستأجراً آخر، يتم إرجاع الرسالة الأجنبية.
- **درجة الخطورة:** **Medium**
- **الحل الهندسي:** إضافة `Message.tenant_id == tenant_id`.

---

## 2. آليات الدفاع في العمق المكتملة والمثبتة بنجاح (Defense-in-Depth)

1. **تشفير الأسرار المتماثل المصادق (`packages/core/crypto.py`):**
   - استخدام **AES-256-GCM** مع ملح وNonce فريد 96 بت لكل عملية، مع Authenticated Data تمنع التلاعب بالـ Ciphertext.
2. **التحقق من التوقيع الرقمي للـ Webhooks (`apps/agent/api/v1/webhooks.py`):**
   - مطابقة ثابتة الوقت `hmac.compare_digest` لـ Meta HMAC-SHA256 و Telegram Secret Token.
3. **قفل التكرار ومكافحة السباق (`packages/services/idempotency_service.py`):**
   - قيد فريد `uq_tenant_idempotency_key` وقفل الصفوف بـ `with_for_update()` لمنع العمليات المتزامنة المكررة.
4. **حظر اختطاف الموافقات (`packages/services/approval_service.py`):**
   - توكنات موافقة مشفرة ذات مدة صلاحية ومربوطة بنوع الإجراء والمعاملات.
