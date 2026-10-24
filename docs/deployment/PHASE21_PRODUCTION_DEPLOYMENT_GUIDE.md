# AI Employee Platform — دليل النشر والتشغيل الإنتاجي (Production Deployment Guide)
## المرحلة 21: Production Gateway, Frontend Containerization & Reverse Proxy Architecture

---

## 1. المعمارية الإنتاجية للمنصة (Architecture Overview)

تعتمد المنصة في بيئة الإنتاج على تصميم متعدد الطبقات يعزل شبكات الدخول عن شبكات معالجة البيانات وقواعد البيانات:

```
[ متصفحات المستخدمين والإنترنت العام ]
                     │
         (Ports 80 & 443 / TLS)
                     ▼
  ┌──────────────────────────────────────────────────────────────┐
  │                    Caddy v2 Edge Gateway                     │
  │     (إنهاء التشفير التلقائي ACME + توجيه المسارات الموحد)    │
  └───────┬──────────────────────┬──────────────────────┬────────┘
          │                      │                      │
(admin.example.com)      (app.example.com)       (api.example.com
       /*                      /*                 أو /api/*)
          ▼                      ▼                      ▼
  ┌───────────────┐      ┌───────────────┐      ┌───────────────┐
  │  Admin Dash   │      │  Tenant Dash  │      │ Backend Agent │
  │ (Nginx Alpine)│      │ (Nginx Alpine)│      │   (FastAPI)   │
  │    28.9 MB    │      │    28.9 MB    │      └───────┬───────┘
  └───────────────┘      └───────────────┘              │
  ──────────────────────────────────────────────────────┼─────────────
  شبكة البوابة العامة (gateway_network)                │
  ══════════════════════════════════════════════════════╪═════════════
  شبكة البيانات والعمليات الخلفية (backend_network)     │
                                                        ▼
                        ┌───────────────────┬───────────────────┐
                        │                   │                   │
                        ▼                   ▼                   ▼
                 ┌───────────────┐   ┌───────────────┐   ┌───────────────┐
                 │  PostgreSQL   │   │ Redis Alpine  │   │ Outbox Worker │
                 │ 17 + pgvector │   │ (مع كلمة سر)  │   │ (عملية مستقلة)│
                 └───────────────┘   └───────────────┘   └───────────────┘
```

### المكونات الأساسية للإنتاج:
1. **Caddy Gateway:** الحاوية الوحيدة التي تنشر منافذ على المضيف (`80` و`443`)، وتتولى إصدار وتجديد شهادات Let's Encrypt / ZeroSSL تلقائيًا، وتوجيه مسارات `/api/*` على نفس المصدر (Same-Origin).
2. **Frontend Dashboards:** صورتان مستقلتان بحجم فائق الخفة (`28.9 MB` لكل منهما)، تعتمدان على `nginx:alpine` لتقديم الملفات الثابتة وتوجيه مسارات SPA.
3. **Backend Agent (FastAPI):** يعمل على Python 3.13 في بيئة إنتاجية صارمة ترفض الإقلاع إذا كانت المفاتيح غير مشفرة أو ضعيفة (`JWT_SECRET_KEY` و`SECRETS_ENCRYPTION_KEY`).
4. **Standalone Outbox Worker:** معالج أحداث خلفية يعمل في حاوية مستقلة تمامًا (`python -m apps.worker`) لمنع أي تأثير على زمن استجابة خادم الويب عند معالجة المهام الثقيلة.
5. **PostgreSQL 17 + pgvector:** قاعدة البيانات العلائقية والبحث الشعاعي، معزولة كليًا داخل `backend_network` بدون أي منافذ على المضيف.
6. **Redis 7 Alpine:** ذاكرة مخبأة وأقفال موزعة وإدارة طوابير، محمية بكلمة مرور وصامدة عبر وحدة تخزين دائمة (`appendonly yes`).

---

## 2. متطلبات النشر المسبقة (Prerequisites)

قبل النشر على خادم VPS جديد (مثل Ubuntu 24.04 LTS أو Debian 12):
1. **Docker Engine و Docker Compose v2:** مثبتان ومحدثان.
2. **النطاقات وسجلات DNS:**
   - نطاق المشرف: `admin.yourdomain.com` يشير عبر سجل `A` إلى عنوان IP العام للخادم.
   - نطاق العملاء: `app.yourdomain.com` يشير عبر سجل `A` إلى IP الخادم.
   - نطاق الـ API: `api.yourdomain.com` يشير عبر سجل `A` إلى IP الخادم.
3. **الجدار الناري (Firewall / Security Groups):**
   - السماح بالمرور عبر المنافذ: `80/tcp` (HTTP) و `443/tcp` (HTTPS).
   - حظر المنافذ: `5432` و `6379` و `8000` نهائيًا من الوصول الخارجي.

> [!IMPORTANT]
> **بناء أو رفع صور الواجهات قبل النشر على خادم خارجي:**
> صورتا الواجهتين `ai-employee-admin-dashboard:prod` و `ai-employee-tenant-dashboard:prod` تم بناؤهما محليًا.
> عند النشر على خادم VPS آخر، يجب:
> إما رفع الصورتين إلى سجل حاويات خاص (Container Registry مثل Docker Hub أو GitHub Packages أو AWS ECR)،
> أو نسخهما بصيغة tar:
> ```bash
> docker save -o frontend_images.tar ai-employee-admin-dashboard:prod ai-employee-tenant-dashboard:prod
> scp frontend_images.tar user@vps:/opt/ai-employee/
> ssh user@vps "docker load -i /opt/ai-employee/frontend_images.tar"
> ```

