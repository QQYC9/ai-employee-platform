# التحليل المصدري لقاعدة البيانات والترحيلات وعلاقات المستأجرين (Database & Migrations Audit)

**تاريخ التوثيق:** 2026-11-03  
**المسار المفحوص:**
- `packages/models/domain.py` و `packages/models/tenant.py`
- `infrastructure/migrations/versions/` (19 ترحيلاً خطياً)
- قاعدة بيانات PostgreSQL 17 المحلية (`localhost:5433`)

---

## 1. التمييز الهندسي الدقيق لعدد الجداول

- **عدد نماذج ORM المعرفة في الكود (`Base.metadata.tables`):** **53 نموذجاً** (نموذج واحد في `tenant.py` و 52 نموذجاً في `domain.py`).
- **عدد الجداول الفعلية في قاعدة بيانات PostgreSQL الحية:** **54 جدولاً**.
- **تفسير الفارق:** الجدول رقم 54 هو جدول النظام الداخلي `alembic_version` الذي ينشئه Alembic تلقائياً لتتبع رقم الترحيل ولا يمثله كلاس ORM في الكود.
- **الخلاصة:** كود التطبيق وقاعدة البيانات في حالة تطابق تام (No Schema Drift) فيما يخص تعريف الجداول.

---

## 2. تدقيق ترحيلات Alembic الخطية

تم فحص شجرة الترحيلات في مجلد `infrastructure/migrations/versions/`:
- **إجمالي ملفات الترحيل:** **19 ترحيلاً خطياً مستمراً**.
- **نقطة البداية (Root):** `0001_initial_schema.py`.
- **نقطة الرأس الحالية (Alembic Head):** `0019_phase12_knowledge_base.py`.
- **سلامة التسلسل:** لا يوجد أي تفرع (No Git-like Branching) في سجل الترحيلات، وكافة الترحيلات تطبق ترقية خطية `down_revision` متسلسلة بدقة.

---

## 3. مصفوفة علاقات `tenant_id` والقيود الفريدة (Constraints Analysis)

| تصنيف الجدول | عدد الجداول | طبيعة الربط بـ `tenant_id` | نماذج من الجداول | التقييم الأمني والمعماري |
| :--- | :---: | :--- | :--- | :--- |
| **جداول المستأجر المباشرة** | **51** | عمود `tenant_id UUID NOT NULL` مباشر مع Foreign Key لجدول `tenants.id` وفهرس مركب | `agents`, `tasks`, `approvals`, `conversations`, `messages`, `facts`, `campaigns`, `outbox_events` | عزل مباشر صلب على مستوى الصفوف واستعلامات الـ ORM |
| **جداول التفاصيل التابعة (Child Tables)** | **2** | ترتبط بعلاقة Foreign Key صلبة بجدول أبوي يحمل `tenant_id`، دون وجود عمود مباشر | `learning_evidence` (يرتبط بـ `learnings.id`)<br>`report_items` (يرتبط بـ `daily_reports.id`) | تصميم علائقي سليم (3NF)، لكن يُوصى بإضافة `tenant_id` كـ Denormalized Field لتمكين RLS |
| **جدول الكيان المستقل** | **1** | جدول المستأجر الأساسي نفسه | `tenants` (يمتلك عمود `id` والـ `slug` الفريد) | قمة شجرة العزل |

### 3.1 تحليل القيود الفريدة المركبة (Unique Constraints)
كشف فحص الـ AST لـ 24 جدولاً تمتلك قيود فريدة:
- **التصميم السليم:** في كافة الجداول التشغيلية الحساسة، تكون القيود الفريدة مركبة وتتضمن `tenant_id` حتماً لمنع تداخل أسماء الكيانات بين المستأجرين:
  - `agents`: `UNIQUE(tenant_id, id)`
  - `approvals`: `UNIQUE(tenant_id, idempotency_key)`
  - `outbox_events`: `UNIQUE(tenant_id, idempotency_key)`
  - `conversations`: `UNIQUE(tenant_id, id)`
  - `interview_topics`: `UNIQUE(tenant_id, slug)`
- **ملاحظة معمارية هامة على جدول `owner_inquiries`:**
  - عمود `inquiry_number` معرف كـ `Identity(start=1, increment=1)` عام على مستوى قاعدة البيانات بالكامل.
  - هذا يعني أن أرقام الاستفسارات تتسلسل عالمياً عبر المستأجرين (مثلاً: استفسار مستأجر A يحمل رقم 1، يليه استفسار مستأجر B برقم 2).
  - على الرغم من أن استعلام المالك مقيد برمجياً بـ `tenant_id` (مما يمنع مالك B من رؤية استفسار A حتى لو خمن الرقم 1)، إلا أن هذا التسلسل العام يكشف لأصحاب الأعمال الحجم الإجمالي لاستفسارات المنصة ويخالف توقع العميل بأن يبدأ ترقيم استفساراته من #1.
  - **التوصية:** تحويل `inquiry_number` ليكون تسلسلاً محلياً لكل مستأجر (`tenant-scoped sequence`).
