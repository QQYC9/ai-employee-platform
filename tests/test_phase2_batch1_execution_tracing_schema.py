from __future__ import annotations

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.core.config import settings
from packages.core.database import SessionLocal, engine
from packages.models.domain import (
    Agent,
    Approval,
    Conversation,
    ExecutionStep,
    ExecutionTrace,
    Message,
    OutboxEvent,
    Task,
    User,
)
from packages.models.tenant import Tenant


def get_alembic_config() -> Config:
    from packages.core.safety_guard import verify_test_database_isolation
    verify_test_database_isolation(engine)
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("script_location", "infrastructure/migrations")
    alembic_cfg.set_main_option("sqlalchemy.url", settings.effective_test_database_url)
    return alembic_cfg


@pytest.fixture(scope="module", autouse=True)
def run_migrations():
    """Ensure migrations are applied before running tests."""
    alembic_cfg = get_alembic_config()
    command.upgrade(alembic_cfg, "head")
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_tenant_helper(db: Session, name: str = "Test Tenant") -> Tenant:
    tenant = Tenant(
        id=uuid4(),
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}",
        status="active",
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@pytest.fixture
def tenant_alpha(db: Session) -> Tenant:
    return create_tenant_helper(db, "Tenant Alpha Schema Test")


@pytest.fixture
def tenant_beta(db: Session) -> Tenant:
    return create_tenant_helper(db, "Tenant Beta Schema Test")


def test_schema_tables_and_indexes_exist(db: Session):
    """Verify that execution_traces and execution_steps tables, unique constraints, and indexes exist."""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "execution_traces" in tables, "execution_traces table must exist in schema"
    assert "execution_steps" in tables, "execution_steps table must exist in schema"

    # Verify execution_traces indexes
    trace_indexes = {idx["name"] for idx in inspector.get_indexes("execution_traces")}
    assert "ix_execution_traces_tenant_id" in trace_indexes
    assert "ix_execution_traces_trace_id" in trace_indexes
    assert "ix_execution_traces_status" in trace_indexes
    assert "ix_execution_traces_tenant_status" in trace_indexes
    assert "ix_execution_traces_tenant_created" in trace_indexes

    # Verify execution_steps indexes
    step_indexes = {idx["name"] for idx in inspector.get_indexes("execution_steps")}
    assert "ix_execution_steps_tenant_id" in step_indexes
    assert "ix_execution_steps_trace_id" in step_indexes
    assert "ix_execution_steps_status" in step_indexes
    assert "ix_execution_steps_step_type" in step_indexes
    assert "ix_execution_steps_tenant_trace_order" in step_indexes

    # Verify unique constraints on referenced tables
    agent_uqs = {c["name"] for c in inspector.get_unique_constraints("agents")}
    assert "uq_agents_tenant_id" in agent_uqs

    task_uqs = {c["name"] for c in inspector.get_unique_constraints("tasks")}
    assert "uq_tasks_tenant_id" in task_uqs

    conv_uqs = {c["name"] for c in inspector.get_unique_constraints("conversations")}
    assert "uq_conversations_tenant_id" in conv_uqs

    msg_uqs = {c["name"] for c in inspector.get_unique_constraints("messages")}
    assert "uq_messages_tenant_id" in msg_uqs

    app_uqs = {c["name"] for c in inspector.get_unique_constraints("approvals")}
    assert "uq_approvals_tenant_id" in app_uqs

    outbox_uqs = {c["name"] for c in inspector.get_unique_constraints("outbox_events")}
    assert "uq_outbox_events_tenant_id" in outbox_uqs


