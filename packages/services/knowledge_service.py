from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from packages.context.ranking import ContextRanking
from packages.memory.sanitizer import MemorySanitizer
from packages.models.domain import Knowledge, Provenance, Source, SourcePolicy
from packages.services.audit_service import AuditService


class KnowledgeService:
    """
    Tenant-scoped service for managing the enterprise Knowledge Base.
    Enforces strict tenant isolation, secret scanning, lifecycle state transitions,
    provenance tracking, conflict resolution, and auditable mutations.
    """

    ALLOWED_STATUSES = {"active", "inactive", "archived", "draft"}
    DEFAULT_STATUS = "active"

    def __init__(
        self,
        db: Session,
        audit_service: AuditService | None = None,
        ranking: ContextRanking | None = None,
    ):
        self.db = db
        self.audit_service = audit_service or AuditService(db)
        self.ranking = ranking or ContextRanking()

    def _validate_source_and_policy(
        self,
        tenant_id: UUID,
        source: Source,
        target_status: str,
    ) -> None:
        """Enforce source active status and SourcePolicy learning and approval rules."""
        if source.status != "active":
            raise ValueError(
                f"Cannot create or activate knowledge from inactive source '{source.name}'"
            )

        # Lookup matching SourcePolicy (tenant-specific takes priority over global)
        stmt = (
            select(SourcePolicy)
            .where(
                or_(SourcePolicy.tenant_id == tenant_id, SourcePolicy.tenant_id.is_(None)),
                SourcePolicy.source_type == source.source_type,
            )
            .order_by(SourcePolicy.tenant_id.desc().nullslast())
        )
        policy = self.db.scalars(stmt).first()
        if policy is not None:
            if not policy.allow_learning:
                raise ValueError(
                    f"Source policy for '{source.source_type}' forbids learning from this source"
                )
            if policy.require_approval and target_status == "active":
                raise ValueError(
                    f"Source policy for '{source.source_type}' requires approval before activation"
                )

    def create_knowledge(
        self,
        tenant_id: UUID,
        title: str,
        content: str,
        knowledge_type: str = "general",
        status: str = "active",
        metadata_json: dict[str, Any] | None = None,
        provenance_id: UUID | None = None,
        source_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> Knowledge:
        """Create a new knowledge base entry with tenant isolation and secret sanitization."""
        clean_title = (title or "").strip()
        clean_content = (content or "").strip()

        if not clean_title:
            raise ValueError("Knowledge title cannot be empty")
        if not clean_content:
            raise ValueError("Knowledge content cannot be empty")

        clean_status = (status or self.DEFAULT_STATUS).strip().lower()
        if clean_status not in self.ALLOWED_STATUSES:
            raise ValueError(
                f"Invalid knowledge status '{status}'. Allowed statuses: {', '.join(sorted(self.ALLOWED_STATUSES))}"
            )

        clean_type = (knowledge_type or "general").strip().lower()

        # Security: Scan text and metadata for secrets/credentials
        MemorySanitizer.scan_for_secrets(f"{clean_title}\n{clean_content}")
        meta = dict(metadata_json or {})
        MemorySanitizer.scan_dict_for_secrets(meta)

        # Handle provenance / source attribution
        resolved_prov_id = provenance_id
        if source_id is not None:
            source = self.db.scalar(
                select(Source).where(
                    Source.id == source_id,
                    Source.tenant_id == tenant_id,
                )
            )
            if source is None:
                raise ValueError(f"Source '{source_id}' not found for tenant")

            self._validate_source_and_policy(tenant_id, source, clean_status)

            meta["source_id"] = str(source.id)
            meta["source_name"] = source.name
            meta["source_uri"] = source.uri

            if resolved_prov_id is None:
                prov = Provenance(
                    tenant_id=tenant_id,
                    source_type=source.source_type,
                    source_uri=source.uri,
                    source_name=source.name,
                    source_metadata=source.metadata_json or {},
                )
                self.db.add(prov)
                self.db.flush()
                resolved_prov_id = prov.id

        if resolved_prov_id is not None:
            prov_check = self.db.scalar(
                select(Provenance).where(
                    Provenance.id == resolved_prov_id,
                    Provenance.tenant_id == tenant_id,
                )
            )
            if prov_check is None:
                raise ValueError(f"Provenance '{resolved_prov_id}' not found for tenant")

        item = Knowledge(
            tenant_id=tenant_id,
            provenance_id=resolved_prov_id,
            title=clean_title,
            content=clean_content,
            knowledge_type=clean_type,
            status=clean_status,
            metadata_json=meta,
            version=1,
        )
        self.db.add(item)
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type="knowledge_created",
            action="create_knowledge",
            description=f"Created knowledge '{clean_title[:80]}' ({clean_type})",
            event_metadata={
                "knowledge_id": str(item.id),
                "knowledge_type": clean_type,
                "status": clean_status,
                "provenance_id": str(resolved_prov_id) if resolved_prov_id else None,
            },
        )

        return item

    def get_knowledge(self, tenant_id: UUID, knowledge_id: UUID) -> Knowledge | None:
        """Fetch a knowledge item strictly scoped to the tenant."""
        stmt = select(Knowledge).where(
            Knowledge.id == knowledge_id,
            Knowledge.tenant_id == tenant_id,
        )
        return self.db.scalar(stmt)

    def get_knowledge_guarded(
        self,
        requesting_tenant_id: UUID,
        target_tenant_id: UUID,
        knowledge_id: UUID,
    ) -> Knowledge:
        """Fetch knowledge item with cross-tenant boundary verification."""
        if requesting_tenant_id != target_tenant_id:
            raise PermissionError("Cross-tenant access prohibited: cannot access another tenant's knowledge")

        item = self.get_knowledge(target_tenant_id, knowledge_id)
        if item is None:
            raise ValueError(f"Knowledge '{knowledge_id}' not found")
        return item

    def list_knowledge(
        self,
        tenant_id: UUID,
        knowledge_type: str | None = None,
        status: str | None = None,
        customer_id: UUID | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Knowledge], int]:
        """List knowledge records for a tenant with pagination and optional filters."""
        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        base_stmt = select(Knowledge).where(Knowledge.tenant_id == tenant_id)

        if status:
            clean_status = status.strip().lower()
            base_stmt = base_stmt.where(Knowledge.status == clean_status)

        if knowledge_type:
            clean_type = knowledge_type.strip().lower()
            base_stmt = base_stmt.where(Knowledge.knowledge_type == clean_type)

        if customer_id is not None:
            str_customer_id = str(customer_id)
            try:
                base_stmt = base_stmt.where(
                    or_(
                        Knowledge.metadata_json["customer_id"].as_string() == str_customer_id,
                        Knowledge.metadata_json.is_(None),
                        ~Knowledge.metadata_json.has_key("customer_id"),
                    )
                )
            except Exception:
                pass

        if query and query.strip():
            pat = f"%{query.strip()}%"
            base_stmt = base_stmt.where(
                or_(
                    Knowledge.title.ilike(pat),
                    Knowledge.content.ilike(pat),
                )
            )

        # Count query
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_count = self.db.scalar(count_stmt) or 0

        # Paged items query
        items_stmt = (
            base_stmt.order_by(Knowledge.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        items = list(self.db.scalars(items_stmt).all())

        if customer_id is not None:
            str_customer_id = str(customer_id)
            items = [
                k for k in items
                if not (k.metadata_json or {}).get("customer_id")
                or str((k.metadata_json or {}).get("customer_id")).strip() in ("", str_customer_id)
            ]

        return items, total_count

    def update_knowledge(
        self,
        tenant_id: UUID,
        knowledge_id: UUID,
        title: str | None = None,
        content: str | None = None,
        knowledge_type: str | None = None,
        status: str | None = None,
        metadata_json: dict[str, Any] | None = None,
        provenance_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> Knowledge:
        """Update fields of an existing knowledge base entry with secret sanitization."""
        item = self.get_knowledge(tenant_id, knowledge_id)
        if item is None:
            raise ValueError(f"Knowledge '{knowledge_id}' not found")

        updates_made: list[str] = []

        if title is not None:
            clean_title = title.strip()
            if not clean_title:
                raise ValueError("Knowledge title cannot be empty")
            MemorySanitizer.scan_for_secrets(clean_title)
            item.title = clean_title
            updates_made.append("title")

        if content is not None:
            clean_content = content.strip()
            if not clean_content:
                raise ValueError("Knowledge content cannot be empty")
            MemorySanitizer.scan_for_secrets(clean_content)
            item.content = clean_content
            updates_made.append("content")

        if knowledge_type is not None:
            clean_type = knowledge_type.strip().lower()
            item.knowledge_type = clean_type
            updates_made.append("knowledge_type")

        if status is not None:
            clean_status = status.strip().lower()
            if clean_status not in self.ALLOWED_STATUSES:
                raise ValueError(
                    f"Invalid status '{status}'. Allowed: {', '.join(sorted(self.ALLOWED_STATUSES))}"
                )
            item.status = clean_status
            updates_made.append("status")

        if metadata_json is not None:
            MemorySanitizer.scan_dict_for_secrets(metadata_json)
            current_meta = dict(item.metadata_json or {})
            current_meta.update(metadata_json)
            item.metadata_json = current_meta
            updates_made.append("metadata_json")

        if provenance_id is not None:
            prov = self.db.scalar(
                select(Provenance).where(
                    Provenance.id == provenance_id,
                    Provenance.tenant_id == tenant_id,
                )
            )
            if prov is None:
                raise ValueError(f"Provenance '{provenance_id}' not found for tenant")
            item.provenance_id = provenance_id
            updates_made.append("provenance_id")

        if updates_made:
            item.version += 1
            self.db.flush()

            self.audit_service.record_event(
                tenant_id=tenant_id,
                user_id=user_id,
                event_type="knowledge_updated",
                action="update_knowledge",
                description=f"Updated knowledge '{item.title[:80]}': {', '.join(updates_made)}",
                event_metadata={
                    "knowledge_id": str(item.id),
                    "updates": updates_made,
                    "version": item.version,
                },
            )

        return item

    def activate_knowledge(
        self,
        tenant_id: UUID,
        knowledge_id: UUID,
        user_id: UUID | None = None,
    ) -> Knowledge:
        """Mark a knowledge record as active with policy verification."""
        item = self.get_knowledge(tenant_id, knowledge_id)
        if item is None:
            raise ValueError(f"Knowledge '{knowledge_id}' not found")

        meta = item.metadata_json or {}
        if isinstance(meta, dict):
            if meta.get("superseded_by"):
                raise ValueError(
                    f"Cannot activate superseded knowledge record; superseded by '{meta['superseded_by']}'"
                )

            if meta.get("source_id"):
                try:
                    sid = UUID(meta["source_id"])
                    source = self.db.scalar(
                        select(Source).where(
                            Source.id == sid,
                            Source.tenant_id == tenant_id,
                        )
                    )
                    if source is not None:
                        self._validate_source_and_policy(tenant_id, source, target_status="active")
                except (ValueError, TypeError) as exc:
                    if "approval" in str(exc).lower() or "forbids" in str(exc).lower() or "inactive" in str(exc).lower():
                        raise

        item.status = "active"
        item.version += 1
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type="knowledge_activated",
            action="activate_knowledge",
            description=f"Activated knowledge '{item.title[:80]}'",
            event_metadata={"knowledge_id": str(item.id), "version": item.version},
        )
        return item

    def deactivate_knowledge(
        self,
        tenant_id: UUID,
        knowledge_id: UUID,
        reason: str | None = None,
        user_id: UUID | None = None,
    ) -> Knowledge:
        """Mark a knowledge record as inactive with an optional deactivation reason."""
        item = self.get_knowledge(tenant_id, knowledge_id)
        if item is None:
            raise ValueError(f"Knowledge '{knowledge_id}' not found")

        item.status = "inactive"
        if reason:
            meta = dict(item.metadata_json or {})
            meta["deactivation_reason"] = reason.strip()
            item.metadata_json = meta

        item.version += 1
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type="knowledge_deactivated",
            action="deactivate_knowledge",
            description=f"Deactivated knowledge '{item.title[:80]}'",
            event_metadata={
                "knowledge_id": str(item.id),
                "reason": reason,
                "version": item.version,
            },
        )
        return item

    def delete_knowledge(
        self,
        tenant_id: UUID,
        knowledge_id: UUID,
        user_id: UUID | None = None,
    ) -> None:
        """Permanently delete a knowledge record with audit trail."""
        item = self.get_knowledge(tenant_id, knowledge_id)
        if item is None:
            raise ValueError(f"Knowledge '{knowledge_id}' not found")

        self.db.delete(item)
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type="knowledge_deleted",
            action="delete_knowledge",
            description=f"Deleted knowledge record {knowledge_id}",
            event_metadata={"knowledge_id": str(knowledge_id)},
        )

    def flag_conflict(
        self,
        tenant_id: UUID,
        knowledge_id: UUID,
        conflicting_knowledge_id: UUID,
        reason: str,
        user_id: UUID | None = None,
    ) -> tuple[Knowledge, Knowledge]:
        """
        Flag a factual contradiction between two knowledge records without silently overwriting.
        Both records remain in their current status but are annotated with conflict tracking.
        """
        MemorySanitizer.scan_for_secrets(reason)

        item_a = self.get_knowledge(tenant_id, knowledge_id)
        if item_a is None:
            raise ValueError(f"Knowledge '{knowledge_id}' not found")

        item_b = self.get_knowledge(tenant_id, conflicting_knowledge_id)
        if item_b is None:
            raise ValueError(f"Conflicting knowledge '{conflicting_knowledge_id}' not found")

        # Update item A metadata
        meta_a = dict(item_a.metadata_json or {})
        conflicts_a = set(meta_a.get("conflicts_with", []))
        conflicts_a.add(str(item_b.id))
        meta_a["conflicts_with"] = list(conflicts_a)
        meta_a["conflict_status"] = "flagged"
        meta_a["conflict_reason"] = reason.strip()
        item_a.metadata_json = meta_a
        item_a.version += 1

        # Update item B metadata
        meta_b = dict(item_b.metadata_json or {})
        conflicts_b = set(meta_b.get("conflicts_with", []))
        conflicts_b.add(str(item_a.id))
        meta_b["conflicts_with"] = list(conflicts_b)
        meta_b["conflict_status"] = "flagged"
        meta_b["conflict_reason"] = reason.strip()
        item_b.metadata_json = meta_b
        item_b.version += 1

        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type="knowledge_conflict_flagged",
            action="flag_conflict",
            description=f"Flagged contradiction between '{item_a.title[:40]}' and '{item_b.title[:40]}'",
            event_metadata={
                "knowledge_a_id": str(item_a.id),
                "knowledge_b_id": str(item_b.id),
                "reason": reason,
            },
        )

        return item_a, item_b

    def resolve_conflict(
        self,
        tenant_id: UUID,
        winner_id: UUID,
        loser_id: UUID,
        resolution_reason: str,
        user_id: UUID | None = None,
    ) -> tuple[Knowledge, Knowledge]:
        """
        Deterministically resolve a contradiction:
        - Winner is kept active and records that it supersedes loser.
        - Loser is archived/deprecated and records that it is superseded by winner.
        """
        MemorySanitizer.scan_for_secrets(resolution_reason)

        winner = self.get_knowledge(tenant_id, winner_id)
        if winner is None:
            raise ValueError(f"Winner knowledge '{winner_id}' not found")

        loser = self.get_knowledge(tenant_id, loser_id)
        if loser is None:
            raise ValueError(f"Loser knowledge '{loser_id}' not found")

        # Winner metadata
        w_meta = dict(winner.metadata_json or {})
        w_meta["supersedes"] = str(loser.id)
        w_meta["conflict_status"] = "resolved"
        w_meta["resolution_reason"] = resolution_reason.strip()
        winner.metadata_json = w_meta
        winner.version += 1

        # Loser metadata & deprecation
        l_meta = dict(loser.metadata_json or {})
        l_meta["superseded_by"] = str(winner.id)
        l_meta["conflict_status"] = "resolved"
        l_meta["resolution_reason"] = resolution_reason.strip()
        loser.metadata_json = l_meta
        loser.status = "archived"
        loser.version += 1

        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type="knowledge_conflict_resolved",
            action="resolve_conflict",
            description=f"Resolved conflict: '{winner.title[:40]}' superseded '{loser.title[:40]}'",
            event_metadata={
                "winner_id": str(winner.id),
                "loser_id": str(loser.id),
                "resolution": resolution_reason,
            },
        )

        return winner, loser

    def search_knowledge(
        self,
        tenant_id: UUID,
        query: str,
        knowledge_type: str | None = None,
        customer_id: UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Knowledge]:
        """Search active knowledge base items scored by relevance with customer privacy."""
        if not query or not query.strip():
            items, _ = self.list_knowledge(
                tenant_id=tenant_id,
                knowledge_type=knowledge_type,
                status="active",
                customer_id=customer_id,
                limit=limit,
                offset=offset,
            )
            return items

        # Fetch candidate active records
        stmt = select(Knowledge).where(
            Knowledge.tenant_id == tenant_id,
            Knowledge.status == "active",
        )
        if knowledge_type:
            stmt = stmt.where(Knowledge.knowledge_type == knowledge_type.strip().lower())

        candidates = list(self.db.scalars(stmt).all())

        # Customer isolation filter
        def _get_cust_id(k: Any) -> Any:
            meta = getattr(k, "metadata_json", None) or getattr(k, "metadata", None) or {}
            if isinstance(meta, dict):
                return meta.get("customer_id")
            return None

        if customer_id is not None:
            str_cust = str(customer_id)
            candidates = [
                k for k in candidates
                if not _get_cust_id(k)
                or str(_get_cust_id(k)).strip() in ("", str_cust)
            ]
        else:
            candidates = [
                k for k in candidates
                if not _get_cust_id(k)
                or str(_get_cust_id(k)).strip() == ""
            ]

        ranked = self.ranking.rank_knowledge(candidates, limit=limit + offset, query=query)
        return ranked[offset : offset + limit]

    @staticmethod
    def serialize_knowledge(item: Knowledge) -> dict[str, Any]:
        """Serialize Knowledge model to API response dictionary."""
        return {
            "id": str(item.id),
            "tenant_id": str(item.tenant_id),
            "provenance_id": str(item.provenance_id) if item.provenance_id else None,
            "title": item.title,
            "content": item.content,
            "knowledge_type": item.knowledge_type,
            "status": item.status,
            "metadata_json": item.metadata_json or {},
            "version": item.version,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
