from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://ai_employee:change_me_local@127.0.0.1:5433/ai_employee"
    test_database_url: str | None = None
    redis_url: str = "redis://localhost:6379/0"

    ai_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_timeout_seconds: float = 30.0

    # Groq Provider Settings
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_timeout_seconds: float = 30.0

    # OpenAI Provider Settings
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout_seconds: float = 30.0

    # Secrets Encryption Key (AES-256-GCM)
    secrets_encryption_key: str = ""

    # Webhook Base URL
    webhook_base_url: str | None = None

    ai_planning_enabled: bool = False

    # Background Worker Settings
    enable_embedded_worker: bool = False
    outbox_worker_poll_interval: float = 1.0
    outbox_worker_batch_size: int = 10
    outbox_worker_lock_timeout: int = 300


    # Production Authentication & Security Settings
    environment: str = "development"
    allow_dev_auth_header: bool = True
    jwt_secret_key: str = "dev-insecure-jwt-secret-replace-in-production-min32chars"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "ai-employee-platform"
    jwt_audience: str = "ai-employee-api"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    # Rate Limiting
    rate_limit_login_per_minute: int = 10
    rate_limit_planning_per_minute: int = 30

    # Frontend Dashboards
    tenant_dashboard_url: str | None = None
    admin_dashboard_url: str | None = None
    password_reset_token_expire_minutes: int = 30

    @property
    def effective_test_database_url(self) -> str:
        """
        Derives or returns the isolated test database URL.
        Preserves host, port, credentials, and driver while targeting 'ai_employee_test'.
        """
        if self.test_database_url:
            return self.test_database_url
        from packages.core.safety_guard import derive_test_database_url
        return derive_test_database_url(self.database_url, "ai_employee_test")

    @property
    def is_dev_auth_allowed(self) -> bool:
        """
        Check if X-User-ID header authentication is permitted.
        Strictly disallowed in production and staging environments.
        """
        if self.environment.lower() in ("production", "prod", "staging"):
            return False
        return self.allow_dev_auth_header

    @property
    def effective_webhook_base_url(self) -> str:
        """
        Returns the resolved public base URL for webhooks.
        Reads WEBHOOK_BASE_URL env var or defaults to active public tunnel.
        """
        clean_url = (self.webhook_base_url or "").strip().rstrip("/")
        if clean_url:
            return clean_url
        return "https://nov-marie-passport-pet.trycloudflare.com"

    @property
    def effective_tenant_dashboard_url(self) -> str:
        """
        Returns the resolved tenant dashboard URL.
        In production/staging, requires TENANT_DASHBOARD_URL to be a public URL and strictly disallows localhost.
        In development/testing, falls back to http://localhost:5173 if unspecified.
        """
        env_clean = (self.environment or "").strip().lower()
        clean_url = (self.tenant_dashboard_url or "").strip()
        if env_clean in ("production", "prod", "staging"):
            if not clean_url or "localhost" in clean_url or "127.0.0.1" in clean_url:
                import logging
                logging.getLogger(__name__).error(
                    "Production configuration error: TENANT_DASHBOARD_URL is required and cannot be localhost in %s",
                    self.environment,
                )
                raise RuntimeError(
                    f"Production configuration error: TENANT_DASHBOARD_URL is required and cannot be localhost in '{self.environment}'"
                )
            return clean_url
        return clean_url or "http://localhost:5173"

    @model_validator(mode="after")
    def validate_production_security(self) -> Settings:
        """
        Rejects insecure development defaults when running in production or staging.
        Prevents starting with default JWT secrets or insufficient key lengths.
        """
        env_clean = (self.environment or "").strip().lower()
        if env_clean in ("production", "prod", "staging"):
            insecure_jwt_defaults = {
                "dev-insecure-jwt-secret-replace-in-production-min32chars",
                "secret",
                "changeme",
                "password",
            }
            clean_jwt = (self.jwt_secret_key or "").strip()
            if not clean_jwt or clean_jwt in insecure_jwt_defaults or clean_jwt.startswith("dev-"):
                raise ValueError(
                    f"Production startup rejected: JWT_SECRET_KEY cannot use default development value in '{self.environment}' environment."
                )
            if len(clean_jwt) < 32:
                raise ValueError(
                    f"Production startup rejected: JWT_SECRET_KEY must be at least 32 characters in '{self.environment}' environment."
                )

            if self.secrets_encryption_key:
                clean_enc = self.secrets_encryption_key.strip()
                if len(clean_enc) < 32:
                    raise ValueError(
                        f"Production startup rejected: SECRETS_ENCRYPTION_KEY must be at least 32 characters or 64-char hex in '{self.environment}' environment."
                    )

            clean_dash_url = (self.tenant_dashboard_url or "").strip()
            if not clean_dash_url:
                import logging
                logging.getLogger(__name__).error(
                    "Production configuration error: TENANT_DASHBOARD_URL is missing in environment '%s'",
                    self.environment,
                )
                raise ValueError(
                    f"Production startup rejected: TENANT_DASHBOARD_URL is a required setting in '{self.environment}' environment."
                )
            if "localhost" in clean_dash_url or "127.0.0.1" in clean_dash_url:
                import logging
                logging.getLogger(__name__).error(
                    "Production configuration error: TENANT_DASHBOARD_URL cannot use localhost/127.0.0.1 in environment '%s'",
                    self.environment,
                )
                raise ValueError(
                    f"Production startup rejected: TENANT_DASHBOARD_URL cannot use localhost/127.0.0.1 in '{self.environment}' environment."
                )

        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
