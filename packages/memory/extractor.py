from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from packages.memory.models import (
    MemoryCandidate,
    MemoryExtractionResult,
    MemoryType,
)
from packages.memory.sanitizer import MemorySanitizer, SecretDetectedError
from packages.models.domain import Message, Task


class MemoryExtractor:
    """
    Extracts high-value, persistent memory candidates from conversations and tasks.

    Enforces:
    1. Distinguishing customer preferences from general conversation noise.
    2. Filtering out ephemeral chatter and task trivia.
    3. Mandatory security scanning to prevent credential leakage.
    4. Explicit confidence attribution based on source certainty.
    """

    # Patterns indicating general instructions, warnings, advice, or non-personal imperatives
    INSTRUCTION_OR_CAUTION_PATTERNS = [
        re.compile(r"\b(?:caution|warning|danger|note|instructions?|handle with care|when handling|as directed|at your own risk|use caution|use care)\b", re.IGNORECASE),
        re.compile(r"\b(?:تحذير|تنبيه|إرشادات|تعليمات|توخى الحذر|استخدم بحذر|احرص على الحذر)\b", re.UNICODE),
    ]

    # Stated customer preference markers (explicit and unambiguous)
    PREFERENCE_PATTERNS = [
        re.compile(r"\b(?:i prefer|my preference is|i would prefer|i'd prefer)\s+([^\.\n,]{3,100})", re.IGNORECASE),
        re.compile(r"\b(?:please (?:always )?contact me via|reach me (?:at|via)|contact me (?:on|through)|reach out to me (?:via|on))\s+([^\.\n,]{3,100})", re.IGNORECASE),
        re.compile(r"\b(?:always (?:send me|contact me via|reach me at|notify me via|email me at|call me at))\s+([^\.\n,]{3,100})", re.IGNORECASE),
        re.compile(r"\b(?:please (?:always )?use (?:whatsapp|email|sms|slack|phone|mobile) for (?:contacting me|updates|billing|invoices|receipts))\b", re.IGNORECASE),
        re.compile(r"\b(?:my preferred language is|language preference)\s*[:=]?\s*([a-zA-Z\u0600-\u06FF]{2,30})", re.IGNORECASE),
        re.compile(r"\b(?:أفضل|أفضّل|تفضيلاتي هي|لغتي المفضلة هي)\s+([^\.\n،]{3,100})", re.UNICODE),
        re.compile(r"\b(?:تواصل معي عبر|تواصلوا معي عبر|راسلني على|راسلوني عبر|أرسل لي عبر)\s+([^\.\n،]{3,100})", re.UNICODE),
        re.compile(r"\b(?:دائماً (?:تواصل معي عبر|أرسل لي عبر|استخدم (?:الواتساب|البريد|الإيميل|واتساب)))\s*([^\.\n،]{0,100})", re.UNICODE),
    ]

    # Stated business decisions
    DECISION_PATTERNS = [
        re.compile(r"\b(?:agreed to|decided on|approved|decision is|we will offer)\s+([^\.\n]{3,120})", re.IGNORECASE),
        re.compile(r"\b(?:تمت الموافقة على|تم الاتفاق على|القرار هو)\s+([^\.\n،]{3,120})", re.UNICODE),
    ]

    def extract_from_message(
        self,
        message: Message,
        *,
        customer_id: UUID | None = None,
    ) -> MemoryExtractionResult:
        """Extract memory candidates from an incoming or outgoing message."""
        candidates: list[MemoryCandidate] = []
        content = (message.content or "").strip()
        if not content:
            return MemoryExtractionResult(candidates=[], extracted_count=0, source_type="message")

        effective_customer_id = customer_id or message.customer_id

        # 1. Check for Customer Preferences
        if message.sender_type in ("customer", "user"):
            # If the entire message is an instruction/caution, do not extract personal preferences
            is_instruction = any(p.search(content) for p in self.INSTRUCTION_OR_CAUTION_PATTERNS)
            if not is_instruction:
                for pattern in self.PREFERENCE_PATTERNS:
                    match = pattern.search(content)
                    if match:
                        extracted_text = match.group(0).strip()
                        # Skip if too short or if matched text has caution/instruction markers
                        if len(extracted_text) < 5 or any(p.search(extracted_text) for p in self.INSTRUCTION_OR_CAUTION_PATTERNS):
                            continue

                        try:
                            MemorySanitizer.scan_for_secrets(extracted_text)
                            candidate = MemoryCandidate(
                                content=extracted_text,
                                memory_type=MemoryType.CUSTOMER_PREFERENCE,
                                importance=85,
                                confidence=90,  # Directly stated by human
                                customer_id=effective_customer_id,
                                conversation_id=message.conversation_id,
                                source="conversation_message",
                                source_id=str(message.id),
                                metadata_json={
                                    "sender_type": message.sender_type,
                                    "raw_message": content[:200],
                                    "extracted_at": datetime.now(timezone.utc).isoformat(),
                                },
                            )
                            candidates.append(candidate)
                        except SecretDetectedError:
                            # Silently skip candidates containing credentials
                            continue

        # 2. Check for Confirmed Decisions
        for pattern in self.DECISION_PATTERNS:
            match = pattern.search(content)
            if match:
                extracted_text = match.group(0).strip()
                if len(extracted_text) < 5:
                    continue

                try:
                    MemorySanitizer.scan_for_secrets(extracted_text)
                    candidate = MemoryCandidate(
                        content=extracted_text,
                        memory_type=MemoryType.DECISION,
                        importance=80,
                        confidence=85,
                        customer_id=effective_customer_id,
                        conversation_id=message.conversation_id,
                        source="conversation_message",
                        source_id=str(message.id),
                        metadata_json={
                            "sender_type": message.sender_type,
                            "extracted_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    candidates.append(candidate)
                except SecretDetectedError:
                    continue

        return MemoryExtractionResult(
            candidates=candidates,
            extracted_count=len(candidates),
            source_type="message",
            details={"message_id": str(message.id), "sender_type": message.sender_type},
        )

    def extract_from_task(
        self,
        task: Task,
    ) -> MemoryExtractionResult:
        """Extract task learnings and confirmed operational facts from a completed task."""
        candidates: list[MemoryCandidate] = []
        if task.status != "completed":
            return MemoryExtractionResult(candidates=[], extracted_count=0, source_type="task")

        # Evaluate task result payload
        result_payload = task.result if isinstance(task.result, dict) else {}
        verification = result_payload.get("verification") or {}
        if not verification.get("verified", False):
            return MemoryExtractionResult(candidates=[], extracted_count=0, source_type="task")

        summary = verification.get("summary") or task.objective
        clean_content = f"Execution Learning: Task '{task.title}' verified with objective: '{task.objective}'"

        try:
            MemorySanitizer.scan_for_secrets(clean_content)
            candidate = MemoryCandidate(
                content=clean_content,
                memory_type=MemoryType.TASK_LEARNING,
                importance=70,
                confidence=95,  # Verified by deterministic execution contract
                agent_id=task.agent_id,
                task_id=task.id,
                source="task_execution",
                source_id=str(task.id),
                metadata_json={
                    "task_title": task.title,
                    "verified": True,
                    "extracted_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            candidates.append(candidate)
        except SecretDetectedError:
            pass

        return MemoryExtractionResult(
            candidates=candidates,
            extracted_count=len(candidates),
            source_type="task",
            details={"task_id": str(task.id)},
        )
