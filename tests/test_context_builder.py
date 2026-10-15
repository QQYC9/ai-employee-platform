from types import SimpleNamespace
from uuid import uuid4

import pytest

from packages.context.builder import ContextBuilder
from packages.context.models import TaskContext


class FakeRetriever:
    def __init__(self, business=None, memories=None, knowledge=None):
        self.business = business
        self.memories = memories or []
        self.knowledge = knowledge or []
        self.calls = []

    def get_business_brain(self, tenant_id):
        self.calls.append(("business", tenant_id))
        return self.business

    def get_memories(self, tenant_id, agent_id=None, limit=20):
        self.calls.append(("memories", tenant_id, agent_id, limit))
        return self.memories[:limit]

    def get_knowledge(self, tenant_id, query=None, limit=20):
        self.calls.append(("knowledge", tenant_id, query, limit))
        return self.knowledge[:limit]


def make_task(agent_id=None):
    return TaskContext(
        task_id=uuid4(),
        agent_id=agent_id,
        objective="Prepare a marketing campaign",
        title="Marketing campaign",
        priority="high",
        status="pending",
    )


def test_builder_returns_task_and_tenant_context():
    tenant_id = uuid4()
    task = make_task()
    builder = ContextBuilder(FakeRetriever())

    context = builder.build(tenant_id=tenant_id, task=task)

    assert context.tenant_id == tenant_id
    assert context.task is task


def test_builder_converts_memories_and_knowledge_to_dicts():
    tenant_id = uuid4()
    memory = SimpleNamespace(
        id=uuid4(),
        agent_id=None,
        user_id=None,
        memory_type="preference",
        content="Use Arabic in marketing content",
        importance=80,
        confidence=90,
        metadata_json={},
        expires_at=None,
    )
    knowledge = SimpleNamespace(
        id=uuid4(),
        title="Brand guide",
        content="Brand guidelines",
        knowledge_type="document",
        metadata_json={},
        version=1,
    )
    retriever = FakeRetriever(memories=[memory], knowledge=[knowledge])

    context = ContextBuilder(retriever).build(
        tenant_id=tenant_id,
        task=make_task(),
    )

    assert context.memories[0]["content"] == memory.content
    assert context.knowledge[0]["title"] == knowledge.title
    assert context.metadata["memory_count"] == 1
    assert context.metadata["knowledge_count"] == 1


def test_builder_serializes_business_brain():
    tenant_id = uuid4()
    business = SimpleNamespace(
        identity={"name": "Test Business"},
        products={},
        services={},
        pricing={},
        brand={},
        customers={},
        competitors={},
        marketing={},
        sales={},
        operations={},
        policies={},
        people={},
        goals={},
        strategy={},
        preferences={},
        performance={},
        lessons={},
        version=2,
    )

    context = ContextBuilder(
        FakeRetriever(business=business)
    ).build(tenant_id=tenant_id, task=make_task())

    assert context.business["identity"]["name"] == "Test Business"
    assert context.business["version"] == 2


def test_builder_handles_missing_business_brain():
    context = ContextBuilder(
        FakeRetriever()
    ).build(tenant_id=uuid4(), task=make_task())

    assert context.business == {}


def test_builder_passes_tenant_and_agent_to_retriever():
    tenant_id = uuid4()
    agent_id = uuid4()
    retriever = FakeRetriever()

    ContextBuilder(retriever).build(
        tenant_id=tenant_id,
        task=make_task(agent_id=agent_id),
    )

    assert retriever.calls[0] == ("business", tenant_id)
    assert retriever.calls[1] == ("memories", tenant_id, agent_id, 20)
    assert retriever.calls[2][0] == "knowledge"
    assert retriever.calls[2][1] == tenant_id


@pytest.mark.parametrize(
    ("memory_limit", "knowledge_limit"),
    [(-1, 20), (20, -1)],
)
def test_builder_rejects_negative_limits(memory_limit, knowledge_limit):
    builder = ContextBuilder(FakeRetriever())

    with pytest.raises(ValueError):
        builder.build(
            tenant_id=uuid4(),
            task=make_task(),
            memory_limit=memory_limit,
            knowledge_limit=knowledge_limit,
        )
