from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import urllib.error
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.agent.main import app
from packages.ai_providers.base import (
    AIAuthenticationError,
    AIConnectionError,
    AIModelNotFoundError,
    AIProvider,
    AIProviderError,
    AIProviderTimeoutError,
    AIRateLimitError,
)
from packages.ai_providers.factory import AIProviderFactory
from packages.ai_providers.gemini_provider import GeminiProvider
from packages.ai_providers.openai_compatible_provider import OpenAICompatibleProvider
from packages.auth.jwt_service import create_access_token
from packages.core.crypto import DecryptionError, SecretsEncryptionService
from packages.core.database import SessionLocal
from packages.models.domain import Credential, Integration, User
from packages.models.tenant import Tenant
from packages.services.ai_provider_service import AIProviderService

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def tenant_a(db: Session):
    t = Tenant(
        name="AI Provider Tenant A",
        slug=f"ai-tenant-a-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def tenant_b(db: Session):
    t = Tenant(
        name="AI Provider Tenant B",
        slug=f"ai-tenant-b-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def owner_user_a(db: Session, tenant_a: Tenant):
    u = User(
        tenant_id=tenant_a.id,
        name="Owner A",
        email=f"owner-a-{uuid.uuid4().hex[:8]}@example.com",
        role="tenant_owner",
        status="active",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def owner_token_a(owner_user_a: User):
    return create_access_token(
        user_id=owner_user_a.id,
        tenant_id=owner_user_a.tenant_id,
        role=owner_user_a.role,
    )


# ---------------------------------------------------------------------------
# 1. Secrets Encryption Tests (AES-256-GCM)
# ---------------------------------------------------------------------------

def test_secrets_encryption_and_decryption_roundtrip():
    crypto = SecretsEncryptionService()
    secret = "gsk_my_super_secret_production_key_12345"

    encrypted = crypto.encrypt(secret)
    assert encrypted.startswith("enc:v1:")
    assert secret not in encrypted

    decrypted = crypto.decrypt(encrypted)
    assert decrypted == secret


def test_secrets_tampered_payload_rejected():
    crypto = SecretsEncryptionService()
    secret = "secret-value"
    encrypted = crypto.encrypt(secret)

    # Tamper with the ciphertext content
    parts = encrypted.split(":")
    tampered = f"{parts[0]}:{parts[1]}:{parts[2][:-4]}AAAA"

    with pytest.raises(DecryptionError):
        crypto.decrypt(tampered)


def test_secrets_wrong_key_rejected():
    crypto_a = SecretsEncryptionService(key=b"1" * 32)
    crypto_b = SecretsEncryptionService(key=b"2" * 32)

    encrypted = crypto_a.encrypt("secret-token")
    with pytest.raises(DecryptionError):
        crypto_b.decrypt(encrypted)


def test_secrets_masking():
    crypto = SecretsEncryptionService()
    masked = crypto.mask_secret("gsk_1234567890abcdef1234")
    assert masked.startswith("gsk_")
    assert masked.endswith("1234")
    assert "..." in masked
    assert "567890abcdef" not in masked


# ---------------------------------------------------------------------------
# 2. OpenAICompatibleProvider Tests (Groq & OpenAI)
# ---------------------------------------------------------------------------

def test_openai_compatible_provider_generate_text():
    provider = OpenAICompatibleProvider(
        api_key="mock-key-1234",
        model="openai/gpt-oss-120b",
        provider_name="groq",
    )

    mock_resp = {
        "choices": [
            {"message": {"content": "Hello from Groq GPT-OSS 120B"}}
        ]
    }

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps(mock_resp).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_cm

        result = provider.generate_text("Hi", system_instruction="Be helpful")
        assert result == "Hello from Groq GPT-OSS 120B"


def test_openai_compatible_provider_generate_json():
    provider = OpenAICompatibleProvider(
        api_key="mock-key-1234",
        model="gpt-4o-mini",
        provider_name="openai",
    )

    mock_resp = {
        "choices": [
            {"message": {"content": "```json\n{\"status\": \"approved\", \"score\": 95}\n```"}}
        ]
    }

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps(mock_resp).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_cm

        result = provider.generate_json("Evaluate request")
        assert result == {"status": "approved", "score": 95}


def test_openai_compatible_provider_error_mapping():
    provider = OpenAICompatibleProvider(
        api_key="mock-key-1234",
        model="openai/gpt-oss-120b",
        provider_name="groq",
    )

    # 401 Unauthorized -> AIAuthenticationError
    with patch("urllib.request.urlopen") as mock_urlopen:
        err = urllib.error.HTTPError(
            url="https://api.groq.com",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"error": "Invalid API Key gsk_secret1234"}')
        )
        mock_urlopen.side_effect = err
        with pytest.raises(AIAuthenticationError) as exc_info:
            provider.generate_text("Hi")
        # Ensure raw key was redacted
        assert "gsk_secret1234" not in str(exc_info.value)
        assert "[REDACTED_KEY]" in str(exc_info.value)

    # 404 Not Found -> AIModelNotFoundError
    with patch("urllib.request.urlopen") as mock_urlopen:
        err = urllib.error.HTTPError(
            url="https://api.groq.com",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"error": "Model not found"}')
        )
        mock_urlopen.side_effect = err
        with pytest.raises(AIModelNotFoundError):
            provider.generate_text("Hi")

    # 429 Rate Limit -> AIRateLimitError
    with patch("urllib.request.urlopen") as mock_urlopen:
        err = urllib.error.HTTPError(
            url="https://api.groq.com",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"error": "Rate limit exceeded"}')
        )
        mock_urlopen.side_effect = err
        with pytest.raises(AIRateLimitError):
            provider.generate_text("Hi")

    # 504 Gateway Timeout -> AIProviderTimeoutError
    with patch("urllib.request.urlopen") as mock_urlopen:
        err = urllib.error.HTTPError(
            url="https://api.groq.com",
            code=504,
            msg="Gateway Timeout",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"error": "Deadline exceeded"}')
        )
        mock_urlopen.side_effect = err
        with pytest.raises(AIProviderTimeoutError):
            provider.generate_text("Hi")


