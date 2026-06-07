"""
LoanCentral notification helpers.
All functions are fire-and-forget — they log warnings but never raise.
"""

import os
import logging

logger = logging.getLogger("LoanCentral")


def notify_discord(message: str, retries: int = 2):
    """Post a plain-text message to a Discord webhook. No-op if not configured."""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        return
    import time
    for attempt in range(retries + 1):
        try:
            import requests
            resp = requests.post(webhook_url, json={"content": message}, timeout=5)
            if resp.status_code < 300:
                return
            logger.warning(f"Discord webhook returned {resp.status_code} (attempt {attempt + 1})")
        except Exception as e:
            logger.warning(f"Discord notification failed (attempt {attempt + 1}): {e}")
        if attempt < retries:
            time.sleep(2 ** attempt)  # 1s, 2s backoff


def notify_email(subject: str, body: str, to: str = None):
    """Send a plain-text email via SMTP. No-op if SMTP_HOST is not configured."""
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    from_addr = os.getenv("SMTP_FROM", smtp_user)
    to_addr   = to or os.getenv("ADMIN_EMAIL", "")
    if not all([smtp_host, smtp_user, smtp_pass, to_addr]):
        return
    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(body, "plain")
        msg["Subject"] = f"[LoanCentral] {subject}"
        msg["From"]    = from_addr
        msg["To"]      = to_addr
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, [to_addr], msg.as_string())
    except Exception as e:
        logger.warning(f"Email notification failed: {e}")
