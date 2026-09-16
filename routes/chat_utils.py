"""
routes/chat_utils.py — Helper utilities, sanitizers, and status handlers for chat endpoint.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


# ── Pacific timezone 
_TZ_PT = ZoneInfo("America/Los_Angeles")


# ════════════════════════════════════════
# Gemini rate-limit retry parser --------
# ════════════════════════════════════════

_RETRY_DELAY_RE = re.compile(r"(\d+\.?\d*)\s*s")

def parse_gemini_retry(exc: Exception) -> float:
    """Extract exact retry delay (seconds) from a Gemini RESOURCE_EXHAUSTED error.

    Priority:
      1. retryDelay field in error details  (e.g. "30.343s" → 30.34)
      2. Retry-After HTTP header            (e.g. "60"     → 60)
      3. Daily quota detection              (→ seconds until midnight PT)
      4. Fallback                           (→ 60 s)
    """
    err_str = str(exc)

    # 1. Parse retryDelay from error body
    m = _RETRY_DELAY_RE.search(err_str)
    if m:
        return max(float(m.group(1)), 1.0)

    # 2. Check HTTP Retry-After header
    resp = getattr(exc, "response", None)
    if resp:
        hdr = None
        if hasattr(resp, "headers"):
            hdr = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
        if hdr:
            try:
                return max(float(hdr), 1.0)
            except ValueError:
                pass

    # 3. Daily quota exhaustion → calculate seconds to midnight Pacific Time
    if "PerDay" in err_str or "per_day" in err_str or "RPD" in err_str:
        now_pt      = datetime.now(_TZ_PT)
        midnight_pt = (now_pt + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return max((midnight_pt - now_pt).total_seconds(), 60.0)

    # 4. Fallback
    return 60.0


# ══════════════════════════════════════════════════════════════════════════════
# LaTeX sanitiser — normalises math/physics equation syntax for the UI renderer
# ══════════════════════════════════════════════════════════════════════════════

def sanitize_latex(text: str) -> str:
    if not text or ('\\' not in text and '$' not in text):
        return text
    text = re.sub(r'\\\[', '\n$$\n', text)
    text = re.sub(r'\\\]', '\n$$\n', text)
    text = re.sub(r'\\\(', '$', text)
    text = re.sub(r'\\\)', '$', text)
    text = re.sub(r'\[[\d.]+pt\]', '', text)

    def _balance(t: str) -> str:
        parts = t.split('$$')
        if len(parts) % 2 == 0:
            parts[-2] += '$' + parts[-1]
            parts = parts[:-1]
        return '$$'.join(parts)

    text = _balance(text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


# ══════════════════════════════════════════════════════════════════════════════
# User-message sanitizer — strips injected context so stored history reads clean
# ══════════════════════════════════════════════════════════════════════════════

# The `# Chat Context` header block injected by chat.py via
# prompts/chat_context_template.md, e.g.:
#
#   # Chat Context
#
#   **Current Time:** Thursday, July 30, 2026 - 11:45 AM
#   **Period:** Mid-morning coffee
#   **User:** Christoffel Ekanem
#
#   <actual user message>
#
# When a user reloads a thread or refreshes, the checkpoint returns this raw
# enriched message. We must strip the header (and any routing hint / legacy
# SYSTEM CONTEXT prefix) so only the original user text is shown.
_CHAT_CONTEXT_BLOCK_RE = re.compile(
    r"^\s*#\s*Chat Context\s*\n+"
    r"(?:\*\*[^\n]*\*\*[^\n]*\n)+"   # the **Current Time:** / **Period:** / **User:** lines
    r"\s*",
    re.IGNORECASE,
)
_ROUTING_HINT_RE  = re.compile(r"\[ROUTING HINT:[^\]]*\]\s*", re.IGNORECASE)
_SYSTEM_CONTEXT_RE = re.compile(r"^\s*\[SYSTEM CONTEXT:[^\]]*\]\s*", re.IGNORECASE)


def clean_user_message(content: str) -> str:
    """Remove injected context (chat-context header, routing hint, legacy
    SYSTEM CONTEXT prefix) so a stored user message displays exactly as typed."""
    if not content:
        return content
    cleaned = _SYSTEM_CONTEXT_RE.sub("", content)
    cleaned = _CHAT_CONTEXT_BLOCK_RE.sub("", cleaned)
    cleaned = _ROUTING_HINT_RE.sub("", cleaned)
    return cleaned.strip()



# Memory annotation helper — single call site eliminates duplication bug


def append_memory_notes(text: str, handler: "JessicaStatusHandler") -> str:
    if handler._has_read_memory:
        text += "\n\n> 🧠 **Successfully retrieved from memory**"
    if handler._has_saved_memory:
        text += "\n\n> 🧠 **Successfully saved to memory**"
    return text



# ══════════════════════════════════════════════════════════════════════════
# Empty-response recovery — used when the live stream produces no final text
# ══════════════════════════════════════════════════════════════════════════

# Tools whose results are internal scaffolding and should not be shown to the
# user as a "task completed" summary (filesystem, planning, pure reasoning).
_INTERNAL_TOOL_NAMES: frozenset[str] = frozenset({
    "think_tool",
    "write_todos",
    "ls",
    "glob",
    "grep",
    "read_file",
    "write_file",
    "edit_file",
    "execute",
    "manage_memory",
    "search_memory",
    "get_current_datetime",
    "calculate_future_datetime",
})

# Delegation / domain tools whose results are especially useful as a fallback
# reply when the parent model ends the turn with empty content.
_PRIORITY_TOOL_NAMES: frozenset[str] = frozenset({
    "task",
    "get_bg_result",
    "check_bg_task",
})

_JSON_TEXT_KEYS: tuple[str, ...] = (
    "content",
    "text",
    "result",
    "output",
    "message",
    "answer",
    "summary",
    "response",
    "body",
    "data",
    "findings",
    "report",
)


def extract_message_text(content) -> str:
    """Normalize AIMessage / ToolMessage content to plain text.

    Providers sometimes return ``content`` as a string, sometimes as a list of
    content blocks (``{"type": "text", "text": "..."}`` or objects with a
    ``.text`` attribute). Streaming and fallback both need the same extraction
    or short final replies after tool use are lost and the UI shows the
    generic "couldn't generate a response" message.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if isinstance(block, dict):
                btype = block.get("type")
                if btype in ("thinking", "reasoning", "reasoning_content"):
                    continue
                if "text" in block and block["text"]:
                    parts.append(str(block["text"]))
                continue
            # LangChain content-block objects
            btype = getattr(block, "type", None)
            if btype in ("thinking", "reasoning", "reasoning_content"):
                continue
            text = getattr(block, "text", None)
            if text:
                parts.append(str(text))
        return "".join(parts)
    return str(content)