def test_openai_compatible_provider_test_connection_success():
    provider = OpenAICompatibleProvider(
        api_key="mock-key-1234",
        model="openai/gpt-oss-120b",
        provider_name="groq",
    )

    mock_resp = {
        "choices": [
            {"message": {"content": "OK"}}
        ]
    }

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps(mock_resp).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_cm

        res = provider.test_connection()
        assert res["success"] is True
        assert res["provider"] == "groq"
        assert res["model"] == "openai/gpt-oss-120b"
        assert res["reply"] == "OK"
        assert res["error_type"] is None


# ---------------------------------------------------------------------------
# 3. AIProviderFactory Tests
# ---------------------------------------------------------------------------

def test_factory_creates_groq_provider():
    provider = AIProviderFactory.create_provider(
        provider_name="groq",
        api_key="mock-groq-key",
        model="openai/gpt-oss-120b",
    )
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.provider_name == "groq"
    assert provider.model == "openai/gpt-oss-120b"
    assert "groq.com" in provider.base_url


def test_factory_creates_openai_provider():
    provider = AIProviderFactory.create_provider(
        provider_name="openai",
        api_key="mock-openai-key",
        model="gpt-4o",
    )
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.provider_name == "openai"
    assert provider.model == "gpt-4o"
    assert "openai.com" in provider.base_url


def test_factory_creates_gemini_provider():
    with patch("packages.ai_providers.gemini_provider.genai.Client"):
        provider = AIProviderFactory.create_provider(
            provider_name="gemini",
            api_key="mock-gemini-key",
            model="gemini-3.8-flash",
        )
        assert isinstance(provider, GeminiProvider)
        assert provider.model == "gemini-3.8-flash"


def test_factory_switches_without_calling_gemini():
    """Verify switching to Groq does not initialize or call Gemini."""
    with patch("packages.ai_providers.gemini_provider.genai.Client") as mock_gemini_client:
        provider = AIProviderFactory.create_provider(
            provider_name="groq",
            api_key="mock-groq-key",
            model="openai/gpt-oss-120b",
        )
        assert isinstance(provider, OpenAICompatibleProvider)
        # Verify Gemini client was never instantiated
        mock_gemini_client.assert_not_called()


def test_factory_rejects_unsupported_provider():
    with pytest.raises(ValueError, match="Unsupported AI provider"):
        AIProviderFactory.create_provider(provider_name="unknown-vendor-xyz")


# ---------------------------------------------------------------------------
# 4. AIProviderService & Multi-Tenant Isolation Tests
# ---------------------------------------------------------------------------