def test_create_execution_trace_and_step_happy_path(db: Session, tenant_alpha: Tenant):
    """Verify happy path creation with all relationships."""
    agent = Agent(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        name="Agent Alpha",
        agent_type="main",
    )
    conv = Conversation(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        subject="Happy Path Conv",
    )
    db.add_all([agent, conv])
    db.flush()

    msg_in = Message(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        conversation_id=conv.id,
        sender_type="customer",
        content="Inquiry",
    )
    msg_reply = Message(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        conversation_id=conv.id,
        sender_type="agent",
        content="Response",
    )
    task = Task(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        title="Order task",
        objective="Process order",
    )
    db.add_all([msg_in, msg_reply, task])
    db.commit()

    trace = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=uuid4(),
        trigger_type="inbound_message",
        conversation_id=conv.id,
        inbound_message_id=msg_in.id,
        reply_message_id=msg_reply.id,
        task_id=task.id,
        agent_id=agent.id,
        status="running",
        metadata_json={"client": "test_client"},
    )
    db.add(trace)
    db.commit()

    approval = Approval(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        task_id=task.id,
        requested_for="commercial_action",
        action="discount_order",
        description="Approval needed",
    )
    outbox = OutboxEvent(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        conversation_id=conv.id,
        message_id=msg_reply.id,
        idempotency_key=f"outbox:{uuid4().hex}",
        event_type="send_channel_message",
    )
    db.add_all([approval, outbox])
    db.commit()

    step = ExecutionStep(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=trace.id,
        task_id=task.id,
        approval_id=approval.id,
        outbox_event_id=outbox.id,
        step_order=1,
        step_type="tool_call",
        step_name="vat_calculator",
        status="completed",
        duration_ms=45,
        attempt_count=1,
        attempts_history=[],
        input_summary={"amount": 100},
        output_summary={"vat": 15},
    )
    db.add(step)
    db.commit()

    # Query back and verify
    fetched_trace = db.scalar(select(ExecutionTrace).where(ExecutionTrace.id == trace.id))
    assert fetched_trace is not None
    assert fetched_trace.tenant_id == tenant_alpha.id
    assert fetched_trace.conversation_id == conv.id
    assert fetched_trace.agent_id == agent.id

    fetched_step = db.scalar(select(ExecutionStep).where(ExecutionStep.id == step.id))
    assert fetched_step is not None
    assert fetched_step.task_id == task.id
    assert fetched_step.approval_id == approval.id
    assert fetched_step.outbox_event_id == outbox.id


def test_cross_tenant_trace_step_rejection(db: Session, tenant_alpha: Tenant, tenant_beta: Tenant):
    """Verify fk_steps_trace_tenant rejects linking a step of Tenant Beta to a trace of Tenant Alpha."""
    trace_alpha = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=uuid4(),
        trigger_type="inbound_message",
    )
    db.add(trace_alpha)
    db.commit()

    step_cross = ExecutionStep(
        id=uuid4(),
        tenant_id=tenant_beta.id,  # Mismatched!
        trace_id=trace_alpha.id,
        step_order=1,
        step_type="tool_call",
        step_name="cross_step",
    )
    db.add(step_cross)

    with pytest.raises(IntegrityError) as exc_info:
        db.commit()
    db.rollback()
    assert "fk_steps_trace_tenant" in str(exc_info.value).lower() or "foreignkeyviolation" in str(exc_info.value).lower()


def test_cross_tenant_parent_step_rejection(db: Session, tenant_alpha: Tenant, tenant_beta: Tenant):
    """Verify fk_steps_parent_tenant rejects linking a child step of Tenant Beta to parent of Tenant Alpha."""
    trace_alpha = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=uuid4(),
        trigger_type="inbound_message",
    )
    db.add(trace_alpha)
    db.commit()

    parent_alpha = ExecutionStep(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=trace_alpha.id,
        step_order=1,
        step_type="llm_reasoning",
        step_name="parent_planner",
    )
    db.add(parent_alpha)

    trace_beta = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_beta.id,
        trace_id=uuid4(),
        trigger_type="inbound_message",
    )
    db.add(trace_beta)
    db.commit()

    child_beta = ExecutionStep(
        id=uuid4(),
        tenant_id=tenant_beta.id,
        trace_id=trace_beta.id,
        parent_step_id=parent_alpha.id,  # Cross-tenant parent!
        step_order=2,
        step_type="tool_call",
        step_name="child_tool",
    )
    db.add(child_beta)

    with pytest.raises(IntegrityError) as exc_info:
        db.commit()
    db.rollback()
    assert "fk_steps_parent_tenant" in str(exc_info.value).lower() or "foreignkeyviolation" in str(exc_info.value).lower()


