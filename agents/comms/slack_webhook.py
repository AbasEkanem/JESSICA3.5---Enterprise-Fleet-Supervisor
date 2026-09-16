"""
agents/comms/slack_webhook.py
=============================
Production Slack event listener + Human-in-the-Loop approval for Jessica 3.5.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from pydantic import BaseModel

logger = structlog.get_logger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
APPROVAL_CHANNEL = os.getenv("SLACK_APPROVAL_CHANNEL", "")

# Explicit opt-in required to bypass approval (fail-closed by default)
ALLOW_AUTO_SEND_WITHOUT_APPROVAL = os.getenv(
    "SLACK_ALLOW_AUTO_SEND_WITHOUT_APPROVAL", "false"
).lower() == "true"

DEDUPE_TTL = 3600      # 1 hour
APPROVAL_TTL = 600     # 10 minutes
RETRY_WINDOW = 300     # 5 minutes

# ── Lazy singletons ──────────────────────────────────────────────────────────
_redis: aioredis.Redis | None = None
_http_client: httpx.AsyncClient | None = None


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379"),
            decode_responses=True,
        )
    return _redis


async def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=10)
    return _http_client


async def _slack_post(method: str, payload: dict) -> dict:
    client = await _get_http_client()
    resp = await client.post(
        f"https://slack.com/api/{method}",
        headers={
            "Authorization": f"Bearer {BOT_TOKEN}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json=payload,
    )
    data = resp.json()
    if not data.get("ok"):
        logger.warning("slack.api_failed", method=method, error=data.get("error"))
    return data


# ── Signature Verification ───────────────────────────────────────────────────
def _verify_signature(body: bytes, timestamp: str | None, signature: str | None) -> None:
    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Missing Slack signature headers")
    if abs(int(time.time()) - int(timestamp)) > RETRY_WINDOW:
        raise HTTPException(status_code=401, detail="Stale Slack request")
    basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    digest = hmac.new(
        SIGNING_SECRET.encode("utf-8"),
        basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    expected = f"v0={digest}"
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")


# ── Deduplication ────────────────────────────────────────────────────────────
def _dedupe_key(event_id: str) -> str:
    return f"jessica:slack:event:{event_id}"


async def _dedupe(event_id: str) -> bool:
    """Return True if this is a new event."""
    r = await _get_redis()
    key = _dedupe_key(event_id)
    return bool(await r.set(key, "1", nx=True, ex=DEDUPE_TTL))


async def _release_dedupe(event_id: str) -> None:
    """Release dedup claim on failure so retries can succeed."""
    try:
        r = await _get_redis()
        await r.delete(_dedupe_key(event_id))
        logger.info("slack.dedupe_released", event_id=event_id)
    except Exception as exc:
        logger.error("slack.dedupe_release_failed", event_id=event_id, error=str(exc))


# ── Models ───────────────────────────────────────────────────────────────────
class SlackEventEnvelope(BaseModel):
    type: str
    event_id: str | None = None
    event_time: int | None = None
    challenge: str | None = None
    event: dict[str, Any] | None = None


@dataclass(frozen=True)
class SlackEvent:
    event_id: str
    event_type: str
    channel_id: str
    user_id: str | None
    text: str
    ts: str
    thread_ts: str | None
    raw: dict[str, Any]


def _normalise(envelope: SlackEventEnvelope) -> SlackEvent:
    if not envelope.event_id:
        raise HTTPException(400, "Missing event_id")
    ev = envelope.event or {}
    return SlackEvent(
        event_id=envelope.event_id,
        event_type=ev.get("type", envelope.type),
        channel_id=ev.get("channel", ""),
        user_id=ev.get("user"),
        text=ev.get("text", "").strip(),
        ts=ev.get("ts", ""),
        thread_ts=ev.get("thread_ts"),
        raw=envelope.model_dump(),
    )


def _should_ignore(event: SlackEvent) -> bool:
    if not event.text or event.user_id is None or event.event_type == "bot_message":
        return True
    return False


# ── Core Approval Flow ───────────────────────────────────────────────────────
async def _draft_and_request_approval(event: SlackEvent, app_state: Any) -> None:
    try:
        await _draft_and_request_approval_inner(event, app_state)
    except Exception as exc:
        logger.error("slack.unhandled_error", event_id=event.event_id, exc_info=True)
        await _release_dedupe(event.event_id)


async def _draft_and_request_approval_inner(event: SlackEvent, app_state: Any) -> None:
    agent = getattr(app_state, "conversation_agent", None)
    if not agent:
        logger.warning("slack.agent_not_ready", event_id=event.event_id)
        await _release_dedupe(event.event_id)
        return

    prompt = (
        f"[SLACK MESSAGE FROM <@{event.user_id}> IN #{event.channel_id}]\n"
        f"{event.text}\n\n"
        "Draft a concise, professional Slack reply. Use Slack markdown. "
        "Reply ONLY with the reply text — no preamble."
    )

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": prompt}]},
        config={"configurable": {"thread_id": f"slack-{event.channel_id}-{event.ts}"}},
    )

    messages = result.get("messages", [])
    draft = next((m.content for m in reversed(messages) if getattr(m, "content", None)), None)

    if not draft:
        logger.warning("slack.no_draft", event_id=event.event_id)
        await _release_dedupe(event.event_id)
        return

    # Store pending approval
    action_id = f"jessica-approve-{event.event_id}"
    reject_id = f"jessica-reject-{event.event_id}"
    pending = {
        "draft": draft,
        "channel_id": event.channel_id,
        "thread_ts": event.thread_ts or event.ts,
        "user_id": event.user_id,
    }

    r = await _get_redis()
    await r.set(f"jessica:pending:{action_id}", json.dumps(pending), ex=APPROVAL_TTL)

    # Approval flow
    if not APPROVAL_CHANNEL:
        if not ALLOW_AUTO_SEND_WITHOUT_APPROVAL:
            logger.error("slack.approval_channel_missing", event_id=event.event_id)
            return
        logger.warning("slack.auto_send_enabled", event_id=event.event_id)
        await _slack_post("chat.postMessage", {
            "channel": event.channel_id,
            "text": draft,
            "thread_ts": event.thread_ts or event.ts,
        })
        return

    # Post approval card
    original_link = f"https://slack.com/archives/{event.channel_id}/p{event.ts.replace('.', '')}"
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "📬 Slack Reply Approval Request"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Channel:* <#{event.channel_id}>\n*From:* <@{event.user_id}>\n*Original Message:* <{original_link}|View in Slack>",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"> {event.text[:500]}",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Proposed Reply:*\n{draft}",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve & Send"},
                    "style": "primary",
                    "action_id": action_id,
                    "value": event.event_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "style": "danger",
                    "action_id": reject_id,
                    "value": action_id,
                },
            ],
        },
    ]

    await _slack_post("chat.postMessage", {
        "channel": APPROVAL_CHANNEL,
        "text": f"Jessica wants to reply to <@{event.user_id}>",
        "blocks": blocks,
    })
    logger.info("slack.approval_card_posted", event_id=event.event_id)


# ── Router ───────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/slack", tags=["slack"])


@router.post("/events")
async def slack_events(
    request: Request,
    background_tasks: BackgroundTasks,
    x_slack_signature: str | None = Header(default=None, alias="X-Slack-Signature"),
    x_slack_request_timestamp: str | None = Header(default=None, alias="X-Slack-Request-Timestamp"),
    x_slack_retry_num: str | None = Header(default=None, alias="X-Slack-Retry-Num"),
):
    raw_body = await request.body()
    _verify_signature(raw_body, x_slack_request_timestamp, x_slack_signature)

    envelope = SlackEventEnvelope.model_validate_json(raw_body)

    if envelope.type == "url_verification" and envelope.challenge:
        return {"challenge": envelope.challenge}

    if envelope.type != "event_callback":
        return {"ok": True}

    event = _normalise(envelope)

    if not await _dedupe(event.event_id):
        logger.debug("slack.duplicate_event", event_id=event.event_id)
        return {"ok": True}

    if x_slack_retry_num is not None:
        return {"ok": True}

    if _should_ignore(event):
        return {"ok": True}

    background_tasks.add_task(_draft_and_request_approval, event, request.app.state)
    return {"ok": True}


@router.post("/interactions")
async def slack_interactions(
    request: Request,
    x_slack_signature: str | None = Header(default=None, alias="X-Slack-Signature"),
    x_slack_request_timestamp: str | None = Header(default=None, alias="X-Slack-Request-Timestamp"),
):
    raw_body = await request.body()
    _verify_signature(raw_body, x_slack_request_timestamp, x_slack_signature)

    form = await request.form()
    payload = json.loads(form.get("payload", "{}"))
    actions = payload.get("actions", [])

    if not actions:
        return {"ok": True}

    action = actions[0]
    action_id = action.get("action_id", "")
    value = action.get("value", "")

    r = await _get_redis()

    if action_id.startswith("jessica-approve-"):
        key = f"jessica:pending:{action_id}"
        raw = await r.get(key)
        if not raw:
            return {"ok": True}
        pending = json.loads(raw)
        await r.delete(key)

        await _slack_post("chat.postMessage", {
            "channel": pending["channel_id"],
            "text": pending["draft"],
            "thread_ts": pending["thread_ts"],
        })

        await _update_approval_card(payload, "✅ Approved — reply sent.", approved=True)

    elif action_id.startswith("jessica-reject-"):
        approve_key = f"jessica:pending:{value}"
        await r.delete(approve_key)
        await _update_approval_card(payload, "❌ Rejected — reply discarded.", approved=False)

    return {"ok": True}


async def _update_approval_card(payload: dict, status_text: str, approved: bool):
    channel = payload.get("channel", {}).get("id")
    ts = payload.get("message", {}).get("ts")
    if not channel or not ts:
        return

    color = "#2eb886" if approved else "#e01e5a"
    approver = payload.get("user", {}).get("name", "someone")

    await _slack_post("chat.update", {
        "channel": channel,
        "ts": ts,
        "text": status_text,
        "blocks": [{
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{status_text}*\n_by @{approver}_"}
        }],
        "attachments": [{"color": color}],
    })
