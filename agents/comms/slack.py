"""
agents/comms/slack.py
=====================
Complete Slack tools for Jessica 3.5.

Includes messaging, threading, DMs, channel history, reactions,
channel listing with membership detection, and user lookup.
"""

from __future__ import annotations

import os
from typing import Optional
from dotenv import load_dotenv
from langchain.tools import tool
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_async_handlers import (
    AsyncConnectionErrorRetryHandler,
    AsyncRateLimitErrorRetryHandler,
)
from slack_sdk.web.async_client import AsyncWebClient

load_dotenv()

_client: AsyncWebClient | None = None


def _get_client() -> AsyncWebClient:
    """Lazy AsyncWebClient with proper rate-limit + connection retries."""
    global _client
    if _client is None:
        token = os.getenv("SLACK_BOT_TOKEN", "")
        if not token:
            raise RuntimeError("[slack_tools] SLACK_BOT_TOKEN is not set.")

        _client = AsyncWebClient(
            token=token,
            timeout=10,
            retry_handlers=[
                AsyncConnectionErrorRetryHandler(),
                AsyncRateLimitErrorRetryHandler(max_retry_count=2),
            ],
        )
    return _client


# ── Tools ────────────────────────────────────────────────────────────────────

@tool
async def send_slack_message(channel: str, message: str) -> str:
    """Send message to channel/user."""
    try:
        await _get_client().chat_postMessage(channel=channel, text=message)
        return f"✅ Sent to {channel}"
    except SlackApiError as e:
        return f"⚠️ Send failed: {e.response['error']}"
    except Exception as e:
        return f"⚠️ Send error: {e}"


@tool
async def reply_to_slack_thread(channel: str, thread_ts: str, message: str) -> str:
    """Reply in a thread."""
    try:
        await _get_client().chat_postMessage(channel=channel, thread_ts=thread_ts, text=message)
        return f"✅ Replied to thread {thread_ts}"
    except SlackApiError as e:
        return f"⚠️ Reply failed: {e.response['error']}"
    except Exception as e:
        return f"⚠️ Reply error: {e}"


@tool
async def send_slack_dm(user_email: str, message: str) -> str:
    """Send DM by email."""
    try:
        client = _get_client()
        user = (await client.users_lookupByEmail(email=user_email))["user"]["id"]
        channel = (await client.conversations_open(users=user))["channel"]["id"]
        await client.chat_postMessage(channel=channel, text=message)
        return f"✅ DM sent to {user_email}"
    except SlackApiError as e:
        return f"⚠️ DM failed: {e.response['error']}"
    except Exception as e:
        return f"⚠️ DM error: {e}"


async def _fetch_history(client, channel: str, max_messages: int):
    """Fetch history, auto-joining a public channel once if the bot isn't in it."""
    try:
        return await client.conversations_history(channel=channel, limit=max_messages)
    except SlackApiError as e:
        # The bot can only read history from channels it has joined. For PUBLIC
        # channels it can self-join with conversations_join, then retry ONCE.
        # (Private channels / DMs cannot be auto-joined — surface the error.)
        if e.response.get("error") == "not_in_channel":
            try:
                await client.conversations_join(channel=channel)
                return await client.conversations_history(channel=channel, limit=max_messages)
            except SlackApiError:
                raise e
        raise


@tool
async def get_slack_channel_history(channel: str, max_messages: int = 10) -> str:
    """Get recent messages from a channel. Auto-joins public channels the bot is
    not yet a member of, so a `not_in_channel` error does not require retrying.

    Args:
        channel: The channel ID (e.g. 'C0123ABC') to read history from.
        max_messages: How many recent messages to fetch (default 10).
    """
    try:
        result = await _fetch_history(_get_client(), channel, max_messages)
        messages = result.get("messages", [])
        if not messages:
            return f"No messages in {channel}."
        lines = [f"Last {len(messages)} in {channel}:"]
        for m in reversed(messages):
            lines.append(f"\n[{m.get('ts')}] <@{m.get('user', 'Unknown')}>: {m.get('text', '')[:200]}")
        return "\n".join(lines)
    except SlackApiError as e:
        err = e.response.get("error", "unknown")
        if err == "not_in_channel":
            return (
                f"⚠️ Not a member of {channel} and it could not be auto-joined "
                f"(it is likely private). Skip this channel — do NOT retry it."
            )
        return f"⚠️ History failed: {err}"
    except Exception as e:
        return f"⚠️ History error: {e}"