def test_cross_tenant_trace_conversation_rejection(db: Session, tenant_alpha: Tenant, tenant_beta: Tenant):
    """Verify fk_traces_conversation_tenant rejects linking conversation of Tenant Beta to trace of Tenant Alpha."""
    conv_beta = Conversation(
        id=uuid4(),
        tenant_id=tenant_beta.id,
        subject="Beta Conv",
    )
    db.add(conv_beta)
    db.commit()

    trace_alpha = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_alpha.id,  # Tenant Alpha!
        trace_id=uuid4(),
        conversation_id=conv_beta.id,  # Conv belongs to Beta!
        trigger_type="inbound_message",
    )
    db.add(trace_alpha)

    with pytest.raises(IntegrityError) as exc_info:
        db.commit()
    db.rollback()
    assert "fk_traces_conversation_tenant" in str(exc_info.value).lower() or "foreignkeyviolation" in str(exc_info.value).lower()


def test_cross_tenant_trace_message_rejection(db: Session, tenant_alpha: Tenant, tenant_beta: Tenant):
    """Verify fk_traces_inbound_msg_tenant rejects message of Tenant Beta linked to trace of Tenant Alpha."""
    conv_beta = Conversation(
        id=uuid4(),
        tenant_id=tenant_beta.id,
        subject="Beta Conv",
    )
    db.add(conv_beta)
    db.flush()

    msg_beta = Message(
        id=uuid4(),
        tenant_id=tenant_beta.id,
        conversation_id=conv_beta.id,
        sender_type="customer",
        content="Hello from beta",
    )
    db.add(msg_beta)
    db.commit()

    trace_alpha = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=uuid4(),
        inbound_message_id=msg_beta.id,  # Belongs to beta!
        trigger_type="inbound_message",
    )
    db.add(trace_alpha)

    with pytest.raises(IntegrityError) as exc_info:
        db.commit()
    db.rollback()
    assert "fk_traces_inbound_msg_tenant" in str(exc_info.value).lower() or "foreignkeyviolation" in str(exc_info.value).lower()


def test_cross_tenant_trace_task_rejection(db: Session, tenant_alpha: Tenant, tenant_beta: Tenant):
    """Verify fk_traces_task_tenant rejects task of Tenant Beta linked to trace of Tenant Alpha."""
    task_beta = Task(
        id=uuid4(),
        tenant_id=tenant_beta.id,
        title="Beta Task",
        objective="Run beta task",
    )
    db.add(task_beta)
    db.commit()

    trace_alpha = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=uuid4(),
        task_id=task_beta.id,  # Belongs to beta!
        trigger_type="manual_api",
    )
    db.add(trace_alpha)

    with pytest.raises(IntegrityError) as exc_info:
        db.commit()
    db.rollback()
    assert "fk_traces_task_tenant" in str(exc_info.value).lower() or "foreignkeyviolation" in str(exc_info.value).lower()


def test_cross_tenant_trace_agent_rejection(db: Session, tenant_alpha: Tenant, tenant_beta: Tenant):
    """Verify fk_traces_agent_tenant rejects agent of Tenant Beta linked to trace of Tenant Alpha."""
    agent_beta = Agent(
        id=uuid4(),
        tenant_id=tenant_beta.id,
        name="Beta Agent",
    )
    db.add(agent_beta)
    db.commit()

    trace_alpha = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=uuid4(),
        agent_id=agent_beta.id,  # Belongs to beta!
        trigger_type="inbound_message",
    )
    db.add(trace_alpha)

    with pytest.raises(IntegrityError) as exc_info:
        db.commit()
    db.rollback()
    assert "fk_traces_agent_tenant" in str(exc_info.value).lower() or "foreignkeyviolation" in str(exc_info.value).lower()


