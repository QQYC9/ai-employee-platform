"""
Live Groq Interview Simulation for:
1. Honey Shop (متجر ومناحل البركة للعسل الطبيعي)
2. Cloud Software Company (شركة المنذر للحلول البرمجية الذكية)

Exercises the REAL router -> engine path with live Groq AIProvider.
Produces full conversational transcripts, token measurements, and detailed topic coverage tables.
"""
from __future__ import annotations

import os
import sys
import time
import json
import re
from uuid import UUID, uuid4

sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.ai_providers.base import AIRateLimitError
from packages.ai_providers.factory import AIProviderFactory
from packages.connectors.base import InboundMessage
from packages.core.database import SessionLocal
from packages.models.domain import (
    BusinessBrain,
    Channel,
    Fact,
    InterviewState,
    InterviewTopic,
    Message,
    User,
)
from packages.models.tenant import Tenant
from packages.services.channel_service import ChannelService
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.interview_service import InterviewService


class UsageTrackingAIProvider:
    """Wraps an AIProvider to measure tokens per turn, total per interview, and handle rate-limits."""

    def __init__(self, inner):
        self._inner = inner
        self.turn_calls = 0
        self.turn_prompt_tokens = 0
        self.turn_completion_tokens = 0
        self.turn_total_tokens = 0
        self.total_interview_tokens = 0
        self.total_interview_prompt_tokens = 0
        self.total_interview_completion_tokens = 0
        self.history = []

    def start_turn(self):
        self.turn_calls = 0
        self.turn_prompt_tokens = 0
        self.turn_completion_tokens = 0
        self.turn_total_tokens = 0

    def end_turn(self):
        turn_data = {
            "calls": self.turn_calls,
            "prompt_tokens": self.turn_prompt_tokens,
            "completion_tokens": self.turn_completion_tokens,
            "total_tokens": self.turn_total_tokens,
        }
        self.history.append(turn_data)
        return turn_data

    def generate_text(self, *args, **kwargs):
        max_retries = 4
        backoff = 4.0
        for attempt in range(max_retries):
            try:
                res = self._inner.generate_text(*args, **kwargs)
                usage = getattr(self._inner, "last_usage", None) or {}
                p_tok = int(usage.get("prompt_tokens") or 0)
                c_tok = int(usage.get("completion_tokens") or 0)
                t_tok = int(usage.get("total_tokens") or (p_tok + c_tok))
                self.turn_calls += 1
                self.turn_prompt_tokens += p_tok
                self.turn_completion_tokens += c_tok
                self.turn_total_tokens += t_tok
                self.total_interview_tokens += t_tok
                self.total_interview_prompt_tokens += p_tok
                self.total_interview_completion_tokens += c_tok
                return res
            except AIRateLimitError as rle:
                delay = backoff
                m = re.search(r"try again in ([0-9\.]+)s", str(rle))
                if m:
                    delay = max(float(m.group(1)) + 1.5, delay)
                if attempt < max_retries - 1:
                    print(f"    [Rate limit pause in generate_text: sleeping {delay:.1f}s...]")
                    time.sleep(delay)
                    backoff *= 2.0
                else:
                    raise

    def generate_json(self, *args, **kwargs):
        max_retries = 4
        backoff = 4.0
        for attempt in range(max_retries):
            try:
                res = self._inner.generate_json(*args, **kwargs)
                usage = getattr(self._inner, "last_usage", None) or {}
                p_tok = int(usage.get("prompt_tokens") or 0)
                c_tok = int(usage.get("completion_tokens") or 0)
                t_tok = int(usage.get("total_tokens") or (p_tok + c_tok))
                self.turn_calls += 1
                self.turn_prompt_tokens += p_tok
                self.turn_completion_tokens += c_tok
                self.turn_total_tokens += t_tok
                self.total_interview_tokens += t_tok
                self.total_interview_prompt_tokens += p_tok
                self.total_interview_completion_tokens += c_tok
                return res
            except AIRateLimitError as rle:
                delay = backoff
                m = re.search(r"try again in ([0-9\.]+)s", str(rle))
                if m:
                    delay = max(float(m.group(1)) + 1.5, delay)
                if attempt < max_retries - 1:
                    print(f"    [Rate limit pause in generate_json: sleeping {delay:.1f}s...]")
                    time.sleep(delay)
                    backoff *= 2.0
                else:
                    raise


