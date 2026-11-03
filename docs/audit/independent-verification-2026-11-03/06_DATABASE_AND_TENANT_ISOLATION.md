# 06_DATABASE_AND_TENANT_ISOLATION.md — التدقيق الجنائي لقاعدة البيانات والذاكرة وعزل المستأجرين

- **تاريخ التوثيق والاعتماد:** 2026-11-03T03:45:00+03:00
- **بيئة الفحص:** PostgreSQL 17 (المنفذ 5433), SQLAlchemy 2.0 ORM, Alembic
- **المنهجية:** تدقيق جنائي لجميع نماذج ORM وترحيلات Alembic وفهارس `tenant_id` واستعلامات الخدمات سطراً بسطر لكشف أي ثغرات عزل حقيقية.

---

## 1. التعداد الفعلي للجداول: نماذج الكود مقابل قاعدة البيانات الحية

### الحقيقة الجنائية المحققة:
- **في كود التطبيق (`Base.metadata.tables`): يوجد بالضبط 53 نموذج ORM** (جدول واحد في `packages/models/tenant.py` و 52 جدولاً في `packages/models/domain.py`).
- **في خادم PostgreSQL الحي (`ai_employee`): يوجد بالضبط 54 جدولاً**.
- **تفسير الفارق:** الجدول رقم 54 هو **`alembic_version`**، وهو جدول تتبع ترحيلات Schema ينشئه Alembic تلقائياً وليس نموذج تطبيق. وهذا يكشف سبب تضارب التقارير السابقة التي نقلت رقم "54 جدولاً" من استعلام قاعدة البيانات دون تمييزه عن نماذج بايثون.

---

## 2. مصفوفة الجداول وحالة عمود `tenant_id` والفهارس

كشف الفحص أن ادعاء التقرير السابق بأن "جميع الجداول تحتوي على `tenant_id`" هو **ادعاء غير دقيق (Partially Verified)**؛ حيث وُجد جدولان تابعان للمستأجر **يفتقران تماماً لعمود `tenant_id`**:

1. **جدول `learning_evidence` (`domain.py:1266`):**
   - يحتوي على: `id`, `learning_id`, `source_id`, `provenance_id`, `evidence_type`, `content`, `confidence`.
   - **لا يحتوي على عمود `tenant_id` إطلاقاً!** ويعتمد عزله بالكامل على الربط غير المباشر (Join) بجدول `learnings`.
2. **جدول `report_items` (`domain.py:1414`):**
   - يحتوي على: `id`, `report_id`, `item_type`, `title`, `description`, `priority`, `visibility`, `data`.
   - **لا يحتوي على عمود `tenant_id` إطلاقاً!** ويعتمد عزله على الربط غير المباشر بجدول `daily_reports`.

### جداول تقبل `tenant_id IS NULL` (القوالب العامة للمنصة):
توجد 9 جداول تسمح بوجود قيمة فارغة (`Nullable`) لدعم القوالب المشتركة على مستوى النظام:
- `users`: تدعم `NULL` لحسابات مشغلي المنصة (`superadmin`, `platform_admin`).
- `employee_personas`, `capabilities`, `tools`, `integrations`, `action_policies`, `sources`, `source_policies`: تدعم `NULL` لقوالب الموظفين والأدوات الافتراضية.
- `audit_events`: تدعم `NULL` لأحداث البنية التحتية العامة.

---

## 3. ترحيلات Alembic وحالة التفرعات

- **إجمالي ملفات الترحيل (`infrastructure/migrations/versions/`):** بالضبط **19 ملف ترحيل**.
- **رأس الترحيل الحالي (Head):** `3b4c5d6e7f8a` (`3b4c5d6e7f8a_add_phase5_employee_personas_and_agent_bindings.py`).
- **قاعدة الترحيل الأولى (Base):** `91e58f155f19` (`91e58f155f19_create_tenants_table.py`).
- **حالة التفرع:** **سلسلة خطية متصلة بنسبة 100% (Linear Chain)**؛ لا توجد أي تفرعات منقسمة (Zero Splits / Zero Branches).

---

## 4. الثغرات الأمنية المكتشفة في استعلامات الخدمات (Cross-Tenant Leaks)

كشف التدقيق الجنائي على كود `packages/services/` وجود **4 مواضع خطيرة تُستعلم فيها السجلات دون تقييد `tenant_id` في شرط `where`**:

1. **استعلام المستخدم والموافقة في `packages/services/approval_service.py` (L390, L804, L845):**
   ```python
   # الأسطر 390 و 804:
   user = self.db.scalar(select(User).where(User.id == decision_by_user_id))
   # السطر 845:
   user = self.db.scalar(select(User).where(User.id == user_id))
   ```
   *الثغرة:* الاستعلام لا يتحقق من `User.tenant_id == tenant_id`؛ إذا مرر مهاجم معرّف مستخدم مسؤول من منشأة أخرى، يتم قبول صلاحياته واعتماد الموافقة!