---

## 3. خطوات النشر على خادم الإنتاج (Step-by-Step Deployment)

### الخطوة 1: استنساخ المستودع وتجهيز المسار
```bash
mkdir -p /opt/ai-employee
cd /opt/ai-employee
git clone -b checkpoint/phase-12-knowledge-base <REPO_URL> .
```

### الخطوة 2: إنشاء ملف متغيرات بيئة الإنتاج (`.env.prod`)
```bash
cp .env.prod.example .env.prod
chmod 600 .env.prod
```

قم بتحرير الملف وتوليد مفاتيح تشفير قوية:
```bash
# توليد مفتاح JWT ومفتاح التشفير وكلمات المرور:
openssl rand -hex 32  # استخدم الناتج لـ JWT_SECRET_KEY
openssl rand -hex 32  # استخدم الناتج لـ SECRETS_ENCRYPTION_KEY
openssl rand -hex 24  # استخدم الناتج لـ POSTGRES_PASSWORD
openssl rand -hex 24  # استخدم الناتج لـ REDIS_PASSWORD
```

### الخطوة 3: بناء صورة الـ Backend الإنتاجية
```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod build backend worker
```

---

## 4. إجراء ترحيل قاعدة البيانات والنسخ الاحتياطي (Database Migrations & Backups)

> [!CAUTION]
> **ممنوع تشغيل migrations تلقائيًا عند إقلاع الحاويات:**
> تشغيل الترحيل كأمر منفصل يمنع تصادم أقفال قاعدة البيانات (Schema Lock Deadlocks) ويحمي البيانات من التلف.

### أ) أخذ نسخة احتياطية إجبارية قبل أي ترقية:
قبل تشغيل أي ترحيل لقاعدة البيانات، خذ نسخة احتياطية كاملة:
```bash
# إنشاء مجلد النسخ الاحتياطية
mkdir -p /opt/ai-employee/backups

# أخذ لقطة فورية متوافقة مع pgvector
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T postgres \
  pg_dump -U ai_employee_admin ai_employee_prod > /opt/ai-employee/backups/backup_$(date +%Y%m%d_%H%M%S).sql
```

### ب) تنفيذ ترحيلات Alembic:
يتم تنفيذ الترحيل كأمر منفصل ومؤقت (`--rm`):
```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend \
  alembic upgrade head
```

### ج) استعادة النسخة الاحتياطية في حال الطوارئ (Rollback / Disaster Recovery):
إذا حدث خلل أثناء الترحيل، يمكنك استعادة النسخة السابقة فورًا:
```bash
# 1. إيقاف خادم التطبيق مؤقتًا لمنع كتابة بيانات جديدة
docker compose -f docker-compose.prod.yml --env-file .env.prod stop backend worker

# 2. استعادة البيانات من ملف النسخة الاحتياطية
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T postgres \
  psql -U ai_employee_admin -d ai_employee_prod < /opt/ai-employee/backups/backup_YYYYMMDD_HHMMSS.sql

# 3. إعادة تشغيل التطبيق
docker compose -f docker-compose.prod.yml --env-file .env.prod start backend worker
```

---

## 5. تشغيل المنصة والتحقق من الجاهزية (Startup & Verification)

### تشغيل كافة الخدمات في الخلفية:
```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

### فحص حالة الحاويات وفحوص الجاهزية (`healthchecks`):
```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
```
يجب أن تظهر كافة الحاويات بحالة `healthy`:
- `ai_employee_prod_caddy`: Up (Ports: 0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp)
- `ai_employee_prod_admin_dashboard`: Up (healthy)
- `ai_employee_prod_tenant_dashboard`: Up (healthy)
- `ai_employee_prod_backend`: Up (healthy)
- `ai_employee_prod_worker`: Up
- `ai_employee_prod_postgres`: Up (healthy)
- `ai_employee_prod_redis`: Up (healthy)

### فحص سجلات التشغيل:
```bash
# سجلات البوابة
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f caddy

# سجلات الـ Backend
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f backend

# سجلات معالج الأحداث
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f worker
```

---

## 6. خطة الاختبار المحلي على Windows Docker Desktop

لإجراء اختبار ومحاكاة كاملة للبنية الإنتاجية محليًا دون الحاجة لنطاق عام أو خادم VPS:

### 1. تعديل ملف `hosts` في Windows:
قم بفتح المفكرة بصلاحيات مسؤول (Administrator) وعدل المسار:
`C:\Windows\System32\drivers\etc\hosts`
أضف الأسطر التالية:
```text
127.0.0.1 admin.local
127.0.0.1 app.local
127.0.0.1 api.local
```

### 2. إعداد `.env.prod` للاختبار المحلي:
قم بضبط النطاقات المحلية في `.env.prod`:
```ini
ADMIN_DOMAIN=admin.local
APP_DOMAIN=app.local
API_DOMAIN=api.local
CADDY_AUTO_HTTPS=off
```
*(أو استخدام `tls internal` لشهادات HTTPS محلية ذاتية التوقيع)*

### 3. التحقق غير المدمر من صحة الإعدادات:
```powershell
docker compose -f docker-compose.prod.yml config
```

### 4. اختبار الوصول عبر المتصفح:
- المشرف: `http://admin.local` -> التحقق من تحميل لوحة الإدارة وتسجيل الدخول.
- العميل: `http://app.local` -> التحقق من تحميل لوحة العميل وعزل البيانات.
- واجهة البرمجة: `http://api.local/health` -> استجابة `{"status": "healthy"}`.