def create_simulation_tenant(db: Session, name: str, owner_id: str) -> tuple[UUID, UUID]:
    tenant_id = uuid4()
    channel_id = uuid4()

    tenant = Tenant(
        id=tenant_id,
        name=name,
        slug=f"sim-{uuid4().hex[:8]}",
        status="active",
        employee_name="سارة",
        interview_required=True,
        interview_threshold=80.0,
    )
    db.add(tenant)
    db.flush()

    user = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email=f"owner_{uuid4().hex[:6]}@sim.local",
        name="Business Owner",
        role="tenant_owner",
        status="active",
    )
    db.add(user)

    channel = Channel(
        id=channel_id,
        tenant_id=tenant_id,
        name="Telegram Connector",
        channel_type="telegram",
        status="active",
        config={
            "bot_token": "sim_bot_token",
            "owner_identifiers": [owner_id],
            "owner_sender_ids": [owner_id],
        },
    )
    db.add(channel)

    brain = BusinessBrain(
        tenant_id=tenant_id,
        identity={"name": name},
        products={},
        services={},
        pricing={},
        operations={},
        policies={},
    )
    db.add(brain)
    db.commit()

    return tenant_id, channel_id


def send_turn(
    db: Session,
    engine: ConversationalAgentEngine,
    tenant_id: UUID,
    channel_id: UUID,
    sender_id: str,
    user_text: str,
) -> tuple[str, str]:
    inbound = InboundMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        channel_type="telegram",
        external_message_id=f"msg_{uuid4().hex[:10]}",
        sender_id=sender_id,
        sender_name="Owner",
        content=user_text,
        content_type="text",
        raw_payload={"text": user_text, "from": {"id": sender_id}},
    )
    channel_svc = ChannelService(db)
    msg = channel_svc.process_inbound_message(inbound)
    db.commit()

    res = engine.process_incoming_message(tenant_id, msg.id)
    return user_text, res.reply_content


def run_honey_shop_simulation(raw_provider):
    db = SessionLocal()
    tracker = UsageTrackingAIProvider(raw_provider)
    try:
        owner_id = "967771111111"
        tenant_id, channel_id = create_simulation_tenant(db, "متجر ومناحل البركة للعسل الطبيعي", owner_id)
        engine = ConversationalAgentEngine(db=db, ai_provider=tracker)

        transcript: list[dict[str, any]] = []

        turns = [
            # 1. Start interview
            "ابدأ التعارف",
            # 2. Q1: Name
            "أنا أحمد البركة",
            # 3. Q2: Role
            "صاحب المنشأة والمؤسس",
            # 4. Q3: Entity type
            "متجر فعلي ومحل لبيع العسل",
            # 5. Q4: Country & Field
            "اليمن - تجارة العسل الطبيعي والمناحل",
            # 6. Q5 asked is ordering_payment -> Owner answers with honey types (off-target answer to test content evaluation)
            "لدينا عسل سدر دوعني وعسل سمر وعسل مراعي طبيعي مفحوص مخبرياً",
            # 7. Owner answers the re-asked payment question
            "طرق الدفع المعتمدة هي الدفع عند الاستلام داخل صنعاء أو التحويل البنكي عبر الكريمي والنجم",
            # 8. Products & Pricing
            "نبيع عسل سدر دوعني فاخر بسعر 50000 ريال يمني وعسل سمر جبلي بسعر 35000 ريال يمني",
            # 9. Packaging sizes question (saying 'لا' to test answer semantics)
            "لا، نبيع فقط عبوة كيلو ونصف كيلو ولا نوفر أحجام أخرى حالياً",
            # 10. Delivery coverage
            "نوصل لجميع مناطق صنعاء عبر مندوبين ونشحن لباقي المحافظات اليمنية",
        ]

        print(f"\n--- Starting Honey Shop Simulation (Tenant {tenant_id}) ---")
        for turn_idx, text in enumerate(turns, 1):
            tracker.start_turn()
            u_text, ai_reply = send_turn(db, engine, tenant_id, channel_id, owner_id, text)
            turn_usage = tracker.end_turn()
            transcript.append({
                "turn": turn_idx,
                "owner": u_text,
                "ai": ai_reply,
                "usage": turn_usage,
            })
            print(f"Turn {turn_idx} finished. Owner: '{u_text[:35]}...' | Total Tokens: {turn_usage['total_tokens']} (Prompt: {turn_usage['prompt_tokens']}, Compl: {turn_usage['completion_tokens']})")
            time.sleep(3.0)  # Throttling to prevent provider TPM rate limits

        # Fetch state and attempts
        db.expire_all()
        interview_state = db.scalar(select(InterviewState).where(InterviewState.tenant_id == tenant_id))
        attempts_map = (interview_state.classification_answers or {}).get("topic_attempts", {}) if interview_state else {}

        # Fetch topics and statuses
        topics = db.scalars(
            select(InterviewTopic)
            .where(InterviewTopic.tenant_id == tenant_id)
            .order_by(InterviewTopic.criticality.desc())
        ).all()

        topic_table = []
        for t in topics:
            what_said = "-"
            if t.source_message_id:
                src_msg = db.scalar(select(Message).where(Message.id == t.source_message_id))
                if src_msg and src_msg.content:
                    what_said = src_msg.content.strip()

            attempts = attempts_map.get(t.slug)
            if attempts is None:
                attempts = 1 if t.status in ("answered", "asked", "partial") else 0

            decided = getattr(t, "decided_by", None) or "model"

            topic_table.append({
                "slug": t.slug,
                "label": t.label,
                "status": t.status,
                "attempts": attempts,
                "coverage": f"{int((t.coverage or 0.0) * 100)}%",
                "criticality": t.criticality,
                "decided_by": decided,
                "what_owner_said": what_said,
            })

        decided_counts = {
            "model": sum(1 for t in topic_table if t["decided_by"] == "model"),
            "fallback": sum(1 for t in topic_table if t["decided_by"] == "fallback"),
        }

        # Facts
        facts = db.scalars(select(Fact).where(Fact.tenant_id == tenant_id, Fact.status == "confirmed")).all()
        fact_list = [{"topic": f.topic, "subject": f.subject, "value": f.value} for f in facts]

        return {
            "business": "Honey Shop (متجر ومناحل البركة للعسل الطبيعي)",
            "transcript": transcript,
            "topics": topic_table,
            "decided_by_counts": decided_counts,
            "facts": fact_list,
            "total_tokens": {
                "prompt_tokens": tracker.total_interview_prompt_tokens,
                "completion_tokens": tracker.total_interview_completion_tokens,
                "total_tokens": tracker.total_interview_tokens,
            },
        }
    finally:
        db.close()