def test_cross_tenant_step_task_and_approval_rejection(db: Session, tenant_alpha: Tenant, tenant_beta: Tenant):
    """Verify fk_steps_task_tenant and fk_steps_approval_tenant reject cross-tenant assignments."""
    trace_alpha = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=uuid4(),
        trigger_type="inbound_message",
    )
    db.add(trace_alpha)

    task_beta = Task(
        id=uuid4(),
        tenant_id=tenant_beta.id,
        title="Beta Task",
        objective="Beta objective",
    )
    db.add(task_beta)
    db.commit()

    # Step in Alpha trying to reference Task in Beta
    step_bad_task = ExecutionStep(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=trace_alpha.id,
        task_id=task_beta.id,
        step_order=1,
        step_type="tool_call",
        step_name="tool_1",
    )
    db.add(step_bad_task)

    with pytest.raises(IntegrityError) as exc_info:
        db.commit()
    db.rollback()
    assert "fk_steps_task_tenant" in str(exc_info.value).lower() or "foreignkeyviolation" in str(exc_info.value).lower()

    # Now test cross-tenant approval
    app_beta = Approval(
        id=uuid4(),
        tenant_id=tenant_beta.id,
        requested_for="commercial_action",
        action="discount",
        description="Beta approval",
    )
    db.add(app_beta)
    db.commit()

    step_bad_approval = ExecutionStep(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=trace_alpha.id,
        approval_id=app_beta.id,
        step_order=1,
        step_type="approval_request",
        step_name="discount_step",
    )
    db.add(step_bad_approval)

    with pytest.raises(IntegrityError) as exc_info:
        db.commit()
    db.rollback()
    assert "fk_steps_approval_tenant" in str(exc_info.value).lower() or "foreignkeyviolation" in str(exc_info.value).lower()


def test_cross_tenant_step_outbox_event_rejection(db: Session, tenant_alpha: Tenant, tenant_beta: Tenant):
    """Verify fk_steps_outbox_event_tenant rejects outbox event of Tenant Beta linked to step of Tenant Alpha."""
    conv_beta = Conversation(
        id=uuid4(),
        tenant_id=tenant_beta.id,
        subject="Beta Conv Outbox",
    )
    db.add(conv_beta)
    db.flush()

    msg_beta = Message(
        id=uuid4(),
        tenant_id=tenant_beta.id,
        conversation_id=conv_beta.id,
        sender_type="customer",
        content="Beta msg",
    )
    db.add(msg_beta)
    db.flush()

    outbox_beta = OutboxEvent(
        id=uuid4(),
        tenant_id=tenant_beta.id,
        conversation_id=conv_beta.id,
        message_id=msg_beta.id,
        idempotency_key=f"outbox:{uuid4().hex}",
    )
    db.add(outbox_beta)

    trace_alpha = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=uuid4(),
        trigger_type="inbound_message",
    )
    db.add(trace_alpha)
    db.commit()

    step_cross_outbox = ExecutionStep(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=trace_alpha.id,
        outbox_event_id=outbox_beta.id,  # Belongs to beta!
        step_order=1,
        step_type="channel_delivery",
        step_name="whatsapp_delivery",
    )
    db.add(step_cross_outbox)

    with pytest.raises(IntegrityError) as exc_info:
        db.commit()
    db.rollback()
    assert "fk_steps_outbox_event_tenant" in str(exc_info.value).lower() or "foreignkeyviolation" in str(exc_info.value).lower()


def test_on_delete_optional_entities_sets_null_leaves_tenant_intact(db: Session, tenant_alpha: Tenant):
    """
    Verify that deleting Conversation, Message, Task, Approval, Agent, OutboxEvent
    each sets ONLY its respective column to NULL, and leaves tenant_id non-null and intact!
    """
    agent = Agent(id=uuid4(), tenant_id=tenant_alpha.id, name="Test Agent")
    conv = Conversation(id=uuid4(), tenant_id=tenant_alpha.id, subject="Test Conv")
    db.add_all([agent, conv])
    db.flush()

    msg_in = Message(id=uuid4(), tenant_id=tenant_alpha.id, conversation_id=conv.id, sender_type="customer", content="In")
    msg_rep = Message(id=uuid4(), tenant_id=tenant_alpha.id, conversation_id=conv.id, sender_type="agent", content="Rep")
    task = Task(id=uuid4(), tenant_id=tenant_alpha.id, title="Test Task", objective="Objective")
    db.add_all([msg_in, msg_rep, task])
