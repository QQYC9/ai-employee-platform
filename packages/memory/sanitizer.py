from __future__ import annotations

import re


class SecretDetectedError(ValueError):
    """Raised when memory content or metadata contains sensitive credentials or secrets."""

    def __init__(self, pattern_name: str, message: str | None = None):
        self.pattern_name = pattern_name
        msg = message or f"Memory content contains restricted credential or secret: '{pattern_name}'"
        super().__init__(msg)


class MemorySanitizer:
    """
    Scans and sanitizes memory content and metadata to prevent
    credentials, API keys, private keys, and sensitive tokens from being persisted.
    """

    PATTERNS: dict[str, re.Pattern] = {
        "Private Key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.IGNORECASE),
        "Anthropic API Key": re.compile(r"\bsk-ant-[a-zA-Z0-9_-]{10,}\b"),
        "OpenAI API Key": re.compile(r"\bsk-(?!ant-)(?:proj-)?[a-zA-Z0-9_-]{20,}\b"),
        "Slack Token": re.compile(r"\bxox[baprs]-[a-zA-Z0-9_-]{10,}\b"),
        "GitHub Token": re.compile(r"\bgh[pousr]_[a-zA-Z0-9]{20,}\b"),
        "Google API Key": re.compile(r"\bAIza[0-9A-Za-z-_]{35}\b"),
        "AWS Access Key": re.compile(r"\b(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b"),
        "Generic JWT Token": re.compile(r"\b(?:Bearer\s+)?ey[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\b", re.IGNORECASE),
        "Password Assignment": re.compile(r"\b(?:password|passwd|pwd|secret)\s*[:=]\s*(?:['\"][^\s'\"]{4,}['\"]|[^\s'\";,\(\)\{\}]{4,})", re.IGNORECASE),
        "Database Connection URI": re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|mssql):\/\/[^\s:]+:[^\s@]+@[^\s\/]+(?:\/[^\s]*)?\b", re.IGNORECASE),
        "Raw Credential Query": re.compile(r"\b(?:api[_-]?key|auth[_-]?token)\s*[:=]\s*(?:['\"][a-zA-Z0-9_=-]{10,}['\"]|[a-zA-Z0-9_=-]{10,})", re.IGNORECASE),
    }

    @classmethod
    def scan_for_secrets(cls, text: str) -> None:
        """
        Scans text for secrets and credentials.
        Raises SecretDetectedError if any sensitive pattern is detected.
        """
        if not text:
            return

        for name, pattern in cls.PATTERNS.items():
            if pattern.search(text):
                raise SecretDetectedError(name)

    @classmethod
    def scan_dict_for_secrets(cls, data: dict) -> None:
        """Recursively scan a dictionary for sensitive secrets."""
        if not isinstance(data, dict):
            return

        for k, v in data.items():
            key_str = str(k).lower()
            if any(s in key_str for s in ("password", "secret", "private_key", "api_key", "token", "credential", "auth_token")):
                if isinstance(v, str) and len(v.strip()) > 3:
                    raise SecretDetectedError("Sensitive Key Assignment")

            if isinstance(v, str):
                cls.scan_for_secrets(v)
            elif isinstance(v, dict):
                cls.scan_dict_for_secrets(v)
            elif isinstance(v, (list, tuple)):
                for item in v:
                    if isinstance(item, str):
                        cls.scan_for_secrets(item)
                    elif isinstance(item, dict):
                        cls.scan_dict_for_secrets(item)
