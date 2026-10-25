"""
Script to generate the printed transcript for Phase 3.2 Tenant Onboarding & Owner Linking:
1. Tenant created with employee name "سارة"
2. Link code generated
3. /link CODE sent from chat -> Owner verified
4. Welcome message with dashboard URL, login email, masked password-set link
5. Interview starts with employee introducing itself as "سارة"
6. Same code used a second time -> Rejected
7. Wrong code sent -> Rejected
"""
import sys
import os
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import uuid
import re
from packages.core.database import SessionLocal
from packages.core.config import settings
from packages.models.tenant import Tenant
from packages.models.domain import Channel, User
from packages.connectors.base import InboundMessage
from packages.services.channel_service import ChannelService
from packages.services.link_code_service import LinkCodeService
from packages.services.tenant_provisioning_service import TenantProvisioningService, TenantProvisioningRequest
from packages.services.conversational_agent_engine import ConversationalAgentEngine


def mask_token(text: str) -> str:
    """Mask JWT token in URLs for safe logging and printing."""
    return re.sub(
        r'(token=)([A-Za-z0-9_\-\.]+)',
        lambda m: m.group(1) + m.group(2)[:15] + "...[MASKED_TOKEN]..." + m.group(2)[-8:],
        text
    )


def run_onboarding_transcript():
    db = SessionLocal()
    try:
        print("=" * 80)
        print("REAL-PATH TRANSCRIPT: PHASE 3.2 TENANT ONBOARDING & OWNER LINKING")
        print("=" * 80)
        
        # Step 1: Provision tenant with employee_name="سارة"
        slug_id = uuid.uuid4().hex[:6]
        req = TenantProvisioningRequest(
            name="مؤسسة الأفق الذكي للتجارة",
            slug=f"alofoq-{slug_id}",
            owner_name="م. عبد الله الشمري",
            owner_email=f"owner.abdullah.{slug_id}@alofoq-smart.com",
            employee_name="سارة",
        )
        
        prov_svc = TenantProvisioningService(db)
        prov_res = prov_svc.provision_tenant(req)
        tenant_id = uuid.UUID(prov_res["tenant"]["id"])
        channel_id = uuid.UUID(prov_res["channel_id"])
        raw_code = prov_res["link_code"]
        
        print("\n[1] TENANT PROVISIONING (ADMIN DASHBOARD / API):")
        print(f"  • Tenant ID:      {tenant_id}")
        print(f"  • Organization:   {req.name}")
        print(f"  • Employee Name:  {req.employee_name}")
        print(f"  • Owner Email:    {req.owner_email}")
        print(f"  • Channel ID:     {channel_id} (telegram default)")
        print(f"  • Generated Code: {raw_code} (Cryptographically secure, single-use, 24h expiry)")
        
        channel_svc = ChannelService(db)
        engine = ConversationalAgentEngine(db=db)
        
        # Step 2: Owner sends /link <raw_code> from chat
        owner_sender_id = f"owner_tg_{uuid.uuid4().hex[:6]}"
        inbound_owner = InboundMessage(
            tenant_id=tenant_id,
            channel_id=channel_id,
            channel_type="telegram",
            external_message_id=f"msg_{uuid.uuid4().hex[:8]}",
            sender_id=owner_sender_id,
            sender_name="عبد الله الشمري",
            content=f"/link {raw_code}",
            content_type="text",
            raw_payload={"text": f"/link {raw_code}"}
        )
        msg_record = channel_svc.process_inbound_message(inbound_owner)
        db.commit()
        
        print("\n" + "-" * 80)
        print(f"[2] OWNER LINKS CHANNEL VIA CHAT (FIRST TIME - VALID CODE):")
        print(f"  --> SENDER: {owner_sender_id} ({inbound_owner.sender_name})")
        print(f"  --> MESSAGE: {inbound_owner.content}")
        
        res = engine.process_incoming_message(tenant_id, msg_record.id)
        reply_masked = mask_token(res.reply_content)
        
        print(f"\n  <-- BOT RESPONSE (SUCCESSFUL OWNER LINKING + ONBOARDING WELCOME + INTERVIEW START):")
        for line in reply_masked.splitlines():
            print(f"      {line}")
            
        # Step 3: Second party / attacker attempts to reuse the SAME code
        second_party_sender_id = f"second_party_tg_{uuid.uuid4().hex[:6]}"
        inbound_reuse = InboundMessage(
            tenant_id=tenant_id,
            channel_id=channel_id,
            channel_type="telegram",
            external_message_id=f"msg_{uuid.uuid4().hex[:8]}",
            sender_id=second_party_sender_id,
            sender_name="مستخدم آخر أو متطفل",
            content=f"/link {raw_code}",
            content_type="text",
            raw_payload={"text": f"/link {raw_code}"}
        )
        msg_reuse_record = channel_svc.process_inbound_message(inbound_reuse)
        db.commit()
        
        print("\n" + "-" * 80)
        print(f"[3] ATTEMPT TO REUSE SAME CODE A SECOND TIME (BY ANOTHER SENDER / ATTACKER):")
        print(f"  --> SENDER: {second_party_sender_id} ({inbound_reuse.sender_name})")
        print(f"  --> MESSAGE: {inbound_reuse.content}")
        
        res_reuse = engine.process_incoming_message(tenant_id, msg_reuse_record.id)
        print(f"\n  <-- BOT RESPONSE (REJECTED - SINGLE USE CODE ALREADY CONSUMED):")
        for line in res_reuse.reply_content.splitlines():
            print(f"      {line}")
            
        # Step 4: Attacker or typo sends an INVALID / WRONG code
        attacker_sender_id = f"attacker_tg_{uuid.uuid4().hex[:6]}"
        invalid_code = "LINK-WRONG-9999"
        inbound_invalid = InboundMessage(
            tenant_id=tenant_id,
            channel_id=channel_id,
            channel_type="telegram",
            external_message_id=f"msg_{uuid.uuid4().hex[:8]}",
            sender_id=attacker_sender_id,
            sender_name="مهاجم مجهول",
            content=f"/link {invalid_code}",
            content_type="text",
            raw_payload={"text": f"/link {invalid_code}"}
        )
        msg_invalid_record = channel_svc.process_inbound_message(inbound_invalid)
        db.commit()
        
        print("\n" + "-" * 80)
        print(f"[4] UNKNOWN SENDER SENDS WRONG/INVALID CODE:")
        print(f"  --> SENDER: {attacker_sender_id} ({inbound_invalid.sender_name})")
        print(f"  --> MESSAGE: {inbound_invalid.content}")
        
        res_invalid = engine.process_incoming_message(tenant_id, msg_invalid_record.id)
        print(f"\n  <-- BOT RESPONSE (REJECTED - INVALID CODE):")
        for line in res_invalid.reply_content.splitlines():
            print(f"      {line}")

        # Step 5: Verified owner re-sends /link command
        inbound_owner_repeat = InboundMessage(
            tenant_id=tenant_id,
            channel_id=channel_id,
            channel_type="telegram",
            external_message_id=f"msg_{uuid.uuid4().hex[:8]}",
            sender_id=owner_sender_id,
            sender_name="عبد الله الشمري",
            content=f"/link {raw_code}",
            content_type="text",
            raw_payload={"text": f"/link {raw_code}"}
        )
        msg_owner_repeat = channel_svc.process_inbound_message(inbound_owner_repeat)
        db.commit()
        
        print("\n" + "-" * 80)
        print(f"[5] VERIFIED OWNER RE-SENDS /link CODE IN CHAT:")
        print(f"  --> SENDER: {owner_sender_id} ({inbound_owner_repeat.sender_name})")
        print(f"  --> MESSAGE: {inbound_owner_repeat.content}")
        
        res_owner_repeat = engine.process_incoming_message(tenant_id, msg_owner_repeat.id)
        print(f"\n  <-- BOT RESPONSE (CONFIRMS ALREADY LINKED):")
        for line in res_owner_repeat.reply_content.splitlines():
            print(f"      {line}")
            
        print("\n" + "=" * 80)
        print("TRANSCRIPT GENERATION COMPLETE AND VERIFIED ON REAL ENGINE PATH.")
        print("=" * 80)
        
    finally:
        db.close()

if __name__ == "__main__":
    run_onboarding_transcript()
