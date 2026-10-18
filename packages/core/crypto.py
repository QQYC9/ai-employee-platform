from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from packages.core.config import settings

logger = logging.getLogger(__name__)


class CryptoError(ValueError):
    """Base exception for cryptography errors."""
    pass


class DecryptionError(CryptoError):
    """Raised when decryption or authentication tag validation fails."""
    pass


class MissingEncryptionKeyError(CryptoError):
    """Raised when no valid encryption key can be resolved."""
    pass


class SecretsEncryptionService:
    """
    AES-256-GCM authenticated encryption service for secrets at rest.

    Security features:
      - 256-bit AES-GCM (Galois/Counter Mode) with 128-bit authentication tag.
      - Unique cryptographically secure 96-bit (12-byte) nonce for every encryption.
      - Versioned format: `enc:v1:<nonce_b64>:<ciphertext_and_tag_b64>`.
      - Strict integrity and authenticity verification upon decryption.
      - Never prints or leaks keys in error messages.
    """

    PREFIX = "enc:v1:"
    ASSOCIATED_DATA = b"ai-employee-platform-secret-v1"

    def __init__(self, key: bytes | str | None = None):
        self._raw_key = self._resolve_key(key)
        self._aesgcm = AESGCM(self._raw_key)

    @classmethod
    def _resolve_key(cls, explicit_key: bytes | str | None = None) -> bytes:
        """Resolve a 32-byte (256-bit) encryption key from parameter or environment."""
        candidate = (
            explicit_key
            or getattr(settings, "secrets_encryption_key", None)
            or os.environ.get("SECRETS_ENCRYPTION_KEY")
        )

        if candidate:
            if isinstance(candidate, str):
                candidate_str = candidate.strip()
                # Check if 64-char hex
                if len(candidate_str) == 64:
                    try:
                        return bytes.fromhex(candidate_str)
                    except ValueError:
                        pass
                # Check if base64
                try:
                    decoded = base64.b64decode(candidate_str)
                    if len(decoded) == 32:
                        return decoded
                except Exception:
                    pass
                # Use SHA-256 digest of key string to guarantee exactly 32 bytes
                return hashlib.sha256(candidate_str.encode("utf-8")).digest()
            elif isinstance(candidate, bytes):
                if len(candidate) == 32:
                    return candidate
                return hashlib.sha256(candidate).digest()

        # Development fallback: derive deterministically from jwt_secret_key
        jwt_key = getattr(settings, "jwt_secret_key", None)
        if jwt_key and getattr(settings, "environment", "development").lower() not in ("production", "prod", "staging"):
            return hashlib.sha256(f"secrets-enc::{jwt_key}".encode("utf-8")).digest()

        raise MissingEncryptionKeyError(
            "SECRETS_ENCRYPTION_KEY is not configured and cannot be derived securely"
        )

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string using AES-256-GCM.
        Returns versioned string: `enc:v1:<nonce_b64>:<ciphertext_b64>`.
        """
        if not plaintext:
            return ""

        nonce = os.urandom(12)  # 96-bit unique nonce
        data_bytes = plaintext.encode("utf-8")

        ciphertext_and_tag = self._aesgcm.encrypt(
            nonce,
            data_bytes,
            self.ASSOCIATED_DATA,
        )

        nonce_b64 = base64.b64encode(nonce).decode("ascii")
        ct_b64 = base64.b64encode(ciphertext_and_tag).decode("ascii")

        return f"{self.PREFIX}{nonce_b64}:{ct_b64}"

    def decrypt(self, encrypted_payload: str) -> str:
        """
        Decrypt and authenticate an AES-256-GCM encrypted payload.
        Fails safely if payload is invalid, tampered, or uses wrong key.
        """
        if not encrypted_payload:
            return ""

        if not encrypted_payload.startswith(self.PREFIX):
            raise DecryptionError("Payload does not have valid encryption header prefix")

        content = encrypted_payload[len(self.PREFIX):]
        parts = content.split(":")
        if len(parts) != 2:
            raise DecryptionError("Malformed encrypted payload structure")

        try:
            nonce = base64.b64decode(parts[0])
            ciphertext_and_tag = base64.b64decode(parts[1])
            if len(nonce) != 12:
                raise DecryptionError("Invalid nonce length")

            plaintext_bytes = self._aesgcm.decrypt(
                nonce,
                ciphertext_and_tag,
                self.ASSOCIATED_DATA,
            )
            return plaintext_bytes.decode("utf-8")
        except Exception as exc:
            if isinstance(exc, DecryptionError):
                raise
            raise DecryptionError("Failed to decrypt secret: authentication tag mismatch or corrupted data") from exc

    def is_encrypted(self, value: str | None) -> bool:
        """Check if a string matches the encrypted payload format."""
        if not value or not isinstance(value, str):
            return False
        return value.startswith(self.PREFIX)

    @staticmethod
    def mask_secret(secret: str | None, visible_start: int = 4, visible_end: int = 4) -> str:
        """
        Mask a secret key for safe logging or DTO presentation.
        e.g., 'gsk_abcdef1234567890' -> 'gsk_...7890'.
        """
        if not secret:
            return ""
        s = secret.strip()
        if len(s) <= visible_start + visible_end:
            return "********"
        return f"{s[:visible_start]}...{s[-visible_end:]}"