def test_on_delete_conversation_sets_null_leaves_tenant_intact(db: Session, tenant_alpha: Tenant):
    """Verify deleting conversation sets conversation_id = NULL on trace without affecting tenant_id."""
    conv = Conversation(id=uuid4(), tenant_id=tenant_alpha.id, subject="Test Conv To Delete")
    db.add(conv)
    db.commit()

    trace = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=uuid4(),
        conversation_id=conv.id,
        trigger_type="inbound_message",
    )
    db.add(trace)
    db.commit()

    db.delete(conv)
    db.commit()
    db.refresh(trace)
    assert trace.conversation_id is None, "conversation_id must be SET NULL"
    assert trace.tenant_id == tenant_alpha.id, "tenant_id must remain untouched"


def test_on_delete_message_sets_null_leaves_tenant_intact(db: Session, tenant_alpha: Tenant):
    """Verify deleting message sets inbound_message_id and reply_message_id = NULL on trace."""
    conv = Conversation(id=uuid4(), tenant_id=tenant_alpha.id, subject="Msg Conv")
    db.add(conv)
    db.flush()

    msg_in = Message(id=uuid4(), tenant_id=tenant_alpha.id, conversation_id=conv.id, sender_type="customer", content="In")
    msg_rep = Message(id=uuid4(), tenant_id=tenant_alpha.id, conversation_id=conv.id, sender_type="agent", content="Rep")
    db.add_all([msg_in, msg_rep])
    db.commit()

    trace = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=uuid4(),
        inbound_message_id=msg_in.id,
        reply_message_id=msg_rep.id,
        trigger_type="inbound_message",
    )
    db.add(trace)
    db.commit()

    db.delete(msg_in)
    db.commit()
    db.refresh(trace)
    assert trace.inbound_message_id is None, "inbound_message_id must be SET NULL"
    assert trace.reply_message_id == msg_rep.id
    assert trace.tenant_id == tenant_alpha.id

    db.delete(msg_rep)
    db.commit()
    db.refresh(trace)
    assert trace.reply_message_id is None, "reply_message_id must be SET NULL"
    assert trace.tenant_id == tenant_alpha.id


def test_on_delete_agent_sets_null_leaves_tenant_intact(db: Session, tenant_alpha: Tenant):
    """Verify deleting agent sets agent_id = NULL on trace without affecting tenant_id."""
    agent = Agent(id=uuid4(), tenant_id=tenant_alpha.id, name="Agent To Delete")
    db.add(agent)
    db.commit()

    trace = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=uuid4(),
        agent_id=agent.id,
        trigger_type="inbound_message",
    )
    db.add(trace)
    db.commit()

    db.delete(agent)
    db.commit()
    db.refresh(trace)
    assert trace.agent_id is None, "agent_id must be SET NULL"
    assert trace.tenant_id == tenant_alpha.id


def test_on_delete_task_sets_null_leaves_tenant_intact(db: Session, tenant_alpha: Tenant):
    """Verify deleting task sets task_id = NULL on trace and step without affecting tenant_id."""
    task = Task(id=uuid4(), tenant_id=tenant_alpha.id, title="Task To Delete", objective="Objective")
    db.add(task)
    db.commit()

    trace = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=uuid4(),
        task_id=task.id,
        trigger_type="manual_api",
    )
    db.add(trace)
    db.commit()

    step = ExecutionStep(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=trace.id,
        task_id=task.id,
        step_order=1,
        step_type="tool_call",
        step_name="task_tool",
    )
    db.add(step)
    db.commit()

    db.delete(task)
    db.commit()
    db.refresh(trace)
    db.refresh(step)
    assert trace.task_id is None, "trace.task_id must be SET NULL"
    assert step.task_id is None, "step.task_id must be SET NULL"
    assert trace.tenant_id == tenant_alpha.id
    assert step.tenant_id == tenant_alpha.id


def test_on_delete_approval_sets_null_leaves_tenant_intact(db: Session, tenant_alpha: Tenant):
    """Verify deleting approval sets approval_id = NULL on step without affecting tenant_id."""
    trace = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=uuid4(),
        trigger_type="inbound_message",
    )
    db.add(trace)
    db.commit()

    approval = Approval(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        requested_for="commercial_action",
        action="approve_me",
        description="desc",
    )
    db.add(approval)
    db.commit()

    step = ExecutionStep(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=trace.id,
        approval_id=approval.id,
        step_order=1,
        step_type="approval_request",
        step_name="approval_step",
    )
    db.add(step)
    db.commit()

    db.delete(approval)
    db.commit()
    db.refresh(step)
    assert step.approval_id is None, "step.approval_id must be SET NULL"
    assert step.tenant_id == tenant_alpha.id


