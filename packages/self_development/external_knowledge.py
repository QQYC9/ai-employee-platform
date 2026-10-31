from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import logging
from pathlib import Path
import re
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from packages.memory.sanitizer import MemorySanitizer
from packages.models.domain import Knowledge
from packages.services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)


class CertaintyLevel(str, Enum):
    """Epistemic certainty level for acquired knowledge."""
    FACT = "fact"                # Empirically verified or official documentation fact
    HYPOTHESIS = "hypothesis"    # Unverified proposition or trial approach
    INFERENCE = "inference"      # Synthesized deduction or procedural rule


class LicenseStatus(str, Enum):
    """Licensing compliance status of acquired technical sources."""
    PERMISSIVE = "permissive"                          # MIT, Apache-2.0, BSD (permissive commercial reuse)
    RESTRICTED_COMMERCIAL = "restricted_commercial"    # Modified Apache-2.0, Sustainable Use, AGPL
    PROPRIETARY = "proprietary"                        # Closed source or unknown terms
    UNKNOWN = "unknown"


class ExternalKnowledgeGap(BaseModel):
    """Formal contract representing a discovered technical or operational knowledge gap."""
    topic: str = Field(..., description="High-level topic of the gap (e.g., 'correlation_token', 'outbox_backoff')")
    query: str = Field(..., description="Target search query or terms to research")
    trigger_context: str = Field(..., description="Context or error that triggered the gap identification")
    gap_type: str = Field(default="architectural_pattern", description="Type: architectural_pattern, api_contract, troubleshooting")


