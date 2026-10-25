"""
Live Groq Interview Simulation for:
1. Honey Shop (متجر ومناحل البركة للعسل الطبيعي)
2. Cloud Software Company (شركة المنذر للحلول البرمجية الذكية)

Exercises the REAL router -> engine path with live Groq AIProvider.
Produces full conversational transcripts and detailed topic coverage tables.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath("."))
import json
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

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


def create_simulation_tenant(db: Session, name: str, owner_id: str) -> tuple[UUID, UUID]:
    tenant_id = uuid4()
    channel_id = uuid4()

    tenant = Tenant(
        id=tenant_id,
        name=name,
        slug=f"sim-{uuid4().hex[:8]}",
        status="active",
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


def run_honey_shop_simulation(groq_provider):
    db = SessionLocal()
    try:
        owner_id = "967771111111"
        tenant_id, channel_id = create_simulation_tenant(db, "متجر ومناحل البركة للعسل الطبيعي", owner_id)
        engine = ConversationalAgentEngine(db=db, ai_provider=groq_provider)

        transcript: list[dict[str, str]] = []

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

        for turn_idx, text in enumerate(turns, 1):
            u_text, ai_reply = send_turn(db, engine, tenant_id, channel_id, owner_id, text)
            transcript.append({"turn": turn_idx, "owner": u_text, "ai": ai_reply})

        # Fetch topics and statuses
        db.expire_all()
        topics = db.scalars(select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id).order_by(InterviewTopic.criticality.desc())).all()

        topic_table = []
        for t in topics:
            what_said = "-"
            if t.source_message_id:
                src_msg = db.scalar(select(Message).where(Message.id == t.source_message_id))
                if src_msg and src_msg.content:
                    what_said = src_msg.content.strip()

            topic_table.append({
                "slug": t.slug,
                "label": t.label,
                "status": t.status,
                "coverage": f"{int((t.coverage or 0.0) * 100)}%",
                "criticality": t.criticality,
                "decided_by": getattr(t, "decided_by", None) or "model",
                "what_owner_said": what_said,
            })

        # Facts
        facts = db.scalars(select(Fact).where(Fact.tenant_id == tenant_id, Fact.status == "confirmed")).all()
        fact_list = [{"topic": f.topic, "subject": f.subject, "value": f.value} for f in facts]

        return {
            "business": "Honey Shop (مناحل البركة)",
            "transcript": transcript,
            "topics": topic_table,
            "facts": fact_list,
        }
    finally:
        db.close()


def run_software_company_simulation(groq_provider):
    db = SessionLocal()
    try:
        owner_id = "967772222222"
        tenant_id, channel_id = create_simulation_tenant(db, "شركة المنذر للحلول البرمجية الذكية", owner_id)
        engine = ConversationalAgentEngine(db=db, ai_provider=groq_provider)

        transcript: list[dict[str, str]] = []

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

        for turn_idx, text in enumerate(turns, 1):
            u_text, ai_reply = send_turn(db, engine, tenant_id, channel_id, owner_id, text)
            transcript.append({"turn": turn_idx, "owner": u_text, "ai": ai_reply})

        # Fetch topics and statuses
        db.expire_all()
        topics = db.scalars(select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id).order_by(InterviewTopic.criticality.desc())).all()

        topic_table = []
        for t in topics:
            what_said = "-"
            if t.source_message_id:
                src_msg = db.scalar(select(Message).where(Message.id == t.source_message_id))
                if src_msg and src_msg.content:
                    what_said = src_msg.content.strip()

            topic_table.append({
                "slug": t.slug,
                "label": t.label,
                "status": t.status,
                "coverage": f"{int((t.coverage or 0.0) * 100)}%",
                "criticality": t.criticality,
                "decided_by": getattr(t, "decided_by", None) or "model",
                "what_owner_said": what_said,
            })

        # Facts
        facts = db.scalars(select(Fact).where(Fact.tenant_id == tenant_id, Fact.status == "confirmed")).all()
        fact_list = [{"topic": f.topic, "subject": f.subject, "value": f.value} for f in facts]

        return {
            "business": "Software Company (شركة المنذر للحلول البرمجية الذكية)",
            "transcript": transcript,
            "topics": topic_table,
            "facts": fact_list,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print("Initializing Live Groq Provider...")
    groq = AIProviderFactory.create_provider("groq")

    print("\n================ RUNNING HONEY SHOP LIVE SIMULATION ================\n")
    honey_res = run_honey_shop_simulation(groq)

    print("\n================ RUNNING SOFTWARE COMPANY LIVE SIMULATION ================\n")
    sw_res = run_software_company_simulation(groq)

    with open("scratch/simulation_results.json", "w", encoding="utf-8") as f:
        json.dump({"honey": honey_res, "software": sw_res}, f, ensure_ascii=False, indent=2)

    print("\nCompleted live simulations successfully! Saved results to scratch/simulation_results.json")