def test_on_delete_outbox_event_sets_null_leaves_tenant_intact(db: Session, tenant_alpha: Tenant):
    """Verify deleting outbox event sets outbox_event_id = NULL on step without affecting tenant_id."""
    conv = Conversation(id=uuid4(), tenant_id=tenant_alpha.id, subject="Outbox Conv")
    db.add(conv)
    db.flush()

    msg = Message(id=uuid4(), tenant_id=tenant_alpha.id, conversation_id=conv.id, sender_type="agent", content="Msg")
    db.add(msg)
    db.flush()

    outbox = OutboxEvent(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        conversation_id=conv.id,
        message_id=msg.id,
        idempotency_key=f"outbox:{uuid4().hex}",
    )
    trace = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=uuid4(),
        trigger_type="inbound_message",
    )
    db.add_all([outbox, trace])
    db.commit()

    step = ExecutionStep(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=trace.id,
        outbox_event_id=outbox.id,
        step_order=1,
        step_type="channel_delivery",
        step_name="channel_delivery_step",
    )
    db.add(step)
    db.commit()

    db.delete(outbox)
    db.commit()
    db.refresh(step)
    assert step.outbox_event_id is None, "step.outbox_event_id must be SET NULL"
    assert step.tenant_id == tenant_alpha.id



def test_on_delete_tenant_cascades_all_traces_and_steps(db: Session):
    """Verify that deleting a tenant cleanly cascades and deletes all its traces and steps."""
    ephemeral_tenant = create_tenant_helper(db, "Ephemeral Tenant Cascade")

    trace = ExecutionTrace(
        id=uuid4(),
        tenant_id=ephemeral_tenant.id,
        trace_id=uuid4(),
        trigger_type="inbound_message",
    )
    db.add(trace)
    db.commit()

    step = ExecutionStep(
        id=uuid4(),
        tenant_id=ephemeral_tenant.id,
        trace_id=trace.id,
        step_order=1,
        step_type="llm_reasoning",
        step_name="reasoning",
    )
    db.add(step)
    db.commit()

    trace_id_val = trace.id
    step_id_val = step.id

    # Delete the tenant
    db.delete(ephemeral_tenant)
    db.commit()

    # Both trace and step must be cascaded away
    f_trace = db.scalar(select(ExecutionTrace).where(ExecutionTrace.id == trace_id_val))
    f_step = db.scalar(select(ExecutionStep).where(ExecutionStep.id == step_id_val))
    assert f_trace is None, "Trace must be deleted when tenant is deleted"
    assert f_step is None, "Step must be deleted when tenant is deleted"


def test_on_delete_parent_step_cascades_child_steps(db: Session, tenant_alpha: Tenant):
    """Verify that deleting a parent step cascades and deletes its child steps."""
    trace = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=uuid4(),
        trigger_type="inbound_message",
    )
    db.add(trace)
    db.commit()

    parent = ExecutionStep(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=trace.id,
        step_order=1,
        step_type="subagent_delegation",
        step_name="subagent_lead",
    )
    db.add(parent)
    db.commit()

    child = ExecutionStep(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=trace.id,
        parent_step_id=parent.id,
        step_order=2,
        step_type="tool_call",
        step_name="child_tool",
    )
    db.add(child)
    db.commit()

    child_id_val = child.id

    # Delete parent step
    db.delete(parent)
    db.commit()

    f_child = db.scalar(select(ExecutionStep).where(ExecutionStep.id == child_id_val))
    assert f_child is None, "Child step must be deleted when parent step is deleted via CASCADE"