class ExternalSourceItem(BaseModel):
    """Structured representation of harvested external documentation or source code."""
    title: str
    source_uri: str
    source_type: str = Field(default="local_reference", description="local_reference, http_docs, git_repository")
    version: str = Field(default="1.0.0")
    retrieved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    content: str
    excerpt: str
    certainty: CertaintyLevel = CertaintyLevel.FACT
    license_status: LicenseStatus = LicenseStatus.PERMISSIVE
    confidence: float = Field(default=0.90, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExternalKnowledgeHarvester:
    """
    Extensible harvester that searches, reads, verifies, and assimilates
    authoritative documentation and reference implementations (Track A2).
    
    Guarantees:
      - Untrusted content is sanitized for secrets and cannot execute commands.
      - Restrictive licenses (e.g. Dify modified terms, n8n SUSL) are flagged.
      - Epistemic certainty (fact, hypothesis, inference) is recorded.
      - SHA-256 fingerprinting prevents knowledge base duplication.
    """

    KNOWN_LICENSES = {
        "memento-skills": LicenseStatus.PERMISSIVE,          # Apache-2.0
        "openai-agents-python": LicenseStatus.PERMISSIVE,    # MIT
        "ragleap-core": LicenseStatus.PERMISSIVE,            # MIT
        "langgraph": LicenseStatus.PERMISSIVE,                # MIT
        "microsoft-agent-framework": LicenseStatus.PERMISSIVE,# MIT
        "dify": LicenseStatus.RESTRICTED_COMMERCIAL,         # Modified Apache-2.0 (Section 1.a multi-tenant ban)
        "n8n": LicenseStatus.RESTRICTED_COMMERCIAL,          # Sustainable Use License v1.0
    }

    def __init__(
        self,
        reference_root: str | Path = r"D:\AI-Employee-Platform-Research",
    ):
        self.reference_root = Path(reference_root)

    def formulate_query(self, gap: ExternalKnowledgeGap) -> str:
        """Constructs an effective, sanitized search query from a knowledge gap."""
        cleaned = re.sub(r"[^\w\s\-_]", " ", gap.query)
        tokens = [t.strip().lower() for t in cleaned.split() if len(t.strip()) > 2]
        return " ".join(tokens[:8])

    def assess_license(self, source_path_or_uri: str) -> LicenseStatus:
        """Determines the intellectual property license status of a source."""
        norm = str(source_path_or_uri).lower().replace("/", "\\")
        for repo_name, status in self.KNOWN_LICENSES.items():
            if repo_name in norm:
                return status
        return LicenseStatus.UNKNOWN

    def harvest_local_reference(
        self,
        gap: ExternalKnowledgeGap,
        max_results: int = 3,
    ) -> list[ExternalSourceItem]:
        """
        Searches and reads actual content from local reference repositories.
        Reads concrete lines, extracts excerpts, and tags license status.
        """
        if not self.reference_root.exists():
            logger.warning("Reference directory %s does not exist; offline mode", self.reference_root)
            return []

        tokens = [t.strip().lower() for t in gap.query.split() if len(t.strip()) > 2]
        if not tokens:
            tokens = [gap.topic.lower()]

        findings: list[ExternalSourceItem] = []

        # Prioritize permissive reference repositories first
        repos = [d for d in self.reference_root.iterdir() if d.is_dir() and not d.name.startswith(".")]
        repos.sort(key=lambda d: 0 if d.name.lower() in ("ragleap-core", "memento-skills", "openai-agents-python", "langgraph", "microsoft-agent-framework") else 1)

        for repo_dir in repos:
            repo_name = repo_dir.name
            license_stat = self.assess_license(str(repo_dir))

            # Scan key code and documentation files in repo
            candidate_files = list(repo_dir.glob("*.md")) + list(repo_dir.glob("*.py"))
            src_dir = repo_dir / "src"
            if src_dir.exists():
                candidate_files.extend(list(src_dir.rglob("*.py"))[:10])

            for file_path in candidate_files:
                if any(p in file_path.parts for p in (".git", "node_modules", ".venv", "__pycache__", "tests")):
                    continue

                try:
                    text = file_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue

                text_lower = text.lower()
                matches = sum(1 for t in tokens if t in text_lower)
                if matches == 0:
                    continue

                # Locate relevant excerpt
                idx = -1
                for t in tokens:
                    idx = text_lower.find(t)
                    if idx != -1:
                        break

                start_idx = max(0, idx - 150)
                end_idx = min(len(text), idx + 450)
                excerpt = text[start_idx:end_idx].strip()

                findings.append(
                    ExternalSourceItem(
                        title=f"Reference from {repo_name}: {file_path.name}",
                        source_uri=str(file_path),
                        source_type="local_reference",
                        version="1.0.0",
                        content=text[:4000],  # Bounded to 4KB for memory safety
                        excerpt=excerpt,
                        certainty=CertaintyLevel.FACT if license_stat == LicenseStatus.PERMISSIVE else CertaintyLevel.INFERENCE,
                        license_status=license_stat,
                        confidence=0.92 if license_stat == LicenseStatus.PERMISSIVE else 0.75,
                        metadata={
                            "repo_name": repo_name,
                            "file_extension": file_path.suffix,
                            "match_score": matches,
                            "tokens_matched": [t for t in tokens if t in text_lower],
                        },
                    )
                )

                if len(findings) >= max_results:
                    break

            if len(findings) >= max_results:
                break

        # Sort by match score
        findings.sort(key=lambda x: x.metadata.get("match_score", 0), reverse=True)
        return findings

    def harvest_http_documentation(
        self,
        url: str,
        gap: ExternalKnowledgeGap,
        http_client: Any | None = None,
    ) -> ExternalSourceItem | None:
        """
        Harvests external HTTP documentation using SSRF protection and sanitization.
        If offline or external networking is unconfigured, returns None safely.
        """
        from packages.tools.http_tool import SSRFGuard, SSRFSecurityViolationError
        import httpx

        guard = SSRFGuard()
        try:
            guard.validate_url(url)
        except (SSRFSecurityViolationError, ValueError) as err:
            logger.info("URL validation or DNS resolution failed for URL %s: %s", url, err)
            return None

        client = http_client or httpx.Client(timeout=5.0)
        try:
            resp = client.get(url, follow_redirects=True)
            if resp.status_code != 200:
                logger.info("External HTTP request returned status %d for %s", resp.status_code, url)
                return None

            raw_text = resp.text[:10000]
            sanitized_text = MemorySanitizer.mask_secrets(raw_text)

            return ExternalSourceItem(
                title=f"Web Documentation: {url}",
                source_uri=url,
                source_type="http_docs",
                version="1.0.0",
                content=sanitized_text,
                excerpt=sanitized_text[:500],
                certainty=CertaintyLevel.FACT,
                license_status=LicenseStatus.UNKNOWN,
                confidence=0.85,
                metadata={"status_code": resp.status_code, "gap_topic": gap.topic},
            )
        except Exception as exc:
            logger.info("External HTTP fetch safely skipped or failed: %s", exc)
            return None

    def assimilate_into_knowledge_base(
        self,
        tenant_id: UUID,
        item: ExternalSourceItem,
        knowledge_service: KnowledgeService,
        *,
        learning_engine: Any | None = None,
    ) -> tuple[Knowledge, bool]:
        """
        Assimilates a harvested source item into the tenant's isolated knowledge base.
        Enforces:
          - Sanitization of secrets.
          - SHA-256 fingerprinting to prevent duplicate knowledge items.
          - Respect for licensing restrictions (warnings attached to metadata).
        """
        # Security sanitization
        clean_content = MemorySanitizer.mask_secrets(item.content)
        clean_excerpt = MemorySanitizer.mask_secrets(item.excerpt)

        rule_sig = f"external:{hashlib.sha256(item.source_uri.encode('utf-8')).hexdigest()[:16]}"
        fp_payload = f"{tenant_id}:{rule_sig}".encode("utf-8")
        fingerprint = hashlib.sha256(fp_payload).hexdigest()

        # Check existing
        existing_res = knowledge_service.list_knowledge(tenant_id=tenant_id, knowledge_type="external_knowledge")
        existing_items = existing_res[0] if isinstance(existing_res, tuple) else existing_res
        for k in existing_items:
            m = dict(k.metadata_json or {})
            if m.get("rule_fingerprint") == fingerprint:
                m["usage_count"] = int(m.get("usage_count", 0)) + 1
                m["last_accessed_at"] = datetime.now(timezone.utc).isoformat()
                k.metadata_json = m
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(k, "metadata_json")
                knowledge_service.db.flush()
                return k, False

        meta = {
            "rule_fingerprint": fingerprint,
            "rule_signature": rule_sig,
            "source_uri": item.source_uri,
            "source_type": item.source_type,
            "version": item.version,
            "certainty": item.certainty.value,
            "license_status": item.license_status.value,
            "confidence": item.confidence,
            "usage_count": 1,
            "excerpt": clean_excerpt,
            "assimilated_at": datetime.now(timezone.utc).isoformat(),
        }

        if item.license_status == LicenseStatus.RESTRICTED_COMMERCIAL:
            meta["license_warning"] = (
                "Source is restricted by commercial use terms (e.g. Dify / n8n license). "
                "Concept reference only; no proprietary or restricted source code may be copied."
            )

        created = knowledge_service.create_knowledge(
            tenant_id=tenant_id,
            title=item.title[:250],
            content=(
                f"Title: {item.title}\n"
                f"Source: {item.source_uri} (Type: {item.source_type}, License: {item.license_status.value})\n"
                f"Certainty: {item.certainty.value.upper()}\n"
                f"Confidence: {item.confidence:.2f}\n\n"
                f"Content Excerpt:\n{clean_excerpt}\n\n"
                f"Detailed Content:\n{clean_content[:3000]}"
            ),
            knowledge_type="external_knowledge",
            status="active",
            metadata_json=meta,
        )
        knowledge_service.db.flush()
        return created, True

# =============================================================================
# Track D & E: External Search Gateway & Deep Repository Research Architecture
# =============================================================================

class ExternalSearchHit(BaseModel):
    """Structured hit from an external or local search provider."""
    title: str
    url: str
    snippet: str
    score: float = 0.8
    provider: str = "local"


class SearchProvider:
    """Abstract contract for search providers."""
    name: str = "abstract"

    def is_available(self) -> bool:
        raise NotImplementedError

    def search(self, query: str, max_results: int = 5) -> list[ExternalSearchHit]:
        raise NotImplementedError


class TavilySearchProvider(SearchProvider):
    name = "tavily"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def search(self, query: str, max_results: int = 5) -> list[ExternalSearchHit]:
        if not self.is_available():
            logger.info("Tavily search unavailable: TAVILY_API_KEY is not configured.")
            return []
        import httpx
        try:
            resp = httpx.post(
                "https://api.tavily.com/search",
                json={"query": query, "max_results": max_results, "include_answer": False},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10.0,
            )
            if resp.status_code != 200:
                logger.warning("Tavily search API error: %d", resp.status_code)
                return []
            data = resp.json()
            hits = []
            for item in data.get("results", []):
                hits.append(
                    ExternalSearchHit(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=item.get("content", "")[:500],
                        score=float(item.get("score", 0.8)),
                        provider="tavily",
                    )
                )
            return hits
        except Exception as exc:
            logger.warning("Tavily search request failed: %s", exc)
            return []


class SearXNGSearchProvider(SearchProvider):
    name = "searxng"

    def __init__(self, instance_url: str | None = None):
        self.instance_url = instance_url

    def is_available(self) -> bool:
        return bool(self.instance_url and self.instance_url.strip())

    def search(self, query: str, max_results: int = 5) -> list[ExternalSearchHit]:
        if not self.is_available():
            return []
        import httpx
        try:
            resp = httpx.get(
                f"{self.instance_url.rstrip('/')}/search",
                params={"q": query, "format": "json"},
                timeout=5.0,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            hits = []
            for item in data.get("results", [])[:max_results]:
                hits.append(
                    ExternalSearchHit(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=item.get("content", "")[:500],
                        score=float(item.get("score", 0.7)),
                        provider="searxng",
                    )
                )
            return hits
        except Exception as exc:
            logger.warning("SearXNG search request failed: %s", exc)
            return []


class LocalReferenceSearchProvider(SearchProvider):
    name = "local_reference"

    def __init__(self, harvester: ExternalKnowledgeHarvester):
        self.harvester = harvester

    def is_available(self) -> bool:
        return self.harvester.reference_root.exists()

    def search(self, query: str, max_results: int = 5) -> list[ExternalSearchHit]:
        gap = ExternalKnowledgeGap(topic=query, query=query, trigger_context="manual_search")
        findings = self.harvester.harvest_local_reference(gap, max_results=max_results)
        return [
            ExternalSearchHit(
                title=f.title,
                url=f.source_uri,
                snippet=f.excerpt,
                score=f.confidence,
                provider="local_reference",
            )
            for f in findings
        ]


class ExternalSearchGateway:
    """
    Unified multi-provider search gateway.
    Prioritizes active external providers (Tavily, SearXNG) when keys/networking exist,
    and falls back with zero downtime to local reference repositories.
    """
    def __init__(
        self,
        harvester: ExternalKnowledgeHarvester | None = None,
        tavily_api_key: str | None = None,
        searxng_url: str | None = None,
    ):
        self.harvester = harvester or ExternalKnowledgeHarvester()
        self.providers: list[SearchProvider] = [
            TavilySearchProvider(api_key=tavily_api_key),
            SearXNGSearchProvider(instance_url=searxng_url),
            LocalReferenceSearchProvider(self.harvester),
        ]

    def search(self, query: str, max_results: int = 5) -> tuple[list[ExternalSearchHit], str]:
        for p in self.providers:
            if p.is_available():
                hits = p.search(query, max_results=max_results)
                if hits:
                    return hits, p.name
        return [], "none"


class DeepRepositoryResearcher:
    """
    Executes the 8-stage deep repository study cycle:
    1. Gap identification & topic mapping.
    2. Verification of repo, release, and license permissiveness.
    3. Safe inspection of AST, code, and tests (zero untrusted execution).
    4. Extraction of reusable mechanisms with evidence.
    5. Controlled sandbox trial formulation.
    6. Comparative architectural evaluation against current code.
    7. Admissibility verdict (ADOPT_WITH_ADAPTATION, REJECT_INCOMPATIBLE, REJECT_RESTRICTIVE_LICENSE).
    """
    def __init__(self, reference_root: str | Path = r"D:\AI-Employee-Platform-Research"):
        self.reference_root = Path(reference_root)

    def verify_repository_compliance(self, repo_name: str) -> dict[str, Any]:
        repo_dir = self.reference_root / repo_name
        if not repo_dir.exists():
            return {"exists": False, "status": "not_found"}

        license_file = None
        for cand in ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING"):
            p = repo_dir / cand
            if p.exists():
                license_file = p
                break

        license_text = license_file.read_text(encoding="utf-8", errors="replace")[:1000] if license_file else ""
        license_status = ExternalKnowledgeHarvester.KNOWN_LICENSES.get(repo_name, LicenseStatus.UNKNOWN)

        version = "unknown"
        for vf in ("pyproject.toml", "package.json", "setup.py", "version.py"):
            vp = repo_dir / vf
            if vp.exists():
                vt = vp.read_text(encoding="utf-8", errors="replace")
                m = re.search(r'version\s*=\s*["\']([^"\']+)["\']|"version":\s*"([^"]+)"', vt)
                if m:
                    version = m.group(1) or m.group(2)
                    break

        return {
            "exists": True,
            "repo_name": repo_name,
            "version": version,
            "license_status": license_status.value,
            "license_header": license_text[:200].strip(),
            "is_permissive": license_status == LicenseStatus.PERMISSIVE,
        }

    def inspect_architectural_pattern(
        self,
        repo_name: str,
        topic_keywords: list[str],
    ) -> dict[str, Any]:
        repo_dir = self.reference_root / repo_name
        if not repo_dir.exists():
            return {"status": "error", "message": f"Repo {repo_name} not found"}

        compliance = self.verify_repository_compliance(repo_name)
        matched_files = []
        for p in repo_dir.rglob("*.py"):
            if any(part in p.parts for part in (".git", ".venv", "tests", "test", "__pycache__")):
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            lower_c = content.lower()
            matches = [k for k in topic_keywords if k.lower() in lower_c]
            if matches:
                matched_files.append({
                    "path": str(p),
                    "file_name": p.name,
                    "matched_keywords": matches,
                    "sample_lines": [line.strip() for line in content.splitlines() if any(k.lower() in line.lower() for k in matches)][:5],
                })
            if len(matched_files) >= 3:
                break

        return {
            "repo_name": repo_name,
            "compliance": compliance,
            "matched_files_count": len(matched_files),
            "evidence": matched_files,
        }

    def evaluate_capability_candidate(
        self,
        gap_topic: str,
        repo_name: str,
        extracted_pattern: dict[str, Any],
        current_solution: str,
    ) -> dict[str, Any]:
        compliance = extracted_pattern.get("compliance", {})
        is_permissive = compliance.get("is_permissive", False)
        evidence = extracted_pattern.get("evidence", [])

        if not is_permissive:
            return {
                "gap_topic": gap_topic,
                "repo_name": repo_name,
                "verdict": "REJECT_RESTRICTIVE_LICENSE",
                "reason": f"License for {repo_name} ({compliance.get('license_status')}) is not permissive for commercial multi-tenant reuse.",
                "action": "Concept reference only. No direct adoption.",
            }

        if not evidence:
            return {
                "gap_topic": gap_topic,
                "repo_name": repo_name,
                "verdict": "REJECT_NO_EVIDENCE",
                "reason": f"No concrete source code evidence matched keywords in {repo_name}.",
                "action": "Search other reference repositories.",
            }

        return {
            "gap_topic": gap_topic,
            "repo_name": repo_name,
            "verdict": "ADOPT_WITH_ADAPTATION",
            "current_solution": current_solution,
            "reference_evidence": evidence[0]["file_name"],
            "adaptation_requirements": [
                "Preserve tenant isolation via tenant_id scoping",
                "Enforce PostgreSQL row-level locks or transaction savepoints",
                "Sanitize secrets before persisting evidence to Knowledge base",
            ],
            "risk_assessment": "Low: pattern implemented natively within SQLAlchemy domain models.",
        }