2. **استعلام معتمد المهمة في `packages/services/task_execution_service.py` (L352):**
   ```python
   approver = self.db.scalar(select(User).where(User.id == approval.decision_by_user_id))
   ```
   *الثغرة:* غياب التحقق من تبعية المستخدم لنفس المستأجر صاحب المهمة.
3. **استرجاع القناة في الموزع `packages/services/outbox_worker.py` (L698, L842):**
   ```python
   # السطر 698 (_handle_owner_escalation):
   channel = session.scalar(select(Channel).where(Channel.id == UUID(channel_id_str)))
   # السطر 842 (_handle_task_notification):
   channel = session.scalar(select(Channel).where(Channel.id == UUID(channel_id_str)))
   ```
   *الثغرة:* يستعلم عن القناة بـ `Channel.id` فقط دون `Channel.tenant_id == event.tenant_id`؛ مما قد يسمح بإرسال إشعار عبر قناة تخص مستأجراً آخر إذا تلوث الـ Payload.
4. **تحديث حالة التدقيق في `packages/services/audit_service.py` (L179):**
   ```python
   statement = select(AuditEvent).where(AuditEvent.id == event_id)
   ```
   *الثغرة:* تحديث حالة الحدث دون التحقق من هوية المستأجر.

---

## 5. الحقيقة الجنائية لذاكرة الحقائق والبحث الدلالي (`FactService`)

أثبت التدقيق الميداني على `packages/services/fact_service.py` أن **ادعاء وجود بحث هجين بـ pgvector و Cosine Distance في محرك الحقائق الحالي هو ادعاء غير صحيح (Unsupported / Incorrect)**:
- لا يوجد أي استيراد لـ `pgvector` أو `cosine_distance` في كامل ملفات `packages/services/` أو `infrastructure/`.
- الدالة الحقيقية لاسترجاع الحقائق هي **`get_relevant_facts`** (السطر L934) وليست `search_facts` أو `get_effective_facts`.
- **آلية البحث الحقيقية في الكود:**
  ```python
  # الأسطر L948–L980 في fact_service.py:
  stmt = select(Fact).where(
      Fact.tenant_id == tenant_id,
      Fact.status == "confirmed",
      Fact.superseded_by.is_(None),
      or_(Fact.expires_at.is_(None), Fact.expires_at > now),
  )
  ...
  query_words = [w.lower() for w in re.findall(r"[\w\u0621-\u064A]+", query) if len(w) > 1]
  ```
  - البحث الفعلي يعتمد على مطابقة كلمات استعلام عادية بـ Regex بايثون وترتيب حسب `created_at DESC` مع إزالة تكرار ساعات العمل!
  - **الاستنتاج المعماري:** محرك الذاكرة الحالي لا يمتلك RAG هجين حقيقي؛ وتضمين الـ Vector Search الحقيقي هو ضرورة معمارية للمحرك البديل.

---

## 6. تشفير الأسرار المصادق (`packages/core/crypto.py`)

- **الخوارزمية المعتمدة:** **AES-256-GCM** (مفتاح 256 بت مع Authenticated Data ثابتة: `b"ai-employee-platform-secret-v1"`).
- **الـ Nonce:** عشوائي وفريد لكل عملية تشفير بحجم **96 بت (12 بايت)** عبر `os.urandom(12)`.
- **وسم المصادقة (Tag):** 128 بت (16 بايت). عند حدوث أي تلاعب بالبيانات أو تلفها، تطلق الدالة استثناء `DecryptionError` فورياً (Fail-closed).
- **صيغة التخزين:** `enc:v1:<nonce_b64>:<ciphertext_and_tag_b64>`.

---

## 7. التحكم في الوصول القائم على الأدوار (RBAC)

- **الأدوار المدعومة في النظام:**
  - مشغلو المنصة: `platform_admin`, `superadmin`.
  - إدارة المستأجر: `tenant_owner` / `owner`, `tenant_admin` / `admin`.
  - الموظفون والتشغيل: `manager` (صلاحيات تعديل المعرفة في `knowledge.py:68`), `member` / `user` (صلاحيات محدودة تمنع تعديل إلا الذكريات الخاصة بهم في `memory.py:86`).
- **نقاط القوة:** التحقق الصارم على مسارات `/api/v1/admin/*` وحظر مدراء المنصة من إجراء موافقات تجارية تخص المستأجرين في `approvals.py:161`.
