from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Iterable


class ContextRanking:
    """Rank retrieved context items using transparent scoring rules."""

    def __init__(
        self,
        importance_weight: float = 0.45,
        confidence_weight: float = 0.35,
        recency_weight: float = 0.20,
    ) -> None:
        weights = (
            importance_weight,
            confidence_weight,
            recency_weight,
        )

        if any(weight < 0 for weight in weights):
            raise ValueError("Ranking weights cannot be negative")

        if sum(weights) <= 0:
            raise ValueError("At least one ranking weight must be positive")

        self.importance_weight = importance_weight
        self.confidence_weight = confidence_weight
        self.recency_weight = recency_weight

    def score_memory(self, memory: Any, query: str | None = None) -> float:
        importance = self._normalize(getattr(memory, "importance", 50))
        confidence = self._normalize(getattr(memory, "confidence", 50))
        recency = self._recency_score(
            getattr(memory, "updated_at", None)
        )

        if query and query.strip():
            query_score = self._query_relevance(getattr(memory, "content", ""), query)
            relevance_weight = 0.20
            total_weight = (
                self.importance_weight
                + self.confidence_weight
                + self.recency_weight
                + relevance_weight
            )
            score = (
                importance * self.importance_weight
                + confidence * self.confidence_weight
                + recency * self.recency_weight
                + query_score * relevance_weight
            ) / total_weight
        else:
            total_weight = (
                self.importance_weight
                + self.confidence_weight
                + self.recency_weight
            )

            score = (
                importance * self.importance_weight
                + confidence * self.confidence_weight
                + recency * self.recency_weight
            ) / total_weight

        return round(score, 4)

    def rank_memories(
        self,
        memories: Iterable[Any],
        limit: int | None = None,
        query: str | None = None,
    ) -> list[Any]:
        if limit is not None and limit <= 0:
            return []

        ranked = sorted(
            memories,
            key=lambda m: self.score_memory(m, query=query),
            reverse=True,
        )

        if limit is not None:
            return ranked[:limit]

        return ranked

    @staticmethod
    def _normalize(value: Any) -> float:
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return 0.0

        return max(0.0, min(numeric_value, 100.0)) / 100.0

    @staticmethod
    def _recency_score(updated_at: Any) -> float:
        if not isinstance(updated_at, datetime):
            return 0.5

        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)

        age_days = max(
            0.0,
            (datetime.now(timezone.utc) - updated_at).total_seconds()
            / 86400,
        )

        # The recency score halves approximately every 30 days.
        return 0.5 ** (age_days / 30)

    @staticmethod
    def _query_relevance(content: Any, query: str) -> float:
        """Compute lexical word overlap relevance score between memory content and query."""
        if not content or not isinstance(content, str) or not query:
            return 0.0

        content_words = {w.strip().lower() for w in re.findall(r"\w+", content) if len(w) > 2}
        query_words = {w.strip().lower() for w in re.findall(r"\w+", query) if len(w) > 2}

        if not query_words or not content_words:
            return 0.0

        matches = content_words.intersection(query_words)
        return min(1.0, len(matches) / max(1, len(query_words)))
