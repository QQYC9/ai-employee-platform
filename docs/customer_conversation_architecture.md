# Customer & Omni-Channel Conversation Hub Architecture

## 1. Overview

The **Customer & Omni-Channel Conversation Hub** serves as the primary communication and relationship gateway between commercial B2B tenants, their end-customers, and Autonomous Digital Employees.

In enterprise automation, Digital Employees are not isolated task executors; they continuously communicate with human customers and internal stakeholders across diverse channels:
1. **Omni-Channel Connectivity**: Web Chat, WhatsApp, Email, Slack, and programmatic REST APIs.
2. **Unified Customer Profile**: Centralized, tenant-scoped customer identity records with contact channels, business profiles, and communication history.
3. **Structured Conversation Threads**: State-managed conversation sessions with complete chronological message logs, participant attribution (`customer`, `agent`, `user`, `system`), and lifecycle statuses (`open`, `pending`, `resolved`, `closed`).
4. **Strict Multi-Tenant Isolation**: Zero cross-tenant data leakage across customers, channels, conversations, and message histories.
5. **Auditable Communication**: Full audit trail recording customer creation, channel configuration, conversation creation, status transitions, and message dispatch.

---

## 2. Domain Model Architecture

### 2.1 Entities & Relationships
```
[Tenant]
   ├──> [Customer] (1:N)
   ├──> [Channel] (1:N) (webchat, whatsapp, email, api, slack)
   └──> [Conversation] (1:N)
           ├── References [Customer] (optional / linked)
           ├── References [Channel] (optional / linked)
           └──> [Message] (1:N)
                   ├── sender_type: customer | agent | user | system
                   ├── sender_id: UUID (optional user/agent ID)
                   └── message_type: text | tool_result | event | attachment
```

### 2.2 Lifecycle & Status Management

#### Customer Statuses:
- `active`: Standard customer profile eligible for communication.
- `inactive`: Inactive or dormant customer.
- `blocked`: Prohibited from interacting with automated agents or initiating sessions.
- `deleted`: Soft-deleted record.

#### Conversation Statuses:
- `open`: Active conversation thread awaiting or undergoing interaction.
- `pending`: Paused or awaiting customer response / external input.
- `resolved`: Objective completed; customer satisfied.
- `closed`: Formally terminated session with `closed_at` timestamp.

---

## 3. Core Services

### 3.1 CustomerService (`packages/services/customer_service.py`)
- Manages tenant-isolated customer records.
- Provides search and lookups by unique email, phone, or name query.
- Tracks custom profile JSON data and flexible metadata.
- Enforces soft-delete and status lifecycle.

### 3.2 ChannelService (`packages/services/channel_service.py`)
- Manages communication channel configurations (`webchat`, `whatsapp`, `email`, `slack`, `api`).
- Validates channel providers and sanitizes credential configurations.
- Enforces tenant boundary and status transitions (`active`, `inactive`, `maintenance`).

### 3.3 ConversationService (`packages/services/conversation_service.py`)
- Orchestrates multi-channel conversation sessions.
- Appends and timestamps incoming/outgoing messages.
- Automatically updates `last_message_at` and manages auto-closing / reopening logic.
- Returns chronological message threads with pagination.

---

## 4. API Endpoints

| Endpoint | Method | Role | Description |
|---|---|---|---|
| `/api/v1/customers` | POST | Member+ | Create customer record |
| `/api/v1/customers` | GET | Member+ | List/search customers |
| `/api/v1/customers/{id}` | GET | Member+ | Retrieve customer details |
| `/api/v1/customers/{id}` | PATCH | Member+ | Update customer profile |
| `/api/v1/customers/{id}` | DELETE | Admin+ | Soft-delete customer |
| `/api/v1/channels` | POST | Admin+ | Register communication channel |
| `/api/v1/channels` | GET | Member+ | List channels |
| `/api/v1/channels/{id}` | GET | Member+ | Retrieve channel details |
| `/api/v1/channels/{id}` | PATCH | Admin+ | Update channel config/status |
| `/api/v1/channels/{id}` | DELETE | Admin+ | Delete channel |
| `/api/v1/conversations` | POST | Member+ | Start conversation thread |
| `/api/v1/conversations` | GET | Member+ | List conversation threads |
| `/api/v1/conversations/{id}` | GET | Member+ | Retrieve conversation details |
| `/api/v1/conversations/{id}/status` | PATCH | Member+ | Update conversation status |
| `/api/v1/conversations/{id}/messages` | POST | Member+ | Append message to conversation |
| `/api/v1/conversations/{id}/messages` | GET | Member+ | List messages chronologically |