def run_software_company_simulation(raw_provider):
    db = SessionLocal()
    tracker = UsageTrackingAIProvider(raw_provider)
    try:
        owner_id = "967772222222"
        tenant_id, channel_id = create_simulation_tenant(db, "شركة المنذر للحلول البرمجية الذكية", owner_id)
        engine = ConversationalAgentEngine(db=db, ai_provider=tracker)

        transcript: list[dict[str, any]] = []

        turns = [
            # 1. Start interview
            "ابدأ التعارف",
            # 2. Q1: Name
            "المهندس منذر",
            # 3. Q2: Role
            "المدير العام والتنفيذي",
            # 4. Q3: Entity type
            "شركة برمجيات وأنظمة سحابية",
            # 5. Q4: Country & Field
            "اليمن - تطوير الحلول الرقمية والأنظمة المؤسسية السحابية",
            # 6. Q5 asked is ordering_payment -> Owner answers with target clients, licenses, and support (multi-topic)
            "أنظمتنا موجهة للمؤسسات والشركات المتوسطة والكبيرة ونقدم تراخيص سنوية ودعم فني مستمر طوال الأسبوع",
            # 7. Owner answers re-asked payment question
            "طريقة الاشتراك سنوية بعقود رسمية ويتم الدفع عبر التحويل البنكي لحساب الشركة أو سداد إلكتروني معتمد",
            # 8. Products & Systems (testing verbatim extraction & no hardcoded overrides)
            "نقدم نظام الموظف الذكي السحابي وبرنامج ناظم لإدارة الشركات ومنصة الأفق للمتاجر",
            # 9. Service coverage
            "خدماتنا سحابية بالكامل ونغطي اليمن وكافة دول الخليج العربي بدون أي شحن فيزيائي",
            # 10. Tone
            "نفضل نبرة رسمية ومهنية وواضحة جداً",
        ]

        print(f"\n--- Starting Software Company Simulation (Tenant {tenant_id}) ---")
        for turn_idx, text in enumerate(turns, 1):
            tracker.start_turn()
            u_text, ai_reply = send_turn(db, engine, tenant_id, channel_id, owner_id, text)
            turn_usage = tracker.end_turn()
            transcript.append({
                "turn": turn_idx,
                "owner": u_text,
                "ai": ai_reply,
                "usage": turn_usage,
            })
            print(f"Turn {turn_idx} finished. Owner: '{u_text[:35]}...' | Total Tokens: {turn_usage['total_tokens']} (Prompt: {turn_usage['prompt_tokens']}, Compl: {turn_usage['completion_tokens']})")
            time.sleep(3.0)  # Throttling to prevent provider TPM rate limits

        # Fetch state and attempts
        db.expire_all()
        interview_state = db.scalar(select(InterviewState).where(InterviewState.tenant_id == tenant_id))
        attempts_map = (interview_state.classification_answers or {}).get("topic_attempts", {}) if interview_state else {}

        # Fetch topics and statuses
        topics = db.scalars(
            select(InterviewTopic)
            .where(InterviewTopic.tenant_id == tenant_id)
            .order_by(InterviewTopic.criticality.desc())
        ).all()

        topic_table = []
        for t in topics:
            what_said = "-"
            if t.source_message_id:
                src_msg = db.scalar(select(Message).where(Message.id == t.source_message_id))
                if src_msg and src_msg.content:
                    what_said = src_msg.content.strip()

            attempts = attempts_map.get(t.slug)
            if attempts is None:
                attempts = 1 if t.status in ("answered", "asked", "partial") else 0

            decided = getattr(t, "decided_by", None) or "model"

            topic_table.append({
                "slug": t.slug,
                "label": t.label,
                "status": t.status,
                "attempts": attempts,
                "coverage": f"{int((t.coverage or 0.0) * 100)}%",
                "criticality": t.criticality,
                "decided_by": decided,
                "what_owner_said": what_said,
            })

        decided_counts = {
            "model": sum(1 for t in topic_table if t["decided_by"] == "model"),
            "fallback": sum(1 for t in topic_table if t["decided_by"] == "fallback"),
        }

        # Facts
        facts = db.scalars(select(Fact).where(Fact.tenant_id == tenant_id, Fact.status == "confirmed")).all()
        fact_list = [{"topic": f.topic, "subject": f.subject, "value": f.value} for f in facts]

        return {
            "business": "Software Company (شركة المنذر للحلول البرمجية الذكية)",
            "transcript": transcript,
            "topics": topic_table,
            "decided_by_counts": decided_counts,
            "facts": fact_list,
            "total_tokens": {
                "prompt_tokens": tracker.total_interview_prompt_tokens,
                "completion_tokens": tracker.total_interview_completion_tokens,
                "total_tokens": tracker.total_interview_tokens,
            },
        }
    finally:
        db.close()


