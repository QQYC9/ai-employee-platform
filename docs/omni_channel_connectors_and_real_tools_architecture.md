# Omni-Channel Connectors & Real Tools Architecture (Phase 15)

## 1. Overview & Architectural Goals

Phase 15 introduces a production-oriented tool execution runtime and omni-channel communication layer for the AI Employee Platform. It expands the platform from a conversational and planning engine into an operational system capable of executing real tools, generating persistent documents, and communicating with customers across Meta WhatsApp Cloud API, Telegram Bot API, and Email.

### Key Architectural Tenets
1. **Unified Tool Contract**: Every tool defines a formal contract with Pydantic input schemas, risk categories, execution timeouts, required permissions, and idempotency guarantees.
2. **Strict Defense-in-Depth (Anti-SSRF)**: Real HTTP requests enforce socket-level DNS verification, private/loopback/cloud-metadata subnet blocking, manual redirect hop validation, and response stream size limits.
3. **Multi-Tenant Sandboxing**: Business data tools enforce database isolation using SQLAlchemy ORM; document generation enforces physical directory sandboxing with canonical path traversal checks.
4. **Omni-Channel Transport Abstraction**: Connectors decouple external transport protocols (Meta Graph API, Telegram Bot API, SMTP/MIME) from internal conversation and message domain models.
5. **Zero Plaintext Secrets at Rest**: Channel access tokens, webhook secrets, bot tokens, and SMTP passwords are encrypted using AES-256-GCM authenticated encryption (`SecretsEncryptionService`).
6. **Side-Effect Deduplication**: Inbound webhooks and outbound actions enforce idempotency via the persistent `IdempotencyService`.

---

## 2. Unified Real Tools Runtime (`packages/tools/`)

### 2.1 Tool Contract & Risk Levels
Tools are categorized by risk level:
- `READ_ONLY`: Safe read operations (e.g. `customer_search`, `customer_get`, `task_query`, `business_summary`).
- `LOW`: Minimal side effects.
- `MEDIUM`: State updates or external communication (e.g. `http_request`, `customer_create_or_update`, `task_create`, `generate_document`).
- `HIGH` / `CRITICAL`: High-impact administrative or financial operations requiring strict approval policies.

### 2.2 Built-In Real Tools
| Slug | Category | Description | Idempotent |
| :--- | :--- | :--- | :--- |
| `http_request` | Network / Webhook | SSRF-safe HTTP request with IP verification and redirect inspection | Yes |
| `customer_search` | Business Data | Query customers by name, email, or phone within tenant | Yes |
| `customer_get` | Business Data | Fetch customer profile, status, and metadata | Yes |
| `customer_create_or_update` | Business Data | Create or update customer record within tenant | Yes |
| `task_query` | Business Data | Query task status and execution logs | Yes |
| `task_create` | Business Data | Create operational task within tenant | Yes |
| `business_summary` | Business Data | Aggregate operational summary (customers, tasks, approvals) | Yes |
| `generate_document` | Document Generator | Generate sandboxed HTML (RTL), PDF, Markdown, JSON, or TXT | Yes |

---

## 3. Anti-SSRF HTTP Engine (`packages/tools/http_tool.py`)

The `SSRFGuard` validates all outgoing HTTP/Webhook requests before execution:
1. **Scheme & Port Restrictions**: Only `http` and `https` schemes; ports restricted to standard web ports (80, 443, 8080, 8443).
2. **Blocked Keywords & Metadata**: Blocks `localhost`, `*.internal`, `*.local`, `metadata.google.internal`, `169.254.169.254`, `instance-data`.
3. **Socket DNS Pre-Resolution**: Resolves hostname to all IPv4 and IPv6 addresses via `socket.getaddrinfo`. Every resolved IP is checked against:
   - Loopback: `127.0.0.0/8`, `::1`
   - RFC 1918 Private: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
   - Cloud Metadata / Link-Local: `169.254.0.0/16`, `fe80::/10`
   - Carrier-Grade NAT: `100.64.0.0/10`
   - IPv6 Unique Local: `fc00::/7`
4. **Manual Redirect Inspection**: Disables uninspected automatic redirects (`follow_redirects=False`). Inspects each redirect `Location` hop through `SSRFGuard` before proceeding (up to 5 hops). Cross-origin redirects strip sensitive `Authorization` headers.
5. **Response Size Guard**: Streams response chunks; aborts with `ResponseTooLargeError` if downloaded bytes exceed `max_response_bytes` (default 1MB, configurable up to 10MB).
6. **Header Masking**: Redacts `Authorization`, `X-Api-Key`, `Cookie`, etc., in logs and execution results.

