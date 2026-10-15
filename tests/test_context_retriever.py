from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from packages.context.retriever import ContextRetriever


class FakeResult:
    def __init__(self, items):
        self.items = items

    def all(self):
        return self.items


class FakeSession:
    def __init__(self, items=None):
        self.items = items or []
        self.statements = []

    def scalars(self, statement):
        self.statements.append(statement)
        return FakeResult(self.items)


def make_memory(
    importance=50,
    confidence=50,
    updated_at=None,
    agent_id=None,
):
    return SimpleNamespace(
        id=uuid4(),
        importance=importance,
        confidence=confidence,
        updated_at=updated_at or datetime.now(timezone.utc),
        agent_id=agent_id,
    )


def compile_query(statement):
    return statement.compile(
        dialect=postgresql.dialect(),
    )


def test_memory_query_is_scoped_to_requested_tenant():
    tenant_id = uuid4()
    session = FakeSession()

    ContextRetriever(session).get_memories(tenant_id)

    compiled = compile_query(session.statements[0])

    assert "memories.tenant_id" in str(compiled)
    assert tenant_id in compiled.params.values()


def test_memory_query_excludes_expired_memories():
    session = FakeSession()

    ContextRetriever(session).get_memories(uuid4())

    compiled = compile_query(session.statements[0])
    sql = str(compiled)

    assert "memories.expires_at IS NULL" in sql
    assert "memories.expires_at >" in sql


def test_memory_query_only_selects_active_memories():
    session = FakeSession()

    ContextRetriever(session).get_memories(uuid4())

    compiled = compile_query(session.statements[0])

    assert "memories.status" in str(compiled)
    assert "active" in compiled.params.values()


def test_agent_query_includes_agent_specific_and_shared_memories():
    tenant_id = uuid4()
    agent_id = uuid4()
    session = FakeSession()

    ContextRetriever(session).get_memories(
        tenant_id=tenant_id,
        agent_id=agent_id,
    )

    compiled = compile_query(session.statements[0])
    sql = str(compiled)

    assert "memories.agent_id" in sql
    assert agent_id in compiled.params.values()
    assert tenant_id in compiled.params.values()


def test_memories_are_ranked_before_limit_is_applied():
    low = make_memory(importance=10, confidence=10)
    high = make_memory(importance=95, confidence=95)
    medium = make_memory(importance=50, confidence=50)

    session = FakeSession([low, high, medium])

    result = ContextRetriever(session).get_memories(
        tenant_id=uuid4(),
        limit=2,
    )

    assert len(result) == 2
    assert result[0] is high
    assert result[1] is medium


def test_non_positive_limit_returns_empty_without_query():
    session = FakeSession()

    result = ContextRetriever(session).get_memories(
        tenant_id=uuid4(),
        limit=0,
    )

    assert result == []
    assert session.statements == []
