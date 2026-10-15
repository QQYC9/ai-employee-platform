from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://ai_employee:change_me_local@127.0.0.1:5433/ai_employee"
    redis_url: str = "redis://localhost:6379/0"

    ai_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: float = 30.0
    ai_planning_enabled: bool = False

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

    @property
    def is_dev_auth_allowed(self) -> bool:
        """
        Check if X-User-ID header authentication is permitted.
        Strictly disallowed in production and staging environments.
        """
        if self.environment.lower() in ("production", "prod", "staging"):
            return False
        return self.allow_dev_auth_header

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
