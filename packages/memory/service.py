from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import hashlib
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.models.domain import Memory
from packages.memory.models import MemoryCandidate, MemoryStatus, MemoryType
from packages.memory.sanitizer import MemorySanitizer
from packages.services.audit_service import AuditService


class MemoryService:
    """
    Core management service for Digital Employee Long-Term Memories.

    Enforces:
    1. Mandatory tenant isolation.
    2. Secret sanitization and credential rejection.
    3. Transparent conflict resolution and fact superseding.
    4. Audited lifecycle transitions.
    5. Concurrency-safe deduplication via deterministic scoped fingerprints.
    """

    def __init__(self, db: Session, audit_service: AuditService | None = None):
        self.db = db
        self.audit_service = audit_service or AuditService(db)

    @staticmethod
    def compute_dedup_hash(
        tenant_id: UUID,
        memory_type: str,
        content: str,
        customer_id: UUID | None = None,
        agent_id: UUID | None = None,
    ) -> str:
        """Compute a deterministic scoped fingerprint for deduplication."""
        clean_content = " ".join((content or "").strip().lower().split())
        clean_type = (memory_type or "general").strip().lower()
        cust_part = str(customer_id) if customer_id else "global"
        agent_part = str(agent_id) if agent_id else "any"
        raw_key = f"{tenant_id}:{clean_type}:{clean_content}:{cust_part}:{agent_part}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def create_memory(
        self,
        tenant_id: UUID,
        content: str,
        *,
        memory_type: str = MemoryType.GENERAL,
        importance: int = 50,
        confidence: int = 50,
        agent_id: UUID | None = None,
        user_id: UUID | None = None,
        customer_id: UUID | None = None,
        conversation_id: UUID | None = None,
        task_id: UUID | None = None,
        source: str = "manual",
        metadata_json: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
        status: str = MemoryStatus.ACTIVE,
    ) -> Memory:
        """Create and store a validated, secret-scanned memory."""
        clean_content = (content or "").strip()
        if not clean_content:
            raise ValueError("Memory content cannot be empty")

        clean_type = (memory_type or MemoryType.GENERAL).strip().lower()
        if clean_type not in MemoryType.ALL:
            raise ValueError(f"Invalid memory type: '{memory_type}'")

        clean_status = (status or MemoryStatus.ACTIVE).strip().lower()
        if clean_status not in MemoryStatus.ALL:
            raise ValueError(f"Invalid memory status: '{status}'")

        # 1. Security scan: reject any credentials or secrets
        MemorySanitizer.scan_for_secrets(clean_content)
        if metadata_json:
            MemorySanitizer.scan_dict_for_secrets(metadata_json)

        # 2. Compute deterministic scoped fingerprint
        dedup_hash = self.compute_dedup_hash(
            tenant_id=tenant_id,
            memory_type=clean_type,
            content=clean_content,
            customer_id=customer_id,
            agent_id=agent_id,
        )

        meta = dict(metadata_json or {})
        # Security guard: Customer conversation messages cannot establish store decisions or policies
        if clean_type == MemoryType.DECISION:
            sender_type = str(meta.get("sender_type") or "").strip().lower()
            if sender_type == "customer" or (customer_id is not None and source == "conversation_message"):
                raise ValueError("Customer messages cannot establish store decisions or policies")

        if customer_id is not None:
            meta["customer_id"] = str(customer_id)
        if conversation_id is not None:
            meta["conversation_id"] = str(conversation_id)
        if task_id is not None:
            meta["task_id"] = str(task_id)
        meta["source"] = source
        meta["dedup_hash"] = dedup_hash

        # 3. Concurrency guard: Acquire transaction-scoped advisory lock in PostgreSQL
        # to ensure mutual exclusion under simultaneous concurrent requests for the exact same scoped fact
        bind = getattr(self.db, "bind", None)
        if bind is None and hasattr(self.db, "get_bind"):
            try:
                bind = self.db.get_bind()
            except Exception:
                bind = None

        if bind and getattr(getattr(bind, "dialect", None), "name", "") == "postgresql":
            try:
                self.db.execute(select(func.pg_advisory_xact_lock(func.hashtext(dedup_hash))))
            except Exception:
                pass

        # 4. Duplicate suppression: check if exact content already active for same scope
        existing = self._find_exact_duplicate(
            tenant_id=tenant_id,
            content=clean_content,
            memory_type=clean_type,
            customer_id=customer_id,
            agent_id=agent_id,
            dedup_hash=dedup_hash,
        )
        if existing is not None:
            # Refresh confidence and updated_at rather than adding duplicate
            if confidence > existing.confidence:
                existing.confidence = confidence
            if importance > existing.importance:
                existing.importance = importance
            self.db.flush()
            return existing

        bounded_importance = max(0, min(int(importance), 100))
        bounded_confidence = max(0, min(int(confidence), 100))

        memory = Memory(
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            memory_type=clean_type,
            content=clean_content,
            importance=bounded_importance,
            confidence=bounded_confidence,
            status=clean_status,
            metadata_json=meta,
            expires_at=expires_at,
        )

        # Use nested transaction (savepoint) to isolate insert conflicts safely
        try:
            with self.db.begin_nested():
                self.db.add(memory)
                self.db.flush()
        except IntegrityError:
            winner = self._find_exact_duplicate(
                tenant_id=tenant_id,
                content=clean_content,
                memory_type=clean_type,
                customer_id=customer_id,
                agent_id=agent_id,
                dedup_hash=dedup_hash,
            )
            if winner is not None:
                if confidence > winner.confidence:
                    winner.confidence = confidence
                if importance > winner.importance:
                    winner.importance = importance
                return winner
            raise

        self.audit_service.record_event(
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            event_type="memory_created",
            action="create_memory",
            description=f"Created {clean_type} memory: '{clean_content[:80]}'",
            event_metadata={
                "memory_id": str(memory.id),
                "memory_type": clean_type,
                "importance": bounded_importance,
                "confidence": bounded_confidence,
                "customer_id": str(customer_id) if customer_id else None,
            },
        )

        return memory

    def save_candidate(
        self,
        tenant_id: UUID,
        candidate: MemoryCandidate,
    ) -> Memory:
        """Persist a candidate memory produced by an extraction flow."""
        return self.create_memory(
            tenant_id=tenant_id,
            content=candidate.content,
            memory_type=candidate.memory_type,
            importance=candidate.importance,
            confidence=candidate.confidence,
            agent_id=candidate.agent_id,
            customer_id=candidate.customer_id,
            conversation_id=candidate.conversation_id,
            task_id=candidate.task_id,
            source=candidate.source,
            metadata_json=candidate.metadata_json,
            expires_at=candidate.expires_at,
            status=MemoryStatus.ACTIVE,
        )

    def get_memory(
        self,
        tenant_id: UUID,
        memory_id: UUID,
    ) -> Memory | None:
        """Retrieve a single memory belonging strictly to the tenant."""
        return self.db.scalar(
            select(Memory).where(
                Memory.id == memory_id,
                Memory.tenant_id == tenant_id,
            )
        )

    def list_memories(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        memory_type: str | None = None,
        customer_id: UUID | None = None,
        agent_id: UUID | None = None,
        search: str | None = None,
        include_expired: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Memory]:
        """List tenant memories with scoping, status filtering, and search."""
        if limit < 1:
            raise ValueError("Limit must be greater than zero")
        if limit > 200:
            limit = 200

        stmt = select(Memory).where(Memory.tenant_id == tenant_id)

        if status is not None:
            clean_status = status.strip().lower()
            stmt = stmt.where(Memory.status == clean_status)
        else:
            # Default to active memories unless status specified
            stmt = stmt.where(Memory.status == MemoryStatus.ACTIVE)

        if not include_expired:
            now = datetime.now(timezone.utc)
            stmt = stmt.where(
                or_(
                    Memory.expires_at.is_(None),
                    Memory.expires_at > now,
                )
            )

        if memory_type is not None:
            clean_type = memory_type.strip().lower()
            stmt = stmt.where(Memory.memory_type == clean_type)

        if agent_id is not None:
            stmt = stmt.where(
                (Memory.agent_id == agent_id) | (Memory.agent_id.is_(None))
            )

        if customer_id is not None:
            # Filter where metadata_json['customer_id'] matches
            stmt = stmt.where(
                Memory.metadata_json["customer_id"].as_string() == str(customer_id)
            )

        if search is not None and search.strip():
            term = f"%{search.strip()}%"
            stmt = stmt.where(Memory.content.ilike(term))

        stmt = stmt.order_by(
            Memory.importance.desc(),
            Memory.confidence.desc(),
            Memory.updated_at.desc(),
        ).offset(offset).limit(limit)

        return list(self.db.scalars(stmt).all())

    def update_memory(
        self,
        tenant_id: UUID,
        memory_id: UUID,
        *,
        content: str | None = None,
        importance: int | None = None,
        confidence: int | None = None,
        status: str | None = None,
        expires_at: datetime | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> Memory:
        """Update an existing memory with validation and security checks."""
        memory = self.get_memory(tenant_id, memory_id)
        if memory is None:
            raise ValueError(f"Memory '{memory_id}' not found")

        if content is not None:
            clean_content = content.strip()
            if not clean_content:
                raise ValueError("Memory content cannot be empty")
            MemorySanitizer.scan_for_secrets(clean_content)
            memory.content = clean_content

        if importance is not None:
            memory.importance = max(0, min(int(importance), 100))

        if confidence is not None:
            memory.confidence = max(0, min(int(confidence), 100))

        if status is not None:
            clean_status = status.strip().lower()
            if clean_status not in MemoryStatus.ALL:
                raise ValueError(f"Invalid memory status: '{status}'")
            memory.status = clean_status

        if expires_at is not None:
            memory.expires_at = expires_at

        if metadata_json is not None:
            MemorySanitizer.scan_dict_for_secrets(metadata_json)
            updated_meta = dict(memory.metadata_json or {})
            updated_meta.update(metadata_json)
            memory.metadata_json = updated_meta

        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            agent_id=memory.agent_id,
            event_type="memory_updated",
            action="update_memory",
            description=f"Updated memory {memory.id}",
            event_metadata={
                "memory_id": str(memory.id),
                "status": memory.status,
            },
        )

        return memory

    def supersede_memory(
        self,
        tenant_id: UUID,
        old_memory_id: UUID,
        new_content: str,
        *,
        reason: str | None = None,
        importance: int | None = None,
        confidence: int | None = None,
        source: str = "correction",
    ) -> Memory:
        """
        Supersede an existing memory with an updated fact.
        Marks old memory as 'deprecated' and links both records for full provenance.
        """
        old_memory = self.get_memory(tenant_id, old_memory_id)
        if old_memory is None:
            raise ValueError(f"Memory '{old_memory_id}' not found to supersede")

        old_meta = dict(old_memory.metadata_json or {})

        # Extract scope identifiers from old memory
        old_customer_id = None
        raw_cust = old_meta.get("customer_id")
        if raw_cust:
            try:
                old_customer_id = UUID(str(raw_cust))
            except Exception:
                old_customer_id = None

        old_conv_id = None
        raw_conv = old_meta.get("conversation_id")
        if raw_conv:
            try:
                old_conv_id = UUID(str(raw_conv))
            except Exception:
                old_conv_id = None

        old_task_id = None
        raw_task = old_meta.get("task_id")
        if raw_task:
            try:
                old_task_id = UUID(str(raw_task))
            except Exception:
                old_task_id = None

        new_meta = dict(old_meta)
        new_meta["supersedes"] = str(old_memory.id)
        new_meta["superseded_reason"] = reason or "Updated fact superseded earlier record"

        # Create new memory while preserving scope and provenance
        new_memory = self.create_memory(
            tenant_id=tenant_id,
            content=new_content,
            memory_type=old_memory.memory_type,
            importance=importance if importance is not None else old_memory.importance,
            confidence=confidence if confidence is not None else old_memory.confidence,
            agent_id=old_memory.agent_id,
            user_id=old_memory.user_id,
            customer_id=old_customer_id,
            conversation_id=old_conv_id,
            task_id=old_task_id,
            source=source,
            metadata_json=new_meta,
            status=MemoryStatus.ACTIVE,
        )

        # Deprecate old memory
        old_memory.status = MemoryStatus.DEPRECATED
        old_meta = dict(old_memory.metadata_json or {})
        old_meta["superseded_by"] = str(new_memory.id)
        old_meta["superseded_at"] = datetime.now(timezone.utc).isoformat()
        old_memory.metadata_json = old_meta

        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="memory_superseded",
            action="supersede_memory",
            description=f"Memory {old_memory.id} superseded by {new_memory.id}",
            event_metadata={
                "old_memory_id": str(old_memory.id),
                "new_memory_id": str(new_memory.id),
                "reason": reason,
            },
        )

        return new_memory

    def invalidate_memory(
        self,
        tenant_id: UUID,
        memory_id: UUID,
        reason: str,
    ) -> Memory:
        """Invalidate a memory that was proven incorrect or contradictory."""
        clean_reason = (reason or "").strip()
        if not clean_reason:
            raise ValueError("Invalidation reason is required")

        memory = self.get_memory(tenant_id, memory_id)
        if memory is None:
            raise ValueError(f"Memory '{memory_id}' not found")

        memory.status = MemoryStatus.INVALIDATED
        meta = dict(memory.metadata_json or {})
        meta["invalidation_reason"] = clean_reason
        meta["invalidated_at"] = datetime.now(timezone.utc).isoformat()
        memory.metadata_json = meta

        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="memory_invalidated",
            action="invalidate_memory",
            description=f"Invalidated memory {memory.id}: {clean_reason}",
            event_metadata={
                "memory_id": str(memory.id),
                "reason": clean_reason,
            },
        )

        return memory

    def delete_memory(
        self,
        tenant_id: UUID,
        memory_id: UUID,
    ) -> None:
        """Remove a memory permanently with audit logging."""
        memory = self.get_memory(tenant_id, memory_id)
        if memory is None:
            raise ValueError(f"Memory '{memory_id}' not found")

        self.db.delete(memory)
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="memory_deleted",
            action="delete_memory",
            description=f"Deleted memory {memory_id}",
            event_metadata={"memory_id": str(memory_id)},
        )

    def _find_exact_duplicate(
        self,
        tenant_id: UUID,
        content: str,
        memory_type: str,
        customer_id: UUID | None,
        agent_id: UUID | None,
        dedup_hash: str | None = None,
    ) -> Memory | None:
        """Find an existing active memory with identical content in the same scope."""
        if dedup_hash:
            stmt = select(Memory).where(
                Memory.tenant_id == tenant_id,
                Memory.metadata_json["dedup_hash"].as_string() == dedup_hash,
                Memory.status == MemoryStatus.ACTIVE,
            )
            found = self.db.scalar(stmt)
            if found is not None:
                return found

        # Fallback query matching normalized content and explicit scope
        norm_content = " ".join(content.strip().lower().split())
        stmt = select(Memory).where(
            Memory.tenant_id == tenant_id,
            Memory.memory_type == memory_type,
            func.lower(func.trim(Memory.content)) == norm_content,
            Memory.status == MemoryStatus.ACTIVE,
        )

        if customer_id is not None:
            stmt = stmt.where(
                Memory.metadata_json["customer_id"].as_string() == str(customer_id)
            )
        else:
            # Strictly match general memories without customer_id
            stmt = stmt.where(
                or_(
                    Memory.metadata_json.is_(None),
                    ~Memory.metadata_json.has_key("customer_id"),
                    Memory.metadata_json["customer_id"].as_string().is_(None),
                    Memory.metadata_json["customer_id"].as_string() == "",
                )
            )

        if agent_id is not None:
            stmt = stmt.where(Memory.agent_id == agent_id)
        else:
            stmt = stmt.where(Memory.agent_id.is_(None))

        return self.db.scalar(stmt)
