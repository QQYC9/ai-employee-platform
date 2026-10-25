#!/usr/bin/env python3
"""
Admin CLI script to bulk re-register Telegram webhooks across all active Telegram channels.
Useful when public tunnel URL (Cloudflare, Ngrok) restarts or domain changes.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Sequence

sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from sqlalchemy import select

from packages.core.config import settings
from packages.core.database import SessionLocal
from packages.models.domain import Channel
from packages.models.tenant import Tenant
from packages.services.channel_service import ChannelService


def parse_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bulk re-register Telegram webhooks for all active Telegram channels."
    )
    parser.add_argument(
        "--public-url",
        type=str,
        default=None,
        help="Public HTTPS base URL (e.g. https://xyz.trycloudflare.com). Defaults to WEBHOOK_BASE_URL.",
    )
    parser.add_argument(
        "--channel-id",
        type=str,
        default=None,
        help="Optional single channel UUID to re-register.",
    )
    parser.add_argument(
        "--drop-pending-updates",
        action="store_true",
        default=False,
        help="Drop pending updates at Telegram when setting webhook (default: False).",
    )
    return parser.parse_args(args)


def main(args: Sequence[str] | None = None) -> int:
    parsed = parse_args(args)
    public_url = (parsed.public_url or settings.effective_webhook_base_url or "").strip().rstrip("/")
    if not public_url:
        print("ERROR: No public webhook base URL provided or configured in settings.", file=sys.stderr)
        return 1

    print(f"[*] Target Public Webhook Base: {public_url}")

    with SessionLocal() as db:
        service = ChannelService(db)
        query = select(Channel).where(
            Channel.channel_type == "telegram",
            Channel.status == "active",
        )
        if parsed.channel_id:
            query = query.where(Channel.id == parsed.channel_id)

        channels = list(db.scalars(query).all())
        if not channels:
            print("[-] No active Telegram channels found to re-register.")
            return 0

        print(f"[*] Found {len(channels)} active Telegram channel(s). Starting re-registration...")
        print("-" * 75)

        success_count = 0
        failure_count = 0

        for ch in channels:
            tenant = db.scalar(select(Tenant).where(Tenant.id == ch.tenant_id))
            tenant_name = tenant.name if tenant else "Unknown Tenant"
            print(f"-> Channel: '{ch.name}' [{ch.id}] | Tenant: '{tenant_name}' [{ch.tenant_id}]")

            ok, err_desc = service.register_telegram_webhook(
                ch,
                public_base_url=public_url,
                drop_pending_updates=parsed.drop_pending_updates,
            )

            if not ok:
                failure_count += 1
                print(f"   [FAIL] Registration failed: {err_desc}")
                continue

            test_res = service.test_channel_connection(ch.tenant_id, ch.id)
            if test_res.connected:
                success_count += 1
                wh_url = (ch.config or {}).get("webhook_url", "")
                print(f"   [OK] Webhook registered: {wh_url} (latency: {test_res.latency_ms}ms)")
            else:
                failure_count += 1
                print(f"   [FAIL] Connectivity probe failed: {test_res.error}")

        db.commit()

        print("-" * 75)
        print(f"[*] Summary: {success_count} succeeded, {failure_count} failed out of {len(channels)} total.")
        return 0 if failure_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
