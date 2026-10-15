from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from packages.context.ranking import ContextRanking


def make_memory(
    importance=50,
    confidence=50,
    updated_at=None,
):
    return SimpleNamespace(
        importance=importance,
        confidence=confidence,
        updated_at=updated_at or datetime.now(timezone.utc),
    )


def test_higher_importance_and_confidence_rank_higher():
    ranking = ContextRanking()

    important = make_memory(importance=90, confidence=90)
    ordinary = make_memory(importance=40, confidence=40)

    assert ranking.score_memory(important) > ranking.score_memory(ordinary)


def test_recent_memory_scores_higher_than_old_memory():
    ranking = ContextRanking()

    recent = make_memory(
        updated_at=datetime.now(timezone.utc),
    )
    old = make_memory(
        updated_at=datetime.now(timezone.utc) - timedelta(days=90),
    )

    assert ranking.score_memory(recent) > ranking.score_memory(old)


def test_rank_memories_returns_descending_scores():
    ranking = ContextRanking()

    low = make_memory(importance=10, confidence=10)
    high = make_memory(importance=90, confidence=90)
    medium = make_memory(importance=50, confidence=50)

    result = ranking.rank_memories([low, high, medium])

    assert result == [high, medium, low]


def test_rank_memories_respects_limit():
    ranking = ContextRanking()

    memories = [
        make_memory(importance=20),
        make_memory(importance=80),
        make_memory(importance=50),
    ]

    result = ranking.rank_memories(memories, limit=2)

    assert len(result) == 2
    assert result[0].importance == 80


def test_non_positive_limit_returns_empty_list():
    ranking = ContextRanking()

    assert ranking.rank_memories([make_memory()], limit=0) == []
    assert ranking.rank_memories([make_memory()], limit=-1) == []


def test_invalid_numeric_values_are_handled():
    ranking = ContextRanking()

    memory = make_memory(
        importance="invalid",
        confidence=None,
    )

    assert ranking.score_memory(memory) >= 0


def test_negative_weights_are_rejected():
    with pytest.raises(ValueError):
        ContextRanking(importance_weight=-1)


def test_all_zero_weights_are_rejected():
    with pytest.raises(ValueError):
        ContextRanking(
            importance_weight=0,
            confidence_weight=0,
            recency_weight=0,
        )

def test_rank_memories_preserves_original_items():
    ranking = ContextRanking()
    memory = make_memory(importance=80, confidence=70)

    result = ranking.rank_memories([memory])

    assert len(result) == 1
    assert result[0] is memory