def test_service_saves_config_encrypted_and_masks_key(
    db: Session,
    tenant_a: Tenant,
):
    service = AIProviderService(db)
    dto = service.register_or_update_config(
        tenant_id=tenant_a.id,
        name="groq-primary",
        provider="groq",
        model="openai/gpt-oss-120b",
        api_key="gsk_1234567890abcdef1234567890",
        is_default=True,
    )

    assert dto["name"] == "groq-primary"
    assert dto["provider"] == "groq"
    assert dto["model"] == "openai/gpt-oss-120b"
    assert dto["is_default"] is True
    # Verify returned key is masked
    assert "1234567890abcdef" not in dto["masked_api_key"]
    assert "gsk_" in dto["masked_api_key"]

    # Verify secret at rest in DB is encrypted with enc:v1:
    cred = db.scalar(select(Credential).where(Credential.integration_id == uuid.UUID(dto["id"])))
    assert cred is not None
    assert cred.secret_reference.startswith("enc:v1:")
    assert "gsk_1234567890abcdef" not in cred.secret_reference


def test_service_tenant_isolation(
    db: Session,
    tenant_a: Tenant,
    tenant_b: Tenant,
):
    service = AIProviderService(db)
    dto_a = service.register_or_update_config(
        tenant_id=tenant_a.id,
        name="tenant-a-groq",
        provider="groq",
        model="openai/gpt-oss-120b",
        api_key="gsk_tenant_a_secret_key",
    )

    # Tenant B lists configs -> MUST NOT see Tenant A's config
    configs_b = service.list_configs(tenant_id=tenant_b.id)
    assert not any(c["id"] == dto_a["id"] for c in configs_b)

    # Tenant B tries to get Tenant A's config -> returns None
    assert service.get_config(tenant_id=tenant_b.id, integration_id=uuid.UUID(dto_a["id"])) is None

    # Tenant B tries to test Tenant A's config -> raises ValueError
    with pytest.raises(ValueError, match="not found for tenant"):
        service.test_config(tenant_id=tenant_b.id, integration_id=uuid.UUID(dto_a["id"]))


def test_service_active_config_resolution(
    db: Session,
    tenant_a: Tenant,
):
    service = AIProviderService(db)
    service.register_or_update_config(
        tenant_id=tenant_a.id,
        name="groq-default",
        provider="groq",
        model="openai/gpt-oss-120b",
        api_key="gsk_active_key",
        is_default=True,
    )

    active_cfg = service.get_active_config(tenant_id=tenant_a.id)
    assert active_cfg is not None
    assert active_cfg["provider"] == "groq"
    assert active_cfg["model"] == "openai/gpt-oss-120b"
    assert active_cfg["decrypted_api_key"] == "gsk_active_key"


# ---------------------------------------------------------------------------
# 5. API Endpoints Integration Tests
# ---------------------------------------------------------------------------

def test_api_supported_providers():
    resp = client.get("/api/v1/ai-providers/supported")
    assert resp.status_code == 200
    data = resp.json()
    assert "gemini" in data["supported_providers"]
    assert "groq" in data["supported_providers"]
    assert "openai" in data["supported_providers"]


def test_api_configs_crud_and_test(
    db: Session,
    tenant_a: Tenant,
    owner_token_a: str,
):
    headers = {"Authorization": f"Bearer {owner_token_a}"}

    # 1. Create Config
    create_payload = {
        "name": "api-groq-config",
        "provider": "groq",
        "model": "openai/gpt-oss-120b",
        "api_key": "gsk_test_api_key_value_1234",
        "is_default": True,
    }
    create_resp = client.post("/api/v1/ai-providers/configs", json=create_payload, headers=headers)
    assert create_resp.status_code == 201
    created_data = create_resp.json()
    assert created_data["name"] == "api-groq-config"
    assert created_data["provider"] == "groq"
    config_id = created_data["id"]

    # 2. List Configs
    list_resp = client.get("/api/v1/ai-providers/configs", headers=headers)
    assert list_resp.status_code == 200
    configs = list_resp.json()
    assert any(c["id"] == config_id for c in configs)

    # 3. Test Config (Mocked HTTP response)
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_cm

        test_resp = client.post(f"/api/v1/ai-providers/configs/{config_id}/test", headers=headers)
        assert test_resp.status_code == 200
        test_data = test_resp.json()
        assert test_data["success"] is True
        assert test_data["provider"] == "groq"