---

## 4. Sandboxed Document Generator (`packages/tools/document_tool.py`)

- **Physical Sandboxing**: Files are written to `storage/documents/<tenant_id>/`.
- **Path Traversal Defense**: Validates that `os.path.commonpath([tenant_dir, target_file]) == tenant_dir`. Rejects any traversal sequences (`..`, absolute paths, symlinks).
- **Format Support**:
  - `html`: Responsive layout with automatic `dir="rtl"` and Arabic typography support.
  - `pdf`: Native, standards-compliant PDF 1.4 byte-stream generation.
  - `md`: GitHub Flavored Markdown document.
  - `txt`: Plain text document.
  - `json`: Structured JSON document.
- **Database Tracking**: Persisted in `generated_documents` table with `id`, `tenant_id`, `filename`, `file_size`, `mime_type`, and `sha256_hash`.
- **Authenticated Retrieval**: `GET /api/v1/documents/{document_id}/download` enforces tenant authentication.

---

## 5. Omni-Channel Connectors Architecture (`packages/connectors/`)

```
   [ Meta WhatsApp Cloud ]      [ Telegram Bot API ]      [ Email SMTP / MIME ]
             │                           │                          │
             ▼                           ▼                          ▼
   WhatsAppCloudConnector        TelegramConnector            EmailConnector
             │                           │                          │
             └───────────────────────────┼──────────────────────────┘
                                         ▼
                                BaseConnector (ABC)
                                         │
                                         ▼
                            ChannelService / OutboxService
                                         │
                                         ▼
                         ConversationalAgentEngine
```

### 5.1 WhatsApp Cloud API (`packages/connectors/whatsapp.py`)
- Official Meta Graph API v19.0.
- Webhook Challenge (GET): Validates `hub.mode == "subscribe"` and `hub.verify_token`, returns `hub.challenge`.
- Signature Verification (POST): Computes HMAC-SHA256 of raw request body using `app_secret` and compares with `X-Hub-Signature-256`.
- Message Dispatch: POST to `https://graph.facebook.com/v19.0/{phone_number_id}/messages`.
- Diagnostic Connection: GET `https://graph.facebook.com/v19.0/{phone_number_id}`.

### 5.2 Telegram Bot API (`packages/connectors/telegram.py`)
- Webhook Authentication: Validates `X-Telegram-Bot-Api-Secret-Token`.
- Inbound Parsing: Extracts chat ID, sender name, message ID, and content.
- Message Dispatch: POST to `https://api.telegram.org/bot{token}/sendMessage`.
- Diagnostic Connection: GET `https://api.telegram.org/bot{token}/getMe`.

### 5.3 Email Connector (`packages/connectors/email.py`)
- Standard SMTP client with STARTTLS / SSL support.
- MIME inbound parser for raw RFC 822 email bytes.
- Recipient email address validation.
- Diagnostic Connection: Connects, performs EHLO, TLS negotiation, and authentication.

---

## 6. Digital Employee Engine Integration

1. **`ConversationalAgentEngine`**:
   - Integrated with `ToolRegistry` and `ToolExecutor`.
   - `execute_tool_action(tenant_id, tool_slug, parameters)`:
     - Validates tool contract.
     - Evaluates `DecisionEngine.decide(...)`.
     - Blocks execution and logs audit if `APPROVAL_REQUIRED` or `DENY`.
     - Executes via `ToolExecutor` if `ALLOW`.
     - Bounded iterations (max 3 tool calls per message turn).
2. **`AgentOrchestrator`**:
   - Automatically binds `ToolRegistry` tools into `ToolExecutor.handlers` during initialization.

---

## 7. Database Migrations

- Revision: `e5f6a7b8c9d0` (revises `d4e5f6a7b8c9`).
- Table `generated_documents`:
  - Columns: `id` (UUID PK), `tenant_id` (FK tenants.id CASCADE), `title`, `document_type`, `format`, `filename`, `file_path`, `file_size`, `mime_type`, `sha256_hash`, `created_by_agent_id` (FK agents.id SET NULL), `metadata_json`, `created_at`, `updated_at`.
  - Indexes: `tenant_id`, `document_type`, `format`, `created_by_agent_id`, `created_at`.
