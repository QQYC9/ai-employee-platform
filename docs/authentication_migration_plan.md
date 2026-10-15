# Authentication Migration Plan: Replacing `X-User-ID` with Production-Grade Auth

## 1. Executive Summary & Current Status

> [!WARNING]
> **Production Authentication Status: NOT IMPLEMENTED (Development Stub Only)**  
> The current system relies on an untrusted `X-User-ID` HTTP header for identifying request callers. This header is strictly a development and test convenience stub and **must not be deployed to production**.

This document outlines the architectural assessment of the current authentication mechanism and provides a comprehensive, phased migration roadmap to transition the platform to a robust, standards-compliant authentication system prior to production release.

---

## 2. Current State Assessment

### Implementation Details
- **Location**: [`packages/auth/dependencies.py`](file:///d:/AI-Employee-Platform/packages/auth/dependencies.py)
- **Functions**:
  - `get_current_user(x_user_id: str | None = Header(default=None), db: Session)`: Resolves the user identity by parsing the incoming `X-User-ID` string as a UUID and querying the `users` table for an active user.
  - `get_current_tenant(current_user: User, db: Session)`: Resolves the tenant from the authenticated user's `tenant_id`. The tenant ID is never accepted directly from client input.
  - `activate_tenant_context(current_user: User)`: Activates the scoped tenant context for database isolation.

### Critical Vulnerabilities of `X-User-ID`
1. **No Proof of Possession / Identity Spoofing**: Any HTTP client or adversary can send an arbitrary UUID in `X-User-ID` and impersonate any user, including tenant owners and system administrators.
2. **No Cryptographic Signing or Integrity**: The header is plain text; it cannot be validated for authenticity without querying the database on every request.
3. **No Expiration or Session Lifecycle**: A user ID does not expire. There is no concept of token lifetime, token renewal, or session timeout.
4. **Header Injection & Reverse Proxy Exploitation**: If front-facing proxies, API gateways, or CDNs do not sanitize or strip incoming client headers, untrusted external callers can spoof identities directly to backend services.
5. **Lack of Delegated Authority / Scopes**: The current mechanism does not support granular API scopes, service-to-service service accounts, or third-party OAuth authorization.

---

## 3. Target Production Architecture

The platform will adopt an **OAuth 2.0 / OpenID Connect (OIDC)** and **Signed JWT Bearer Token** architecture.

### 3.1 Token Design & Claims Schema
Tokens will be issued as digitally signed JSON Web Tokens (JWT) using asymmetric cryptography (`RS256` or `EdDSA`):

```json
{
  "iss": "https://auth.ai-employee.local",
  "sub": "4c94f56a-2005-4c0a-810a-66a9c72e2133",
  "aud": "ai-employee-api",
  "exp": 1735700400,
  "iat": 1735696800,
  "jti": "b1bcfb4a-3bb1-4c17-91a1-94595faec2e8",
  "tenant_id": "76ec2a6e-d308-46aa-b2b9-e137fbca20c7",
  "role": "tenant_owner",
  "permissions": [
    "task:create",
    "task:read",
    "task:execute",
    "policy:write"
  ]
}
```

### 3.2 Key Architecture Components
1. **Asymmetric Key Rotation**: Tokens are signed by a private key and validated by public keys fetched from a JSON Web Key Set (JWKS) endpoint with local caching.
2. **Dual-Token Flow**:
   - **Access Token**: Short-lived (15 minutes), stateless JWT used in the `Authorization: Bearer <token>` header.
   - **Refresh Token**: Long-lived (7–30 days), stored as HTTP-only, Secure, SameSite cookies with Redis-backed rotation and family invalidation.
3. **Revocation & Blocklisting**: Immediate user deactivation or session revocation tracked via token `jti` in Redis cache with TTL equal to the remaining access token lifetime.
4. **Service-to-Service Authentication**: Autonomous agents and background workers authenticate using mTLS or OAuth2 Client Credentials (`client_id` + `client_secret`).

---

## 4. Phased Implementation Roadmap

### Phase A: Token Infrastructure & Auth Endpoints
- Implement `packages/auth/jwt_service.py` with `create_access_token`, `verify_token`, and JWKS validation.
- Implement `/api/v1/auth/login`, `/api/v1/auth/refresh`, and `/api/v1/auth/logout`.
- Integrate password hashing with Argon2id / bcrypt for local tenant users.

### Phase B: Dependency Modernization (Dual-Auth with Strict Guard)
- Update `get_current_user` in [`packages/auth/dependencies.py`](file:///d:/AI-Employee-Platform/packages/auth/dependencies.py):
  1. Primary check: `Authorization: Bearer <token>`. Verify cryptographic signature, expiration, issuer, and claims.
  2. Fallback check: `X-User-ID` accepted **only if**:
     - `settings.allow_dev_auth_header == True`, AND
     - `settings.environment in ("development", "test")`.
  3. Reject request with `401 Unauthorized` if neither is valid or if `X-User-ID` is attempted in staging/production.

### Phase C: Client & Test Migration
- Create test utility fixtures that generate signed test JWTs (`create_test_auth_headers(user)`).
- Migrate all integration tests from `headers={"X-User-ID": ...}` to Bearer token headers.
- Update UI/frontend applications to store tokens securely and manage refresh flows.

### Phase D: Hard Sunsetting of `X-User-ID`
- Remove the `X-User-ID` fallback completely from `packages/auth/dependencies.py`.
- Configure edge API Gateway (Nginx/Traefik/Cloudflare) to strip any incoming `X-User-ID` header.
- Run penetration tests and multi-tenant security verification.

---

## 5. Security Checklist Before Production Deployment

- [ ] `X-User-ID` header fallback removed or strictly disabled.
- [ ] JWKS endpoint configured with automatic key rotation.
- [ ] Access token TTL set to $\le 15$ minutes.
- [ ] Refresh tokens protected with HTTP-only, Secure cookies and rotation tracking in Redis.
- [ ] Rate limiting enforced on all auth endpoints (`/login`, `/refresh`).
- [ ] Audit logging configured for authentication failures and privilege escalation attempts.