@tool
async def get_slack_thread_replies(channel: str, thread_ts: str) -> str:
    """Get thread replies."""
    try:
        result = await _get_client().conversations_replies(channel=channel, ts=thread_ts)
        messages = result.get("messages", [])
        if not messages:
            return "No replies in thread."
        lines = [f"Thread replies ({len(messages)}):"]
        for m in messages:
            lines.append(f"\n[{m.get('ts')}] <@{m.get('user', 'Unknown')}>: {m.get('text', '')[:200]}")
        return "\n".join(lines)
    except SlackApiError as e:
        return f"⚠️ Thread failed: {e.response['error']}"
    except Exception as e:
        return f"⚠️ Thread error: {e}"


@tool
async def add_slack_reaction(channel: str, timestamp: str, emoji: str) -> str:
    """Add reaction to message."""
    try:
        await _get_client().reactions_add(channel=channel, timestamp=timestamp, name=emoji)
        return f"✅ Added :{emoji}:"
    except SlackApiError as e:
        return f"⚠️ Reaction failed: {e.response['error']}"
    except Exception as e:
        return f"⚠️ Reaction error: {e}"


@tool
async def list_slack_channels(exclude_archived: bool = True, limit: int = 50, member_only: bool = False) -> str:
    """List channels, flagging which ones the bot is already a MEMBER of.

    Each row shows a ✅ (bot IS a member — history readable directly) or a ➕
    (bot is NOT a member — a public channel can be auto-joined on read, a private
    one cannot). To scan activity, read history ONLY from ✅ channels first;
    never blindly probe every channel.

    Args:
        exclude_archived: Skip archived channels (default True).
        limit: Max channels to return (default 50).
        member_only: If True, return ONLY channels the bot has already joined —
                     use this before scanning recent activity to avoid
                     `not_in_channel` errors and wasted retries.
    """
    try:
        result = await _get_client().conversations_list(exclude_archived=exclude_archived, limit=limit)
        channels = result.get("channels", [])
        if member_only:
            channels = [c for c in channels if c.get("is_member")]
        if not channels:
            return "No member channels found." if member_only else "No channels found."
        label = "Member channels" if member_only else "Channels"
        lines = [f"{label} ({len(channels)}):"]
        for ch in channels:
            flag = "✅ member" if ch.get("is_member") else "➕ not a member"
            lines.append(
                f"• #{ch.get('name')} (ID: {ch.get('id')}) — "
                f"{ch.get('num_members', 0)} members — {flag}"
            )
        if not member_only and result.get("response_metadata", {}).get("next_cursor"):
            lines.append("\n(More channels exist — increase limit to see them.)")
        return "\n".join(lines)
    except SlackApiError as e:
        return f"⚠️ List failed: {e.response['error']}"
    except Exception as e:
        return f"⚠️ List error: {e}"


@tool
async def lookup_slack_user(email: str) -> str:
    """Lookup user by email."""
    try:
        user = (await _get_client().users_lookupByEmail(email=email))["user"]
        return (
            f"User found:\n"
            f"Name: {user.get('real_name', 'Unknown')} (@{user.get('profile', {}).get('display_name')})\n"
            f"ID: {user['id']}\n"
            f"Admin: {user.get('is_admin', False)}"
        )
    except SlackApiError as e:
        return f"⚠️ User lookup failed: {e.response['error']}"
    except Exception as e:
        return f"⚠️ User lookup error: {e}"


# ── Export ───────────────────────────────────────────────────────────────────
SLACK_TOOLS = [
    send_slack_message,
    reply_to_slack_thread,
    send_slack_dm,
    get_slack_channel_history,
    get_slack_thread_replies,
    add_slack_reaction,
    list_slack_channels,
    lookup_slack_user,
]

__all__ = [
    "SLACK_TOOLS",
    "send_slack_message",
    "reply_to_slack_thread",
    "send_slack_dm",
    "get_slack_channel_history",
    "get_slack_thread_replies",
    "add_slack_reaction",
    "list_slack_channels",
    "lookup_slack_user",
]
