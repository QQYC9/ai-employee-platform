from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from packages.ai_providers.factory import AIProviderFactory
from packages.core.config import settings
from packages.core.crypto import SecretsEncryptionService
from packages.models.domain import Credential, Integration
from packages.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class AIProviderService:
    """
    Business service for configuring, managing, and testing AI Providers and models.

    Key Features:
      - Multi-tenant isolation: Tenant A cannot view, modify, or test Tenant B's configs.
      - Global (platform-wide) fallback: Admin can configure default integrations (tenant_id=None).
      - Zero plaintext secrets at rest: Keys are encrypted with AES-256-GCM before DB insertion.
      - Safe output: API keys are masked in all returned DTOs.
      - Non-intrusive connection testing with latency and failure categorization.
    """

    ALLOWED_PROVIDERS = {"groq", "openai", "gemini"}

    def __init__(
        self,
        db: Session,
        crypto: SecretsEncryptionService | None = None,
        audit_service: AuditService | None = None,
    ):
        self.db = db
        self.crypto = crypto or SecretsEncryptionService()
        self.audit_service = audit_service or AuditService(db)

    def register_or_update_config(
        self,
        tenant_id: UUID | None,
        name: str,
        provider: str,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        is_default: bool = False,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or update an AI provider configuration."""
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Configuration reference name cannot be empty")

        clean_provider = (provider or "").strip().lower()
        if clean_provider not in self.ALLOWED_PROVIDERS:
            raise ValueError(
                f"Unsupported AI provider: '{provider}'. Allowed: {', '.join(sorted(self.ALLOWED_PROVIDERS))}"
            )

        clean_model = (model or "").strip()
        if not clean_model:
            raise ValueError("Model name cannot be empty")

        # Find existing integration by tenant_id and name
        stmt = select(Integration).where(
            Integration.tenant_id == tenant_id,
            Integration.name == clean_name,
        )
        integration = self.db.scalar(stmt)

        if integration is None:
            integration = Integration(
                id=uuid4(),
                tenant_id=tenant_id,
                name=clean_name,
                provider=clean_provider,
                status="active",
                config={},
            )
            self.db.add(integration)

        integration.provider = clean_provider
        integration.status = "active"

        # If marking as default, unset previous default for this tenant scope
        if is_default:
            self._unset_default_integrations(tenant_id)

        cfg = dict(integration.config or {})
        cfg["model"] = clean_model
        cfg["base_url"] = base_url.strip() if base_url and base_url.strip() else None
        cfg["temperature"] = max(0.0, min(float(temperature), 2.0))
        cfg["max_tokens"] = max_tokens if max_tokens and max_tokens > 0 else None
        cfg["is_default"] = bool(is_default)
        if extra_params:
            cfg["extra_params"] = extra_params

        integration.config = cfg
        flag_modified(integration, "config")
        self.db.flush()

        # Handle API key encryption if provided
        masked_key = ""
        if api_key and api_key.strip():
            encrypted_val = self.crypto.encrypt(api_key.strip())
            masked_key = self.crypto.mask_secret(api_key.strip())

            if tenant_id is not None:
                # Find or create associated Credential record for tenant
                cred_stmt = select(Credential).where(
                    Credential.integration_id == integration.id,
                    Credential.tenant_id == tenant_id,
                )
                cred = self.db.scalar(cred_stmt)
                if cred is None:
                    cred = Credential(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        integration_id=integration.id,
                        name=f"{clean_name}-credential",
                        credential_type="api_key",
                        secret_reference=encrypted_val,
                        status="active",
                        metadata_json={"masked_key": masked_key},
                    )
                    self.db.add(cred)
                else:
                    cred.secret_reference = encrypted_val
                    meta = dict(cred.metadata_json or {})
                    meta["masked_key"] = masked_key
                    cred.metadata_json = meta
                    flag_modified(cred, "metadata_json")
                self.db.flush()
            else:
                # Platform-wide integration (tenant_id is None): store encrypted at rest in integration.config
                cfg_dict = dict(integration.config or {})
                cfg_dict["encrypted_api_key"] = encrypted_val
                cfg_dict["masked_api_key"] = masked_key
                integration.config = cfg_dict
                flag_modified(integration, "config")
                self.db.flush()
        else:
            masked_key = self._get_masked_key(integration.id)

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="ai_provider_config_saved",
            action="register_or_update_config",
            description=f"Saved AI provider config '{clean_name}' for provider '{clean_provider}'",
            event_metadata={
                "integration_id": str(integration.id),
                "provider": clean_provider,
                "model": clean_model,
                "is_default": is_default,
            },
        )

        return self._to_dto(integration, masked_key=masked_key)

    def _unset_default_integrations(self, tenant_id: UUID | None) -> None:
        """Unset is_default flag on all existing integrations in the same scope."""
        stmt = select(Integration).where(Integration.tenant_id == tenant_id)
        for integ in self.db.scalars(stmt).all():
            if integ.config and integ.config.get("is_default"):
                c = dict(integ.config)
                c["is_default"] = False
                integ.config = c
                flag_modified(integ, "config")
        self.db.flush()

    def get_config(self, tenant_id: UUID | None, integration_id: UUID) -> dict[str, Any] | None:
        """Retrieve a specific provider config by ID with strict tenant isolation."""
        stmt = select(Integration).where(
            Integration.id == integration_id,
            or_(Integration.tenant_id == tenant_id, Integration.tenant_id.is_(None)),
            Integration.status != "deleted",
        )
        integration = self.db.scalar(stmt)
        if integration is None:
            return None

        masked_key = self._get_masked_key(integration.id)
        return self._to_dto(integration, masked_key=masked_key)

    def list_configs(self, tenant_id: UUID | None = None) -> list[dict[str, Any]]:
        """List provider configs visible to the tenant (own configs + platform global)."""
        stmt = select(Integration).where(
            Integration.status != "deleted",
        )
        if tenant_id is not None:
            stmt = stmt.where(
                or_(
                    Integration.tenant_id == tenant_id,
                    Integration.tenant_id.is_(None),
                )
            )
        else:
            stmt = stmt.where(Integration.tenant_id.is_(None))

        stmt = stmt.order_by(Integration.created_at.asc())
        integrations = list(self.db.scalars(stmt).all())

        results = []
        for integ in integrations:
            masked = self._get_masked_key(integ.id)
            results.append(self._to_dto(integ, masked_key=masked))
        return results

    def get_active_config(
        self,
        tenant_id: UUID | None = None,
        provider: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Resolve the active configuration to use for AI inference.
        Resolution precedence:
          1. Tenant's default active integration
          2. Platform global default active integration
          3. First active integration for tenant
        Returns dictionary including decrypted_api_key for internal worker usage.
        """
        candidates: list[Integration] = []

        # 1. Tenant-specific
        if tenant_id is not None:
            stmt = select(Integration).where(
                Integration.tenant_id == tenant_id,
                Integration.status == "active",
            )
            if provider:
                stmt = stmt.where(Integration.provider == provider.strip().lower())
            candidates = list(self.db.scalars(stmt).all())

        # 2. Global fallback if none found
        if not candidates:
            stmt = select(Integration).where(
                Integration.tenant_id.is_(None),
                Integration.status == "active",
            )
            if provider:
                stmt = stmt.where(Integration.provider == provider.strip().lower())
            candidates = list(self.db.scalars(stmt).all())

        if not candidates:
            return None

        # Prioritize one with is_default=True
        selected = next((c for c in candidates if c.config.get("is_default")), candidates[0])

        # Decrypt API key
        decrypted_key = ""
        masked_key = ""
        cred_stmt = select(Credential).where(Credential.integration_id == selected.id)
        cred = self.db.scalar(cred_stmt)
        if cred and cred.secret_reference:
            try:
                decrypted_key = self.crypto.decrypt(cred.secret_reference)
                masked_key = self.crypto.mask_secret(decrypted_key)
            except Exception as exc:
                logger.error("Failed to decrypt API key for integration %s: %s", selected.id, exc)
        elif selected.config and selected.config.get("encrypted_api_key"):
            try:
                decrypted_key = self.crypto.decrypt(selected.config["encrypted_api_key"])
                masked_key = selected.config.get("masked_api_key", self.crypto.mask_secret(decrypted_key))
            except Exception as exc:
                logger.error("Failed to decrypt platform API key for integration %s: %s", selected.id, exc)

        dto = self._to_dto(selected, masked_key=masked_key)
        dto["decrypted_api_key"] = decrypted_key
        return dto

    def test_config(
        self,
        tenant_id: UUID | None,
        integration_id: UUID,
    ) -> dict[str, Any]:
        """
        Run an isolated connection test against the integration's provider and model.
        Updates last_test_status and last_test_result in DB.
        """
        stmt = select(Integration).where(
            Integration.id == integration_id,
            or_(Integration.tenant_id == tenant_id, Integration.tenant_id.is_(None)),
            Integration.status != "deleted",
        )
        integration = self.db.scalar(stmt)
        if integration is None:
            raise ValueError(f"Integration '{integration_id}' not found for tenant '{tenant_id}'")

        cfg = integration.config or {}
        provider_name = integration.provider
        model_name = cfg.get("model", "")
        base_url = cfg.get("base_url")

        # Decrypt API key
        cred = self.db.scalar(select(Credential).where(Credential.integration_id == integration.id))
        decrypted_key = ""
        if cred and cred.secret_reference:
            decrypted_key = self.crypto.decrypt(cred.secret_reference)
        elif integration.config and integration.config.get("encrypted_api_key"):
            decrypted_key = self.crypto.decrypt(integration.config["encrypted_api_key"])

        # Fallback to environment keys if none stored in DB
        if not decrypted_key:
            if provider_name == "groq":
                decrypted_key = settings.groq_api_key
            elif provider_name == "openai":
                decrypted_key = settings.openai_api_key
            elif provider_name == "gemini":
                decrypted_key = settings.gemini_api_key

        if not decrypted_key:
            test_result = {
                "success": False,
                "provider": provider_name,
                "model": model_name,
                "error_type": "MissingAPIKeyError",
                "error_message": f"No API key configured for {provider_name}",
            }
        else:
            provider_inst = AIProviderFactory.create_provider(
                provider_name=provider_name,
                model=model_name,
                api_key=decrypted_key,
                base_url=base_url,
                timeout_seconds=15.0,
            )
            test_result = provider_inst.test_connection()

        # Update integration status in DB
        cfg = dict(integration.config or {})
        cfg["last_test_status"] = "success" if test_result["success"] else "failed"
        cfg["last_test_result"] = test_result
        cfg["last_tested_at"] = datetime.now(timezone.utc).isoformat()
        integration.config = cfg
        flag_modified(integration, "config")
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="ai_provider_connection_tested",
            action="test_config",
            description=f"Tested connection for provider '{provider_name}': {'SUCCESS' if test_result['success'] else 'FAILED'}",
            event_metadata={
                "integration_id": str(integration.id),
                "success": test_result["success"],
                "error_type": test_result.get("error_type"),
            },
        )

        return test_result

    def _get_masked_key(self, integration_id: UUID) -> str:
        cred = self.db.scalar(select(Credential).where(Credential.integration_id == integration_id))
        if cred:
            meta = cred.metadata_json or {}
            return meta.get("masked_key", "********")
        integ = self.db.scalar(select(Integration).where(Integration.id == integration_id))
        if integ and integ.config:
            return integ.config.get("masked_api_key", "")
        return ""

    @staticmethod
    def _to_dto(integration: Integration, masked_key: str = "") -> dict[str, Any]:
        cfg = integration.config or {}
        return {
            "id": str(integration.id),
            "tenant_id": str(integration.tenant_id) if integration.tenant_id else None,
            "name": integration.name,
            "provider": integration.provider,
            "status": integration.status,
            "model": cfg.get("model", ""),
            "base_url": cfg.get("base_url"),
            "temperature": cfg.get("temperature", 0.2),
            "max_tokens": cfg.get("max_tokens"),
            "is_default": cfg.get("is_default", False),
            "masked_api_key": masked_key,
            "last_test_status": cfg.get("last_test_status", "untested"),
            "last_test_result": cfg.get("last_test_result", {}),
            "last_tested_at": cfg.get("last_tested_at"),
            "created_at": integration.created_at.isoformat() if integration.created_at else None,
            "updated_at": integration.updated_at.isoformat() if integration.updated_at else None,
        }
