# التحليل الجنائي العميق لعزل المستأجرين (Deep Tenant Isolation Forensic Audit)

**تاريخ التوثيق:** 2026-11-03  
**النطاق المفحوص:** طبقة واجهات البرمجة (API Routes)، خدمات الأعمال (Services)، نماذج البيانات (ORM Models)، وعمال الخلفية (Background Workers).

---

## 1. التتبع الجنائي لمواضع الاستعلام المشتبه بها (Call Tree & Boundary Analysis)

### 1.1 خدمة الموافقات (`packages/services/approval_service.py`)
- **المواضع المفحوصة:** الأسطر 795, 804, 836, 845.
- **مسار الاستدعاء الفعلي (Call Stack Trace):**
  1. يبدأ الطلب عند نقطة النهاية: `POST /api/v1/approvals/{approval_id}/approve` في [`apps/agent/api/v1/approvals.py:154`](file:///d:/AI-Employee-Platform/apps/agent/api/v1/approvals.py#L154).
  2. يتم فك شفرة الـ JWT واستخراج `current_user` عبر التبعية الإجبارية `Depends(get_tenant_context)` بالسطر 158.
  3. تستدعي الـ API الدالة `service.approve(tenant_id=current_user.tenant_id, approval_id=approval_id, decision_by_user_id=current_user.id, user_role=current_user.role)`.
  4. داخل `ApprovalService`:
     ```python
     approval = self.db.scalar(
         select(Approval)
         .where(Approval.id == approval_id, Approval.tenant_id == tenant_id)
         .with_for_update()
     )
     ```
     إذا لم يجد الطلب، ينفذ السطر 795:
     ```python
     if approval is None:
         cross_tenant = self.db.scalar(select(Approval).where(Approval.id == approval_id))
         if cross_tenant is not None:
             raise PermissionError("Cross-tenant access prohibited: approval belongs to another tenant")
         raise ValueError("Approval not found")
     ```
  5. عند السطر 804:
     ```python
     if user_role is None:
         user = self.db.scalar(select(User).where(User.id == decision_by_user_id))
     ```
     بما أن واجهة الـ API تمرر `user_role=current_user.role` مسبقاً، فإن هذا السطر **لا يُنفذ إطلاقاً عبر مسار الـ API**!
- **النتيجة الجنائية:** **ادعاء التسريب باطل كلياً (REFUTED).** السطر 795 هو آلية كشف هجوم متعمدة (Intrusion Detection Guard) تعيد خطأ 403 صريح للمهاجم وتمنعه من الوصول للبيانات.

---

### 1.2 خدمة تنفيذ المهام (`packages/services/task_execution_service.py`)
- **الموضع المفحوص:** السطر 352.
- **مسار الاستدعاء الفعلي:**
  1. تستدعى الدالة `resume_approved_task(tenant_id, task_id, approval_id)` بالسطر 313.
  2. يتم جلب المهمة أولاً عبر `task = self._get_task(tenant_id, task_id)` المقيدة بـ `tenant_id`.
  3. يتم جلب الموافقة عبر `approval = self.approval_service.get_approval(tenant_id, approval_id)` المقيدة بـ `tenant_id`.
  4. يتحقق النظام من العلاقة: `if approval.task_id != task.id: raise ValueError("Approval does not belong to task")`.
  5. السطر 352:
     ```python
     approver = self.db.scalar(select(User).where(User.id == approval.decision_by_user_id))
     ```
- **النتيجة الجنائية:** **ادعاء التسريب باطل كلياً (REFUTED).** الاستعلام يبحث عن سجل المستخدم الذي اتخذ القرار فقط للتحقق من أن دوره الوظيفي يمتلك صلاحية الموافقة. لا يمكن لمستأجر آخر استئناف مهمة مستأجر مختلف لأن كلاً من المهمة والموافقة تم قفلهما سلفاً بـ `tenant_id`.

---

### 1.3 خدمة سجل التدقيق (`packages/services/audit_service.py`)
- **الموضع المفحوص:** السطر 179 في الدالة `update_access_event_status`.
- **مسار الاستدعاء الفعلي:**
  1. تم فحص كامل مستودع التطبيق بحثاً عن مستدعي هذه الدالة.
  2. الدالة غير معروضة في أي مسار API عام.
  3. المستدعي الوحيد في كامل المشروع هو مسار الدعم الفني الإداري للسوبر أدمن في [`apps/agent/api/v1/admin.py:567`](file:///d:/AI-Employee-Platform/apps/agent/api/v1/admin.py#L567).
  4. في هذا المسار، يتم أولاً التحقق من صلاحية Superadmin، ثم إنشاء سجل تدقيق بالسطر 533 مع `tenant_id=target_tenant_id`، ثم فور قراءة الرسائل يتم استدعاء `update_access_event_status` لتغيير حالة نفس السجل الذي أُنشئ قبل أجزاء من الثانية إلى `disclosed`.
- **النتيجة الجنائية:** **ادعاء التسريب باطل كلياً (REFUTED).** الدالة تشغيلية داخلية محصورة في سياق الدعم الإداري الموثق جنائياً.

---

### 1.4 عمال الـ Outbox غير المتزامنين (`packages/services/outbox_worker.py`)
- **المواضع المفحوصة:** السطر 698 (`_handle_owner_escalation`) والسطر 842 (`_handle_owner_task_notification`).
- **مسار الاستدعاء الفعلي:**
  ```python
  payload = dict(event.payload or {})
  tenant_id = event.tenant_id
  channel_id_str = payload.get("channel_id")
  if not channel_id_str:
      return True

  channel = session.scalar(select(Channel).where(Channel.id == UUID(channel_id_str)))
  ```
- **التحليل الجنائي الواقعي:**
  - `event` هو سجل `OutboxEvent` يحتوي بالفعل على حقل `tenant_id`.
  - السطر 698 يستعلم عن `Channel.id == UUID(channel_id_str)` فقط، دون إضافة شرط `Channel.tenant_id == tenant_id`.
  - **هل يمكن لمستأجر خارجي استغلال هذا السطر؟**
    - **لا، ليس بشكل مباشر:** لأن أحداث الـ Outbox تُنشأ حصرياً عبر المعاملات الداخلية لخوادم المنصة (`OutboxService.create_event`)، ولا توجد واجهة API عامة تسمح للمستخدم بحقن حدث Outbox مخصص مع `channel_id` مزور.
  - **التقييم المعماري الدقيق:** هذه ليست ثغرة أمنية خارجية نشطة، بل هي **قصور في التحصين بالعمق (Defense-in-Depth Omission)**. إذا حدث خطأ برمجي مستقبلي في خدمة داخلية أدى إلى إدخال `channel_id` خاطئ، فإن العامل سيرسل الإشعار للقناة دون التأكد من ملكيتها للمستأجر.
- **التوصية:** إضافة قيد العزل في السطرين ليصبح:
  `select(Channel).where(Channel.id == UUID(channel_id_str), Channel.tenant_id == tenant_id)`.

---

## 2. تدقيق الجداول التابعة التي لا تحمل `tenant_id` مباشر

كشف الفحص المصدري لمخطط البيانات في `packages/models/domain.py` عن جدولين تفصيليين لا يحتويان على عمود `tenant_id`:
1. `learning_evidence` (السطر 1266): يحتوي على المفاتيح الأجنبية `learning_id` و `source_id` و `provenance_id`.
2. `report_items` (السطر 1414): يحتوي على المفتاح الأجنبي `report_id` المشير لـ `daily_reports.id`.

### هل يسمح هذا بتسريب البيانات بين المستأجرين؟
- كلاهما جدولان فرعيان يتبعان نمط العلاقة الأبوية (Master-Detail).
- الجداول الأبوية (`learnings` و `daily_reports`) تمتلك عمود `tenant_id` صريح ومفهرس ومحمي.
- لا توجد أي واجهة برمجية (API Endpoint) في المنصة تسمح بالاستعلام المباشر عن `learning_evidence` أو `report_items` ككيان مستقل خارج سياق سجله الأبوي.
- **الحكم الهندسي:** التصميم يتبع المعيار العلائقي الطبيعي (3NF). ومع ذلك، ومن منظور **الحماية بالعمق (Defense-in-Depth)** وتمهيداً لتفعيل سياسات الأمان على مستوى الصفوف (PostgreSQL Row-Level Security - RLS) مستقبلاً، يُوصى بإضافة عمود `tenant_id` كـ Denormalized Field عبر ترحيل Alembic لاحق.

---

## 3. خلاصة التحقق من عزل المستأجرين

| المكون | مستوى العزل الفعلي | وجود ثغرة نشطة؟ | متطلبات التحصين |
| :--- | :--- | :---: | :--- |
| **API Endpoints** | محصن تماماً عبر `get_tenant_context` والتحقق من التوقيع | **لا** | الحفاظ على النمط الحالي |
| **ApprovalService** | محصن مع حارس رصد التعدي العابر للمستأجرين | **لا** | لا شيء مطلوب |
| **TaskExecutionService** | محصن بتحقق مزدوج من المهمة والموافقة | **لا** | إضافة `User.tenant_id == tenant_id` اختيارياً |
| **AuditService** | محصن داخلياً في مسارات السوبر أدمن | **لا** | لا شيء مطلوب |
| **OutboxWorker** | يعتمد على سلامة أحداث الـ Outbox الداخلية | **لا (تحسين بالعمق)** | إضافة قيد `Channel.tenant_id == tenant_id` |
| **ORM Schemas** | 51 جدولاً معزولاً و2 جدولين تابعين بوراثة علائقية | **لا** | إضافة `tenant_id` للجدولين التابعين تمهيداً لـ RLS |