def _strip_think_blocks(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


# deepagents' PatchToolCallsMiddleware (before_agent) injects synthetic
# ToolMessages for dangling / malformed tool calls left by a crashed or
# interrupted turn. Their content is internal scaffolding, NOT a user-facing
# answer, e.g.:
#   "Tool call {name} with id {id} was cancelled - another message came in
#    before it could be completed."
#   "Tool call {name} with id {id} could not be executed - arguments were
#    malformed or truncated."
# If the empty-response fallback surfaces these verbatim, the user sees a raw
# "send research email: Tool call ... was cancelled ..." string instead of a
# real reply. We must filter them wherever tool output is humanized.
_TOOL_SCAFFOLD_MARKERS: tuple[str, ...] = (
    "was cancelled - another message came in",
    "could not be executed - arguments were malformed",
)


def _is_dangling_tool_scaffold(text: str) -> bool:
    """True when *text* is deepagents' dangling/malformed tool-call scaffolding."""
    t = (text or "").strip()
    if t.startswith("Tool call did not complete"):
        return True
    if t.startswith("Tool call ") and any(m in t for m in _TOOL_SCAFFOLD_MARKERS):
        return True
    return False


def _looks_like_tool_call_json(text: str) -> bool:
    """True when *text* is leaked tool-call scaffolding, not a user answer."""

    s = (text or "").lstrip()
    if not s.startswith("{"):
        return False
    head = s[:240].lower()
    return any(
        key in head
        for key in (
            '"subagent_type"',
            "'subagent_type'",
            '"tool_name"',
            '"function_name"',
            '"tool_calls"',
            '"function_call"',
            '"name": "task"',
            '"name":"task"',
        )
    )


def _extract_text_from_json_value(value, *, depth: int = 0) -> str | None:
    """Pull user-facing text out of structured tool / subagent payloads."""
    if depth > 5 or value is None:
        return None

    if isinstance(value, str):
        clean = _strip_think_blocks(value)
        if clean and len(clean) > 1 and not _looks_like_tool_call_json(clean):
            return clean
        # Nested JSON string
        if clean.startswith("{") or clean.startswith("["):
            try:
                return _extract_text_from_json_value(json.loads(clean), depth=depth + 1)
            except (json.JSONDecodeError, TypeError):
                return clean if len(clean) > 1 else None
        return None

    if isinstance(value, (int, float, bool)):
        return str(value)

    if isinstance(value, list):
        if not value:
            return None
        # List of message-like dicts (LangGraph / deepagents task transcripts)
        if all(isinstance(item, dict) for item in value):
            for item in reversed(value):
                role = str(item.get("role") or item.get("type") or "").lower()
                # Skip pure tool-call AI turns
                if item.get("tool_calls"):
                    continue
                if role in ("tool", "function"):
                    got = _extract_text_from_json_value(
                        item.get("content", item.get("text")), depth=depth + 1
                    )
                    if got:
                        return got
                    continue
                if role in ("ai", "assistant", "model", "") or "content" in item or "text" in item:
                    got = _extract_text_from_json_value(
                        item.get("content", item.get("text")), depth=depth + 1
                    )
                    if got:
                        return got
            # Fall through: join any extractable fragments
        parts: list[str] = []
        for item in value:
            got = _extract_text_from_json_value(item, depth=depth + 1)
            if got:
                parts.append(got)
        if parts:
            return "\n".join(parts[-8:])
        return None

    if isinstance(value, dict):
        # Prefer explicit text-bearing keys first
        for key in _JSON_TEXT_KEYS:
            if key not in value or value[key] in (None, "", [], {}):
                continue
            got = _extract_text_from_json_value(value[key], depth=depth + 1)
            if got:
                return got
        # Common envelope: {"messages": [...]}
        if "messages" in value:
            got = _extract_text_from_json_value(value["messages"], depth=depth + 1)
            if got:
                return got
        # Jira-ish issue lists
        for key in ("issues", "results", "items", "values"):
            if key in value and isinstance(value[key], list) and value[key]:
                lines: list[str] = []
                for issue in value[key][:15]:
                    if isinstance(issue, str):
                        lines.append(f"• {issue}")
                        continue
                    if not isinstance(issue, dict):
                        continue
                    key_id = issue.get("key") or issue.get("id") or ""
                    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
                    summary = (
                        issue.get("summary")
                        or fields.get("summary")
                        or issue.get("title")
                        or ""
                    )
                    status = ""
                    st = fields.get("status") if fields else issue.get("status")
                    if isinstance(st, dict):
                        status = st.get("name") or ""
                    elif isinstance(st, str):
                        status = st
                    label = f"*{key_id}*" if key_id else "•"
                    status_bit = f" [{status}]" if status else ""
                    summary_bit = f" {summary}" if summary else ""
                    line = f"• {label}{status_bit}{summary_bit}".strip()
                    if line != "•":
                        lines.append(line)
                if lines:
                    return "\n".join(lines)
        # Last resort: single nested dict value that yields text
        for nested in value.values():
            if isinstance(nested, (dict, list, str)):
                got = _extract_text_from_json_value(nested, depth=depth + 1)
                if got and len(got) > 20:
                    return got
        return None

    # LangChain message objects
    if hasattr(value, "content"):
        if getattr(value, "tool_calls", None):
            return None
        return _extract_text_from_json_value(
            extract_message_text(getattr(value, "content", None)), depth=depth + 1
        )

    return None


def humanize_tool_result_text(raw) -> str | None:
    """Turn raw tool / subagent output into plain user-facing text, or None.

    Handles plain strings, content-block lists, and JSON envelopes from the
    ``task`` subagent tool (the common empty-parent-reply failure mode).
    """
    if raw is None:
        return None

    # Already structured
    if isinstance(raw, (dict, list)) and not isinstance(raw, str):
        got = _extract_text_from_json_value(raw)
        return got.strip() if got else None

    text = extract_message_text(raw).strip()
    if not text:
        return None
    # Drop deepagents' dangling/malformed tool-call scaffolding (and our own
    # synthetic "did not complete" filler) so it is never surfaced to the user
    # as if it were a real reply.
    if _is_dangling_tool_scaffold(text):
        return None


    text = _strip_think_blocks(text)
    if not text or len(text) <= 1:
        return None
    if _looks_like_tool_call_json(text):
        return None

    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            # Non-JSON that merely starts with a brace — keep if readable prose
            if len(text) > 40 and "\n" in text:
                return text
            return None
        got = _extract_text_from_json_value(parsed)
        return got.strip() if got else None

    return text


def _cap_tool_text(text: str, limit: int = 2500) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _format_tool_fallback_line(name: str, text: str) -> str:
    """Format one tool result for the empty-response fallback."""
    lower = text.lower()
    # task / subagent returns are already the full answer — no label noise
    if name in _PRIORITY_TOOL_NAMES or name.endswith("_agent"):
        return text
    if (
        "email delivered" in lower
        or text.startswith("✓")
        or text.startswith("✅")
        or text.startswith("•")
        or text.startswith("*")
        or "successfully" in lower
        or "delivered via" in lower
        or "created" in lower
        or "result:" in lower
        or "no issues" in lower
        or "no open issues" in lower
        or "no users found" in lower
    ):
        return text
    if "failed" in lower or "error" in lower or text.startswith("⚠️"):
        return text
    label = name.replace("_", " ").strip() or "tool"
    return f"**{label}:**\n{text}"


def _compose_tool_fallback(lines: list[str]) -> str | None:
    if not lines:
        return None
    recent = lines[-3:]
    if len(recent) == 1:
        body = recent[0]
        if (
            body.startswith("✓")
            or body.startswith("✅")
            or "Email delivered" in body
            or "delivered via" in body.lower()
        ):
            return f"Done — here's the result:\n\n{body}"
        # Subagent/task prose already reads as a full answer
        if body.startswith("•") or body.startswith("*") or len(body) > 180:
            return body
        return f"Done. Here's what completed:\n\n{body}"
    return "Done. Here's what completed:\n\n" + "\n\n".join(recent)


def recover_final_ai_text(messages: list) -> str | None:
    """Return the last non-empty final AI reply from *messages*, or None.

    Skips AIMessages that only issued tool calls (intermediate turns) and
    strips ``<think>`` blocks / leaked JSON tool-call structs.
    """
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        # Tool-call turns carry planning text, not the user-facing answer.
        if getattr(msg, "tool_calls", None):
            continue
        raw = extract_message_text(getattr(msg, "content", None)).strip()
        if not raw:
            continue
        clean = humanize_tool_result_text(raw) or _strip_think_blocks(raw)
        if not clean or len(clean) <= 1:
            continue
        if _looks_like_tool_call_json(clean):
            continue
        # Still reject bare JSON objects that humanize couldn't unpack
        if clean.startswith("{") and len(clean) < 40:
            continue
        return clean
    return None


def synthesize_response_from_tool_results(messages: list) -> str | None:
    """Build a user-facing summary from ToolMessages when the model left no final text.

    Common failure mode: email/Slack/Jira tools succeed (often inside a
    ``task`` subagent), the parent model ends the turn with empty content (or
    only reasoning), and the UI would otherwise show
    "I completed the task but couldn't generate a response."

    Also accepts plain ``(name, content)`` tuples so the live status handler
    can feed captured subagent tool outputs that never landed on the parent
    checkpoint as ToolMessages.
    """
    useful: list[str] = []
    priority: list[str] = []

    for msg in messages:
        if isinstance(msg, tuple) and len(msg) >= 2:
            name = (msg[0] or "tool").strip() or "tool"
            raw_content = msg[1]
        elif isinstance(msg, ToolMessage):
            name = (getattr(msg, "name", None) or "").strip() or "tool"
            raw_content = getattr(msg, "content", None)
        else:
            continue

        if name in _INTERNAL_TOOL_NAMES:
            continue

        text = humanize_tool_result_text(raw_content)
        if not text:
            continue

        # task / domain results can be long (issue lists); allow more room
        limit = 4000 if name in _PRIORITY_TOOL_NAMES or "jira" in name else 2500
        text = _cap_tool_text(text, limit)
        line = _format_tool_fallback_line(name, text)

        if name in _PRIORITY_TOOL_NAMES or "jira" in name or name.endswith("_agent"):
            priority.append(line)
        else:
            useful.append(line)

    # Prefer subagent/task/jira results — they are the actual user answer.
    ordered = priority or useful
    return _compose_tool_fallback(ordered)


def recover_turn_response(
    messages: list,
    *,
    captured_tool_outputs: list | None = None,
) -> str | None:
    """Best-effort user-facing reply for a turn that streamed no final text.

    Order:
      1. Last final AIMessage text from this turn
      2. Synthesized ToolMessage summary (incl. ``task`` / JSON unpacking)
      3. Live-captured tool outputs from JessicaStatusHandler (subagent tools)
    """
    text = recover_final_ai_text(messages)
    if text:
        return text
    text = synthesize_response_from_tool_results(messages)
    if text:
        return text
    if captured_tool_outputs:
        return synthesize_response_from_tool_results(captured_tool_outputs)
    return None


# ══════════════════════════════════════════════════════════════════════════
# Empty-turn nudge — last-resort re-ask when a reasoning-only turn emits no text
# ══════════════════════════════════════════════════════════════════════════

# Compact system prompt for the thinking-OFF fallback responder. It must NOT
# reason at length (that is exactly what produced the empty turn); it just
# answers the user directly and briefly.
_NUDGE_SYSTEM = (
    "You are Jessica, a helpful executive assistant. Answer the user's most "
    "recent message directly, warmly, and concisely in plain text. Do NOT think "
    "out loud, do NOT emit tool calls or JSON, and do NOT explain your reasoning "
    "— just give the reply itself. If the message asks for an action or live "
    "information you would normally use a tool for (web search, current prices, "
    "the date or time, email, scheduling, etc.), do NOT claim you are unable to "
    "do it — you can; this is only a brief fallback reply. Instead, say you hit "
    "a momentary glitch and ask the user to send the request once more."
)


async def nudge_final_response(model, user_text: str, *, timeout_s: float = 20.0) -> str | None:
    """Re-ask a thinking-OFF model for a plain final reply, or return None.

    Root cause this addresses: the orchestrator brain runs with native thinking
    ON, so on a trivial prompt (e.g. "hi") it can spend the whole turn inside
    reasoning and end with EMPTY visible content. The streaming loop drops
    reasoning by design, so nothing reaches the user and the generic
    "couldn't generate a response" fallback fires.

    When that happens, chat.py calls this helper ONCE with a cheap,
    thinking-disabled model (loadenv.fallback_responder_model). We deliberately
    do NOT attach tools or history — this is a plain conversational completion,
    so it cannot loop, delegate, or re-enter the empty-reasoning state. Any
    failure (model is None, timeout, provider error, empty/scaffold output)
    returns None so the caller falls back to the original generic string —
    i.e. strictly no worse than before.
    """
    if model is None:
        return None
    text = (user_text or "").strip()
    if not text:
        return None
    try:
        result = await asyncio.wait_for(
            model.ainvoke(
                [
                    SystemMessage(content=_NUDGE_SYSTEM),
                    HumanMessage(content=text[:4000]),
                ]
            ),
            timeout=timeout_s,
        )
    except Exception:
        return None

    raw = extract_message_text(getattr(result, "content", None)).strip()
    if not raw:
        return None
    clean = _strip_think_blocks(raw)
    if not clean or len(clean) <= 1:
        return None
    # Never surface leaked tool-call JSON or dangling scaffolding as the answer.
    if _looks_like_tool_call_json(clean) or _is_dangling_tool_scaffold(clean):
        return None
    return clean


# Conversation-history sanitizer — closes dangling tool calls before next turn


def sanitize_trailing_tool_calls(messages: list) -> list:

    """
    Detect and close dangling tool calls at the tail of a message list.

    When a turn is aborted mid-flight (timeout, client disconnect, or the
    block-response race), an AIMessage with `tool_calls` can be persisted
    to the checkpoint with no matching ToolMessage. The next turn then
    sends a malformed role-sequence to the model, causing a 400 /
    role-sequence-error on the API side.

    Fix: append a synthetic ToolMessage for every unresolved tool_call_id
    so the checkpoint is always in a closed state before a new turn starts.
    Called at the end of every _run_agent() execution, not just error paths.
    """
    if not messages:
        return messages

    last = messages[-1]
    if not (isinstance(last, AIMessage) and getattr(last, "tool_calls", None)):
        return messages

    responded_ids: set[str] = {
        m.tool_call_id
        for m in messages
        if isinstance(m, ToolMessage) and hasattr(m, "tool_call_id")
    }
    unresolved = [
        tc for tc in last.tool_calls
        if tc.get("id") and tc["id"] not in responded_ids
    ]
    if unresolved:
        messages = list(messages)
        for tc in unresolved:
            messages.append(ToolMessage(
                tool_call_id=tc["id"],
                content="Tool call did not complete — turn ended before the tool responded.",
            ))
    return messages



# SSE Status Handler


class JessicaStatusHandler(AsyncCallbackHandler):
    """
    Streams live agent activity to the UI as SSE `status` events.

    Every event carries a stable `id` (the LangChain run_id) plus a `done`
    flag so the client can render an in-progress row (spinner) on
    ``on_tool_start`` and flip it to a checkmark on ``on_tool_end`` — the same
    real-time tool/subagent/memory feed you see in Claude's UI.

    Callbacks propagate into subagent runs, so tools invoked *inside* a
    delegated subagent (e.g. `send_research_email` inside the Email Agent)
    surface here too.
    """

    # ── Web-search tools (get a dedicated "searching" phase + globe icon) ──────
    _SEARCH_TOOLS   = {
        "tavily_search", "exa_search", "linkup_search",
        "serper_dev_search", "serpapi_search_tool", "ddgs_search_tool",
        "exa_search_tool", "linkup_search_tool",
    }
    _SEARCH_LABELS  = {
        "tavily_search":       "Searching with Tavily…",
        "exa_search":          "Searching with Exa…",
        "linkup_search":       "Searching with Linkup…",
    }

    # ── The 4 domain supervisors (friendly display names for the delegation row) ──
    _SUBAGENT_LABELS = {

        "research_agent":         "Research Supervisor",
        "comms_agent":            "Comms Supervisor",
        "google_workspace_agent": "Workspace Supervisor",
        "project_mgmt_agent":     "PM Supervisor",
    }


    _THINK_TOOLS = {"think_tool", "deep_reflection_tool"}

    # ── Background task lifecycle tools (in-process async pattern) 
    _ASYNC_LIFECYCLE_TOOLS = {
        "start_bg_task":   "Launching background task…",
        "check_bg_task":   "Checking background task status…",
        "get_bg_result":   "Retrieving background task result…",
        "cancel_bg_task":  "Canceling background task…",
    }

    # ── snake_case tool-name → gerund verb, for humanized generic-tool labels ──
    _VERB_MAP = {
        "create": "Creating",   "get": "Fetching",       "list": "Listing",
        "search": "Searching",  "update": "Updating",    "delete": "Deleting",
        "send": "Sending",      "read": "Reading",       "add": "Adding",
        "share": "Sharing",     "grade": "Grading",      "publish": "Publishing",
        "move": "Moving",       "rename": "Renaming",    "upload": "Uploading",
        "download": "Downloading", "export": "Exporting", "append": "Adding",
        "insert": "Inserting",  "replace": "Replacing",  "style": "Styling",
        "format": "Formatting", "clear": "Clearing",     "transition": "Updating",
        "assign": "Assigning",  "respond": "Responding", "check": "Checking",
        "revoke": "Revoking",   "trash": "Trashing",     "duplicate": "Duplicating",
        "reorder": "Reordering", "embed": "Embedding",   "refresh": "Refreshing",
        "cancel": "Canceling",  "return": "Returning",   "invite": "Inviting",
        "remove": "Removing",   "write": "Writing",      "schedule": "Scheduling",
        "lookup": "Looking up", "reply": "Replying",     "batch": "Reading",
        "revoke_drive": "Revoking",
    }

    def __init__(self, queue: asyncio.Queue) -> None:
        super().__init__()
        self._q                = queue
        self._has_thought      = False
        self._has_saved_memory = False
        self._has_read_memory  = False
        self._active_tools: dict[str, str] = {}
        self._used_research = False  # set when task(web_searcher) is invoked

        # BUG-FIX (empty-response after subagent crash): live-captured
        # (name, output) pairs for every tool/subagent call that actually
        # completed, in call order. This is the tier-3 recovery source for
        # recover_turn_response(). It exists because a subagent invoked via
        # the `task` tool can still be cancelled (see GraphRecursionError
        # handling in chat.py): on the pinned deepagents (>=0.7.5) subagents
        # inherit the parent's recursion_limit (CONVERSATION_RECURSION_LIMIT,
        # ~50) rather than the old bare-25 default (deepagents#1698, which only
        # affected <0.7.0), but a genuinely long-running subagent such as
        # web_searcher can still exhaust even that budget and get
        # asyncio.Task.cancel()'d.
        # When that happens the parent checkpoint often ends up with NO

        # final AIMessage text and NO usable ToolMessage for the `task`
        # call, so recover_final_ai_text() and synthesize_response_from_tool_results()
        # both return None even though real work (e.g. several completed
        # web searches) already happened. This buffer lets us fall back to
        # that real work instead of the generic error string.
        self._captured_tool_outputs: list[tuple[str, object]] = []

    @classmethod
    def _humanize_tool(cls, name: str) -> str:
        """Turn a snake_case tool name into a live status label.

        e.g. ``create_jira_issue`` → "Creating jira issue…",
             ``send_slack_message`` → "Sending slack message…".
        """
        words = name.replace("_", " ").split()
        if not words:
            return "Working…"
        verb = words[0]
        if verb in cls._VERB_MAP:
            rest = " ".join(words[1:]).strip()
            return f"{cls._VERB_MAP[verb]} {rest}".strip() + "…"
        return "Using " + " ".join(words) + "…"

    @staticmethod
    def _parse_todos(raw) -> list[dict]:
        """Normalize a ``write_todos`` tool input into a ``[{description, status}]``
        checklist for the ``todo`` SSE event.

        The deepagents / LangChain ``TodoListMiddleware`` calls
        ``write_todos(todos=[{"content": str, "status": "pending"|"in_progress"|
        "completed"}, …])`` and REPLACES the whole list each call, so every event
        carries the complete, freshly-updated plan — ideal for a checklist that
        updates in place. We accept the value as a dict, a JSON string, or a bare
        list, tolerate both ``content``/``description`` and ``status``/
        ``task_status`` key spellings, and clamp status to the three canonical
        values the UI's ``TodoTask`` type expects (hyphen → underscore).
        """
        data = raw
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError, ValueError):
                return []
        if isinstance(data, dict):
            items = data.get("todos", data.get("todo", []))
        elif isinstance(data, list):
            items = data
        else:
            return []
        if not isinstance(items, list):
            return []

        todos: list[dict] = []
        for item in items:
            if isinstance(item, dict):
                desc = (
                    item.get("content")
                    or item.get("description")
                    or item.get("task_description")
                    or ""
                )
                status = item.get("status") or item.get("task_status") or "pending"
            elif isinstance(item, str):
                desc, status = item, "pending"
            else:
                continue
            desc = str(desc).strip()
            if not desc:
                continue
            status = str(status).strip().lower().replace("-", "_")
            if status not in ("pending", "in_progress", "completed"):
                status = "pending"
            todos.append({"description": desc, "status": status})
        return todos

    async def _emit(
        self,
        phase: str,
        detail: str,
        tool: str = "",
        *,
        id: str = "",
        done: bool = False,
    ) -> None:
        p: dict = {"phase": phase, "detail": detail, "done": done}
        if tool:
            p["tool"] = tool
        if id:
            p["id"] = id
        await self._q.put(f"data: {json.dumps({'type': 'status', 'data': p})}\n\n")

    async def on_llm_start(self, serialized, prompts, *, run_id, **kwargs) -> None:
        if not self._has_thought:
            self._has_thought = True
            await self._emit("thinking", "Thinking…")

    async def on_tool_start(self, serialized, input_str, *, run_id, **kwargs) -> None:
        name  = (serialized or {}).get("name", "")
        rid   = str(run_id)
        lname = name.lower()
        self._active_tools[rid] = name

        # ── Memory tools
        if "memory" in lname:
            if "search" in lname or "read" in lname or "get" in lname:
                self._has_read_memory = True
                await self._emit("memory", "Searching memory…", tool=name, id=rid)
            else:
                self._has_saved_memory = True
                await self._emit("memory", "Saving to memory…", tool=name, id=rid)
            return

        # ── Plan scratchpad (`write_todos`) — stream the live todo checklist ──
        # Jessica calls write_todos to lay out (and later tick off) her plan. The
        # tool input carries the WHOLE current plan on every call, so each event
        # is a complete, freshly-updated checklist the UI can render in place —
        # this is the "stream the plan / update the todo list each step" feed.
        # We still keep write_todos in _INTERNAL_TOOL_NAMES so its raw JSON is
        # never used as an empty-response fallback reply; this only STREAMS it.
        if name == "write_todos":
            todos = self._parse_todos(input_str) or self._parse_todos(kwargs.get("inputs"))
            if todos:
                await self._q.put(
                    f"data: {json.dumps({'type': 'todo', 'data': todos})}\n\n"
                )
            # Compact activity-feed row so planning is visible alongside the plan.
            await self._emit("writing", "Planning the steps…", tool=name, id=rid)
            return

        # ── Subagent delegation (`task` tool)
        if name == "task":
            subagent = ""
            if isinstance(input_str, dict):
                subagent = input_str.get(
                    "subagent_type", input_str.get("agent", input_str.get("name", ""))
                )
            elif isinstance(input_str, str):
                try:
                    parsed   = json.loads(input_str)
                    subagent = parsed.get(
                        "subagent_type", parsed.get("agent", parsed.get("name", ""))
                    )
                except (json.JSONDecodeError, AttributeError):
                    for k in self._SUBAGENT_LABELS:
                        if k in input_str.lower():
                            subagent = k
                            break
            if subagent in ("research_agent", "web_searcher"):
                self._used_research = True
            friendly = self._SUBAGENT_LABELS.get(subagent, "Sub-agent")
            await self._emit(
                "subagent", f"{friendly} is working…",
                tool=(subagent or "subagent"), id=rid,
            )
            return

        # ── Web-search tools 
        if name in self._SEARCH_TOOLS:
            await self._emit(
                "searching", self._SEARCH_LABELS.get(name, "Searching the web…"),
                tool=name, id=rid,
            )
            return

        # ── Reflection / thinking tools 
        if name in self._THINK_TOOLS:
            await self._emit("thinking", "Reflecting on strategy…", tool=name, id=rid)
            return

        # ── Async subagent lifecycle tools
        if name in self._ASYNC_LIFECYCLE_TOOLS:
            await self._emit(
                "async_task",
                self._ASYNC_LIFECYCLE_TOOLS[name],
                tool=name,
                id=rid,
            )
            return

        # ── Every other tool (Jira, Drive, Docs, Sheets, Slides, Forms,
        #    Calendar, Slack, Classroom, …) — surface it live so nothing is
        #    silent in the UI.
        await self._emit("tool", self._humanize_tool(name), tool=name, id=rid)

    async def on_tool_end(self, output, *, run_id, **kwargs) -> None:
        rid  = str(run_id)
        name = self._active_tools.pop(rid, "")

        # Flip the in-progress row to done (client merges by id).
        if name:
            await self._emit("tool_done", "", tool=name, id=rid, done=True)

        # BUG-FIX (empty-response after subagent crash): record every
        # completed tool/subagent output as it lands, live, regardless of
        # whether the parent graph's checkpoint ever gets a matching
        # ToolMessage. If a sibling subagent (or the parent turn itself) is
        # later cancelled by a recursion-limit crash elsewhere in the run,
        # this is the only place the completed work still exists — see
        # __init__ docstring on _captured_tool_outputs for the full story.
        if name and name not in _INTERNAL_TOOL_NAMES:
            self._captured_tool_outputs.append((name, output))

    async def on_tool_error(self, error: BaseException, *, run_id, **kwargs) -> None:
        """Flip an in-flight status row to failed instead of leaving it
        spinning forever, and surface a clear reason when a subagent was
        killed by exhausting its step budget (GraphRecursionError) — i.e. the
        subagent hit the recursion_limit it inherited from the parent
        (CONVERSATION_RECURSION_LIMIT, ~50 on the pinned deepagents >=0.7.5)
        rather than a generic tool failure. (The old bare-25 subagent cap of
        deepagents#1698 only applied to <0.7.0.)
        """

        rid  = str(run_id)
        name = self._active_tools.pop(rid, "")
        if not name:
            return
        is_recursion_limit = "GraphRecursionError" in type(error).__name__ or isinstance(
            error, asyncio.CancelledError
        )
        detail = (
            "Research step hit an internal step limit and was stopped."
            if is_recursion_limit
            else f"{name.replace('_', ' ')} failed."
        )
        await self._emit("tool_done", detail, tool=name, id=rid, done=True)