def test_alembic_downgrade_and_upgrade_cycle_preserves_existing_data(db: Session, tenant_alpha: Tenant):
    """
    Verify that Alembic downgrade to previous revision:
    1. Cleanly drops execution_traces and execution_steps and their composite unique constraints.
    2. Leaves all pre-existing tables and their existing rows completely intact.
    3. Re-upgrades cleanly to head without data loss.
    """
    # 1. Seed pre-existing tables with real data
    agent = Agent(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        name="Preserved Agent",
        agent_type="main",
    )
    task = Task(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        title="Preserved Task",
        objective="Verify migration safety",
    )
    conv = Conversation(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        subject="Preserved Conversation",
    )
    db.add_all([agent, task, conv])
    db.flush()

    msg = Message(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        conversation_id=conv.id,
        sender_type="customer",
        content="Preserved Message",
    )
    approval = Approval(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        task_id=task.id,
        requested_for="commercial_action",
        action="preserved_action",
        description="Preserved Approval",
    )
    outbox = OutboxEvent(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        conversation_id=conv.id,
        message_id=msg.id,
        idempotency_key=f"outbox:preserve:{uuid4().hex}",
        event_type="send_channel_message",
    )
    db.add_all([msg, approval, outbox])
    db.commit()

    agent_id = agent.id
    task_id = task.id
    conv_id = conv.id
    msg_id = msg.id
    approval_id = approval.id
    outbox_id = outbox.id

    # Add execution trace and step to verify they get dropped
    trace = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=uuid4(),
        trigger_type="inbound_message",
        agent_id=agent_id,
        task_id=task_id,
        conversation_id=conv_id,
    )
    db.add(trace)
    db.commit()

    step = ExecutionStep(
        id=uuid4(),
        tenant_id=tenant_alpha.id,
        trace_id=trace.id,
        step_order=1,
        step_type="tool_call",
        step_name="preserve_test",
    )
    db.add(step)
    db.commit()
    db.close()

    alembic_cfg = get_alembic_config()

    # 2. Downgrade by revision (to f6a7b8c9d0e1)
    command.downgrade(alembic_cfg, "f6a7b8c9d0e1")

    engine.dispose()
    inspector = inspect(engine)
    tables_after_downgrade = inspector.get_table_names()
    assert "execution_traces" not in tables_after_downgrade
    assert "execution_steps" not in tables_after_downgrade

    # Ensure pre-existing tables still exist
    for tbl in ["tenants", "agents", "tasks", "conversations", "messages", "approvals", "outbox_events"]:
        assert tbl in tables_after_downgrade, f"Table {tbl} must survive downgrade"

    # Query with raw connection to verify pre-existing data is 100% intact
    with engine.connect() as conn:
        assert conn.execute(select(Agent.id).where(Agent.id == agent_id)).scalar() == agent_id
        assert conn.execute(select(Task.id).where(Task.id == task_id)).scalar() == task_id
        assert conn.execute(select(Conversation.id).where(Conversation.id == conv_id)).scalar() == conv_id
        assert conn.execute(select(Message.id).where(Message.id == msg_id)).scalar() == msg_id
        assert conn.execute(select(Approval.id).where(Approval.id == approval_id)).scalar() == approval_id
        assert conn.execute(select(OutboxEvent.id).where(OutboxEvent.id == outbox_id)).scalar() == outbox_id

    # 3. Re-upgrade to head
    command.upgrade(alembic_cfg, "head")

    engine.dispose()
    inspector = inspect(engine)
    tables_after_upgrade = inspector.get_table_names()
    assert "execution_traces" in tables_after_upgrade
    assert "execution_steps" in tables_after_upgrade

    # Verify pre-existing data is still intact after re-upgrade
    with engine.connect() as conn:
        assert conn.execute(select(Agent.id).where(Agent.id == agent_id)).scalar() == agent_id
        assert conn.execute(select(Task.id).where(Task.id == task_id)).scalar() == task_id
        assert conn.execute(select(Conversation.id).where(Conversation.id == conv_id)).scalar() == conv_id
        assert conn.execute(select(Message.id).where(Message.id == msg_id)).scalar() == msg_id
        assert conn.execute(select(Approval.id).where(Approval.id == approval_id)).scalar() == approval_id
        assert conn.execute(select(OutboxEvent.id).where(OutboxEvent.id == outbox_id)).scalar() == outbox_id

