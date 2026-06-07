"""
LoanCentral notification helpers.
All functions are fire-and-forget — they log warnings but never raise.
"""

import os
import logging

logger = logging.getLogger("LoanCentral")


def notify_discord(message: str):
    """Post a plain-text message to a Discord webhook. No-op if not configured."""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        return
    try:
        import requests
        requests.post(webhook_url, json={"content": message}, timeout=5)
    except Exception as e:
        logger.warning(f"Discord notification failed: {e}")
