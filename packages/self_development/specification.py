from __future__ import annotations

import re
from typing import Any
from pydantic import BaseModel, Field, field_validator


class ExecutionLimits(BaseModel):
    timeout_seconds: int = Field(default=10, ge=1, le=30)
    memory_mb: int = Field(default=256, ge=64, le=512)
    max_output_chars: int = Field(default=20000, ge=1000, le=50000)


class CapabilitySpecification(BaseModel):
    """
    Verified specification defining the capability's purpose, schemas,
    resource requirements, permissions, risk level, and test contracts.
    """
    name: str = Field(..., min_length=3, max_length=255)
    slug: str = Field(..., min_length=3, max_length=150)
    description: str = Field(..., min_length=10, max_length=2000)
    purpose: str = Field(..., min_length=10, max_length=1000)
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    required_tools: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    secrets_required: list[str] = Field(default_factory=list)
    execution_limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    risk_level: str = Field(default="medium")
    acceptance_tests: list[dict[str, Any]] = Field(default_factory=list)
    security_rules: list[str] = Field(default_factory=list)
    reference_sources: list[str] = Field(default_factory=list)

    @field_validator("slug")
    @classmethod
    def validate_slug_format(cls, v: str) -> str:
        clean = v.strip().lower()
        if not re.match(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$", clean):
            raise ValueError(
                "Slug must contain only lowercase letters, digits, underscores, or hyphens"
            )
        return clean

    @field_validator("risk_level")
    @classmethod
    def validate_risk_level(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in ("low", "medium", "high"):
            raise ValueError("risk_level must be one of: 'low', 'medium', 'high'")
        return clean


def validate_and_classify_specification(data: dict[str, Any]) -> CapabilitySpecification:
    """
    Validates the specification schema and automatically evaluates and enforces
    risk classification based on capability intent and resource requirements.
    """
    spec = CapabilitySpecification(**data)

    # Risk escalation heuristics
    escalated_risk = spec.risk_level

    # 1. Any capability requiring external secrets or credentials is high risk
    if spec.secrets_required:
        escalated_risk = "high"

    # 2. Capabilities touching monetary, payment, credential, or system admin keywords
    text_corpus = f"{spec.name} {spec.description} {spec.purpose}".lower()
    high_risk_keywords = [
        "payment", "wire", "transfer", "financial", "credit_card",
        "delete_all", "sudo", "permission", "password", "crypto",
        "root", "token_mint", "execute_raw", "shell"
    ]
    if any(k in text_corpus for k in high_risk_keywords):
        escalated_risk = "high"

    # 3. If required permissions modify tenant security policies or roles
    for perm in spec.required_permissions:
        p_lower = perm.lower()
        if any(h in p_lower for h in ["admin", "role", "permission", "policy", "secret", "user_delete"]):
            escalated_risk = "high"

    if escalated_risk != spec.risk_level and spec.risk_level != "high":
        spec.risk_level = escalated_risk

    return spec
