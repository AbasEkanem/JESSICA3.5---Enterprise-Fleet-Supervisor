"""
agents/comms/tools.py
=====================
Consolidated tool suite for the Communications domain supervisor (Relay).

Two service domains:
  1. Slack  — messages, threads, DMs, reactions, channel listing, user lookups
  2. Email  — send (immediate + scheduled), read inbox, search, sent log
"""

from __future__ import annotations

from typing import Any

# ── 1. Slack Tools 
from agents.comms.slack import (
    send_slack_message,
    reply_to_slack_thread,
    send_slack_dm,
    get_slack_channel_history,
    get_slack_thread_replies,
    add_slack_reaction,
    list_slack_channels,
    lookup_slack_user,
    SLACK_TOOLS,
)

# ── 2. Email Tools
from agents.comms.email import (
    send_research_email,
    schedule_research_email,
    read_inbox,
    search_emails,
    get_sent_email_log,
    EMAIL_TOOLS,
    EMAIL_SEND_TOOLS,
    EMAIL_READ_TOOLS,
)

# ── Complete Suite
COMMS_TOOLS: list[Any] = SLACK_TOOLS + EMAIL_TOOLS

# ── Service Lookup Map
COMMS_TOOL_MAP: dict[str, list[Any]] = {
    "slack": SLACK_TOOLS,
    "email": EMAIL_TOOLS,
    "email_send": EMAIL_SEND_TOOLS,
    "email_read": EMAIL_READ_TOOLS,
}

__all__ = [
    # Master collection
    "COMMS_TOOLS",
    "COMMS_TOOL_MAP",
    # Subsets
    "SLACK_TOOLS",
    "EMAIL_TOOLS",
    "EMAIL_SEND_TOOLS",
    "EMAIL_READ_TOOLS",
    # Slack callables
    "send_slack_message",
    "reply_to_slack_thread",
    "send_slack_dm",
    "get_slack_channel_history",
    "get_slack_thread_replies",
    "add_slack_reaction",
    "list_slack_channels",
    "lookup_slack_user",
    # Email callables
    "send_research_email",
    "schedule_research_email",
    "read_inbox",
    "search_emails",
    "get_sent_email_log",
]
