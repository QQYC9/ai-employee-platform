from __future__ import annotations

import os
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.agent.main import app
from packages.core.config import Settings
from packages.core.crypto import MissingEncryptionKeyError, SecretsEncryptionService


# =============================================================================
# 1. OpenAPI & Swagger Regression Tests
# =============================================================================


def test_openapi_schema_generation_succeeds():
    """
    Regression test ensuring app.openapi() generates cleanly without
    PydanticUndefinedAnnotation / NameError for 'Any' in ToolExecuteRequest.
    """
    schema = app.openapi()
    assert schema is not None
    assert "paths" in schema
    assert len(schema["paths"]) >= 120
    assert "/api/v1/tools/{tool_id}/execute" in schema["paths"]


def test_openapi_json_endpoint_returns_200():
    """
    Regression test ensuring GET /openapi.json returns HTTP 200 and valid JSON.
    """
    client = TestClient(app)
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["info"]["title"] == "AI Employee Platform"
    assert "/api/v1/tools/{tool_id}/execute" in data["paths"]


def test_docs_html_endpoint_returns_200():
    """
    Regression test ensuring GET /docs returns HTTP 200 and renders Swagger UI HTML.
    """
    client = TestClient(app)
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "swagger-ui" in resp.text.lower()


# =============================================================================
# 2. Production Security Configuration Tests
# =============================================================================


def test_production_settings_rejects_default_dev_jwt_key():
    """
    Settings initialization must reject the default insecure development JWT key in production.
    """
    with pytest.raises(ValueError) as exc:
        Settings(
            environment="production",
            jwt_secret_key="dev-insecure-jwt-secret-replace-in-production-min32chars",
        )
    assert "cannot use default development value" in str(exc.value)


def test_production_settings_rejects_short_jwt_key():
    """
    Settings initialization must reject a JWT key with less than 32 characters in production.
    """
    with pytest.raises(ValueError) as exc:
        Settings(
            environment="production",
            jwt_secret_key="too-short-key",
        )
    assert "must be at least 32 characters" in str(exc.value)


def test_production_settings_accepts_strong_jwt_key():
    """
    Settings initialization must succeed when a sufficiently long key is provided in production.
    """
    s = Settings(
        environment="production",
        jwt_secret_key="a" * 32,
    )
    assert s.environment == "production"
    assert len(s.jwt_secret_key) >= 32


def test_development_settings_allows_default_key():
    """
    Settings initialization in development mode must permit the default dev key for local DX.
    """
    s = Settings(
        environment="development",
        jwt_secret_key="dev-insecure-jwt-secret-replace-in-production-min32chars",
    )
    assert s.environment == "development"


def test_secrets_encryption_service_in_production_requires_key():
    """
    SecretsEncryptionService must raise MissingEncryptionKeyError if no key is configured in production.
    """
    prod_settings = Settings(
        environment="production",
        jwt_secret_key="p" * 32,
        secrets_encryption_key="",
    )
    with patch("packages.core.crypto.settings", prod_settings):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(MissingEncryptionKeyError):
                SecretsEncryptionService._resolve_key()


def test_staging_and_prod_reject_insecure_jwt_key():
    """
    Settings initialization must reject insecure JWT keys in 'staging' and 'prod' as well.
    """
    for env in ("staging", "prod"):
        with pytest.raises(ValueError) as exc:
            Settings(
                environment=env,
                jwt_secret_key="dev-insecure-jwt-secret-replace-in-production-min32chars",
            )
        assert "cannot use default development value" in str(exc.value)


def test_key_rotation_mismatch_raises_decryption_error():
    """
    Decrypting with a rotated/different key must raise DecryptionError safely without leaking data.
    """
    from packages.core.crypto import DecryptionError
    crypto_a = SecretsEncryptionService("a" * 64)
    crypto_b = SecretsEncryptionService("b" * 64)
    encrypted = crypto_a.encrypt("my_secret_token")
    with pytest.raises(DecryptionError) as exc:
        crypto_b.decrypt(encrypted)
    assert "authentication tag mismatch" in str(exc.value)


def test_lifespan_aborts_on_insecure_production_jwt():
    """
    FastAPI lifespan context manager must raise RuntimeError if started in production with an insecure key.
    """
    from packages.core.config import settings
    original_env = settings.environment
    original_jwt = settings.jwt_secret_key
    try:
        settings.environment = "production"
        settings.jwt_secret_key = "dev-insecure-jwt-secret-replace-in-production-min32chars"
        with pytest.raises(RuntimeError) as exc:
            with TestClient(app):
                pass
        assert "Application startup aborted: Insecure JWT_SECRET_KEY in production" in str(exc.value)
    finally:
        settings.environment = original_env
        settings.jwt_secret_key = original_jwt