def print_simulation_report(data: dict):
    biz = data["business"]
    print("\n" + "=" * 90)
    print(f"EVIDENCE REPORT FOR: {biz}")
    print("=" * 90)

    print("\n[A] FULL CONVERSATIONAL TRANSCRIPT & TOKEN USAGE PER TURN:")
    for turn in data["transcript"]:
        idx = turn["turn"]
        u = turn["owner"]
        a = turn["ai"]
        tok = turn["usage"]
        print(f"\nTurn {idx}:")
        print(f"  Owner: {u}")
        print(f"  AI Reply:")
        for line in a.splitlines():
            print(f"    {line}")
        print(f"  [Usage]: {tok['total_tokens']} tokens (prompt: {tok['prompt_tokens']}, completion: {tok['completion_tokens']}, calls: {tok['calls']})")

    print(f"\n[B] TOTAL INTERVIEW TOKENS:")
    tt = data["total_tokens"]
    print(f"  • Prompt Tokens:     {tt['prompt_tokens']}")
    print(f"  • Completion Tokens: {tt['completion_tokens']}")
    print(f"  • Total Tokens:      {tt['total_tokens']}")

    print(f"\n[C] DECIDED_BY SUMMARY (MODEL VS FALLBACK):")
    dc = data["decided_by_counts"]
    print(f"  • Decided by Model:    {dc['model']}")
    print(f"  • Decided by Fallback: {dc['fallback']}")

    print("\n[D] PERSISTED DB TOPIC COVERAGE TABLE:")
    header = f"{'Topic Slug':<25} | {'Status':<12} | {'Attempts':<8} | {'DecidedBy':<10} | {'What Owner Said (Message Text)':<40}"
    print("-" * len(header))
    print(header)
    print("-" * len(header))
    for row in data["topics"]:
        slug = row["slug"][:25]
        status = row["status"][:12]
        att = str(row["attempts"])
        dec = row["decided_by"]
        said = row["what_owner_said"]
        if len(said) > 40:
            said = said[:37] + "..."
        print(f"{slug:<25} | {status:<12} | {att:<8} | {dec:<10} | {said:<40}")
    print("-" * len(header))

    print("\n[E] EXTRACTED CONFIRMED FACTS (PERSISTED DB):")
    for fact in data["facts"]:
        print(f"  • {fact['topic']} [{fact['subject']}]: {fact['value']}")


if __name__ == "__main__":
    print("Initializing Live Groq Provider...")
    groq = AIProviderFactory.create_provider("groq")

    print("\n================ RUNNING HONEY SHOP LIVE SIMULATION ================\n")
    honey_res = run_honey_shop_simulation(groq)

    print("\nPausing 10s between simulations to refresh TPM quota...\n")
    time.sleep(10.0)

    print("\n================ RUNNING SOFTWARE COMPANY LIVE SIMULATION ================\n")
    sw_res = run_software_company_simulation(groq)

    os.makedirs("scratch", exist_ok=True)
    with open("scratch/simulation_results.json", "w", encoding="utf-8") as f:
        json.dump({"honey": honey_res, "software": sw_res}, f, ensure_ascii=False, indent=2)

    print("\n" + "#" * 90)
    print_simulation_report(honey_res)
    print("\n" + "#" * 90)
    print_simulation_report(sw_res)

    print("\nCompleted live simulations successfully! Persisted results to scratch/simulation_results.json")
