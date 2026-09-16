"""
agents/comms/schedule_email.py
==============================
Schedule research emails for future delivery via Supabase queue.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from langchain_core.tools import tool

NIGERIA_TZ = timezone(timedelta(hours=1))


def _get_supabase_client():
    try:
        from agents.comms.email import _supabase
        if _supabase is not None:
            return _supabase
    except ImportError:
        pass
    import os
    from supabase import create_client
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    if url and key:
        try:
            return create_client(url, key)
        except Exception:
            return None
    return None


@tool
def schedule_research_email(
    to_email: str,
    subject: str,
    research_content: str,
    schedule_at: str,
) -> str:
    """Schedule a research report to be sent at a specific future date and time."""
    supabase = _get_supabase_client()
    if not supabase:
        return "Scheduling failed: Supabase is not configured. Please set SUPABASE_URL and SUPABASE_KEY in .env"

    if not to_email or "@" not in to_email:
        return f"Scheduling failed: '{to_email}' is not a valid email address."

    try:
        text = (schedule_at or "").strip()
        now_utc = datetime.now(timezone.utc)

        if text.lower().startswith("tomorrow"):
            target_local = (datetime.now(NIGERIA_TZ) + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            target_time = target_local.astimezone(timezone.utc).isoformat()
        else:
            normalized = text.replace("Z", "+00:00")
            scheduled_dt = datetime.fromisoformat(normalized)
            if scheduled_dt.tzinfo is None:
                scheduled_dt = scheduled_dt.replace(tzinfo=NIGERIA_TZ)
            target_time = scheduled_dt.astimezone(timezone.utc).isoformat()

        if datetime.fromisoformat(target_time.replace("Z", "+00:00")) <= now_utc:
            return "Scheduling failed: time must be in the future."

        supabase.table("jessica_scheduled_emails").insert({
            "to_email": to_email,
            "subject": subject,
            "body": research_content,
            "scheduled_at": target_time,
            "status": "pending",
            "created_at": now_utc.isoformat(),
        }).execute()

        return (
            f"📅 Email scheduled successfully!\n"
            f"Recipient : {to_email}\n"
            f"Subject   : {subject}\n"
            f"Time      : {target_time}\n"
            f"Status    : Pending in Supabase queue"
        )
    except Exception as e:
        return f"Scheduling failed: {str(e)}"


__all__ = [
    "schedule_research_email",
    "NIGERIA_TZ",
]
