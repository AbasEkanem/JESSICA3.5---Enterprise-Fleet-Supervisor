"""
guardrails/router.py — Layer 2: LLM-based Intent Router.

Architecture (research-backed, LangChain 2025 production standard):
    Uses a dedicated small, fast routing model (step-3.7-flash via NVIDIA NIM)
    with Pydantic structured output (with_structured_output) to classify user
    intent into one of Jessica's 7 subagent categories BEFORE the main brain
    processes the request.

Why a routing model instead of just a prompt?
    Source: LangChain blog, Towards AI (2025):
    "Do NOT rely on the LLM to choose the right tool purely from a description.
    Use a smaller, faster router LLM or structured output to classify intent.
    This reduces main-brain context bloat, hallucinations, and wrong-subagent
    selection significantly."

    The router:
    - Runs in ~300–600ms (step-3.7-flash is fast and cheap)
    - Returns a structured RoutingDecision via with_structured_output()
    - Injects a routing HINT into the enriched message if confidence >= 0.70
    - Falls back silently if the router fails — main brain routes freely

Confidence threshold (0.70):
    Below this, no hint is injected. The main brain's prompt-based routing
    handles ambiguous queries. Above 0.70, the hint is a near-certainty.

Supervisors mapped (these MUST be the exact 4 domain-supervisor names the main
brain accepts — see subagent.yaml; leaf persona names like `jira_agent` or
merged names like `atlassian_agent` DO NOT EXIST and are rejected by the
`task` tool, so the router must never emit them):
    research_agent          → Scout  (web research, news, live data)
    comms_agent             → Relay  (Email + Slack)
    google_workspace_agent  → Gemma  (Drive, Docs, Sheets, Slides, Forms,
                                      Calendar, Classroom — structure & work)
    project_mgmt_agent      → Forge  (Jira + Confluence)
    general                 → (no hint — main brain handles freely)
"""

from __future__ import annotations

import asyncio
import time
from typing import Literal

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from config import CONVERSATION_RECURSION_LIMIT, FOCUSED_RECURSION_LIMIT

logger = structlog.get_logger(__name__)

# ── Routing confidence threshold ──────────────────────────────────────────────
_CONFIDENCE_THRESHOLD = 0.70

# ── Router timeout (must finish before main agent can begin) ──────────────────
# HIGH-04: raised 4.0 → 6.0. The router runs on a dense 128B model
# (mistral-medium-3.5) whose first-token latency under NVIDIA NIM load or
# cold-start can reach 2–6 s. At 4.0 s a cold router timed out and fell back to
# confidence=0.0 (no hint) on requests that would otherwise have routed cleanly.
# The caller's outer asyncio.wait_for in routes/chat.py must stay ABOVE this
# value (raised to 7.0 s there) so the router's own timeout fires first and its
# clean general-fallback path is used, rather than the caller cancelling it.
_ROUTER_TIMEOUT_S = 6.0


# ── Subagent type literal ─────────────────────────────────────────────────────
# MUST stay in exact sync with the 4 domain supervisor names the main brain accepts
# (see subagent.yaml and system_prompts.py SUBAGENTS table).
SubagentType = Literal[
    "google_workspace_agent",
    "comms_agent",
    "project_mgmt_agent",
    "research_agent",
    "general",
]


# ── Hint templates injected into the enriched message ────────────────────────
_HINTS: dict[str, str] = {
    "google_workspace_agent": "[ROUTING HINT: This request involves Google Workspace (Drive, Docs, Sheets, Slides, Forms, Calendar, Classroom structure & coursework). Delegate to google_workspace_agent (Gemma) via the task tool.]",
    "comms_agent":            "[ROUTING HINT: This request involves communications (Email or Slack). Delegate to comms_agent (Relay) via the task tool.]",
    "project_mgmt_agent":     "[ROUTING HINT: This request involves project management (Jira or Confluence). Delegate to project_mgmt_agent (Forge) via the task tool.]",
    "research_agent":         "[ROUTING HINT: This request requires web search, live data, or deep research. Delegate to research_agent (Scout) via the task tool.]",
}

# ── Routing system prompt ─────────────────────────────────────────────────────
_ROUTER_SYSTEM = """You are a routing classifier for Jessica 3.5, a supervisor of supervisors.
Jessica oversees 4 domain supervisors. Classify the user request into exactly one:

1. google_workspace_agent — Google Workspace and Classroom (Drive files/folders, Docs, Sheets, Slides, Forms, Calendar events, Classroom courses/rosters/topics, and coursework/grading/announcements)
2. comms_agent            — Communications (Email: reading, searching, drafting, sending, scheduling; Slack: messages, channels, threads, DMs, reactions)
3. project_mgmt_agent     — Project Management (Jira tickets, issues, sprints, boards, comments; Confluence pages, CQL search, documentation)
4. research_agent         — Web search, deep research, news, current events, live data, academic lookups, source verification

Return ONLY a JSON object with two fields:

- "subagent": the exact name of the best matching supervisor from the list above, or "general" if none applies
- "confidence": a float between 0.0 and 1.0

Rules:
- Use the EXACT names listed above: "google_workspace_agent", "comms_agent", "project_mgmt_agent", "research_agent", or "general".
- Return "general" if the request is a greeting, casual chat, math, coding help, or knowledge question with no tool dependency.
- Return "general" if the request involves MULTIPLE domain supervisors (e.g. Jira + Email, Research + Doc, Drive + Slack). Multi-domain workflows must let Jessica orchestrate freely.
- Return confidence >= 0.85 only when you are very certain.
- Return confidence < 0.70 when ambiguous — Jessica will handle routing freely.
"""



class RoutingDecision(BaseModel):
    """Structured output from the routing model."""
    subagent:   SubagentType = Field(description="The target subagent or 'general'")
    confidence: float        = Field(ge=0.0, le=1.0, description="Classification confidence 0.0–1.0")


# ── Router auto-disable (Fix #7: deterministic-failure hygiene) ───────────────
# A routing_model that is None (its build failed at boot) or that returns a
# DETERMINISTIC auth/config error (401/403 bad key, 404/410 retired model) can
# never succeed for the life of this process. Retrying it every turn spams
# router.error and burns a ~round-trip per turn — the exact pathology documented
# in the mistral-410 incident. On the first such failure we log ONCE and latch
# this flag; route_message then short-circuits to the safe "general" decision
# (main brain routes freely) for the rest of the process. TRANSIENT failures
# (timeout, 5xx, overload) never latch it — those are retried as before.
_ROUTER_DISABLED = False


def _safe_decision() -> RoutingDecision:
    """The fail-safe routing decision: no hint, so the main brain routes freely."""
    return RoutingDecision(subagent="general", confidence=0.0)


def _is_deterministic_router_error(exc: Exception) -> bool:
    """True for non-transient provider auth/config failures that will recur every
    turn (bad/absent key → 401/403, retired model → 404/410 Gone). Distinct from a
    transient blip (timeout/5xx), which SHOULD be retried next turn."""
    status = (
        getattr(exc, "status_code", None)
        or getattr(getattr(exc, "response", None), "status_code", None)
    )
    if status in (401, 403, 404, 410):
        return True
    msg = str(exc)
    return any(
        marker in msg
        for marker in ("[401]", "[403]", "[404]", "[410]", "Unauthorized", "Forbidden", "Gone")
    )


def _disable_router(reason: str, exc: Exception | None = None) -> None:
    """Latch the router off for the rest of the process and log the cause ONCE."""
    global _ROUTER_DISABLED
    if _ROUTER_DISABLED:
        return
    _ROUTER_DISABLED = True
    logger.error(
        "router.config_error",
        reason=reason,
        error=str(exc) if exc is not None else None,
        note="Intent router disabled for this process; main brain will route "
             "freely. Deterministic provider/config failure, not a transient blip.",
    )


async def route_message(
    message: str,
    user_email: str = "",
) -> RoutingDecision:
    """
    Classify a user message using the fast routing model.

    Returns a RoutingDecision. If confidence >= _CONFIDENCE_THRESHOLD,
    the caller should prepend _HINTS[subagent] to the enriched message.

    Fails safely: on any error, returns RoutingDecision(subagent="general", confidence=0.0)
    so the main brain routes freely.
    """
    log = logger.bind(user=user_email)
    t0  = time.perf_counter()

    # Fix #7: once the router has been proven unusable this process (see
    # _ROUTER_DISABLED), skip it entirely — no per-turn round-trip, no spam.
    if _ROUTER_DISABLED:
        return _safe_decision()

    # Lazy import to avoid circular dependency at module load
    from loadenv import routing_model  # type: ignore[import]

    # C1: a None routing_model (its build failed at boot) can never classify.
    # Latch the router off after logging once, then route freely.
    if routing_model is None:
        _disable_router("routing_model is None (build failed at startup)")
        return _safe_decision()

    try:
        router = routing_model.with_structured_output(RoutingDecision)
        decision: RoutingDecision = await asyncio.wait_for(
            router.ainvoke([
                SystemMessage(content=_ROUTER_SYSTEM),
                HumanMessage(content=message[:2000]),  # cap context for speed
            ]),
            timeout=_ROUTER_TIMEOUT_S,
        )
        elapsed_ms = round((time.perf_counter() - t0) * 1000)
        log.info(
            "router.classified",
            subagent=decision.subagent,
            confidence=round(decision.confidence, 2),
            elapsed_ms=elapsed_ms,
            hint_injected=decision.confidence >= _CONFIDENCE_THRESHOLD and decision.subagent != "general",
        )
        return decision

    except asyncio.TimeoutError:
        # Transient: a slow/cold router. Fail safe THIS turn but keep the router
        # enabled — the next turn may well succeed.
        log.warning("router.timeout", timeout_s=_ROUTER_TIMEOUT_S)
        return _safe_decision()
    except Exception as exc:
        # C2/C3: distinguish a DETERMINISTIC auth/config failure (recurs every
        # turn) from a transient blip. Deterministic → latch the router off and
        # log once (router.config_error); transient → warn and retry next turn.
        if _is_deterministic_router_error(exc):
            _disable_router("deterministic auth/config error", exc)
        else:
            log.warning("router.error", error=str(exc))
        return _safe_decision()


def get_routing_hint(decision: RoutingDecision) -> str:
    """
    Return the routing hint string to prepend to the enriched message,
    or an empty string if confidence is below threshold or subagent is general.
    """
    if decision.confidence < _CONFIDENCE_THRESHOLD:
        return ""
    if decision.subagent == "general":
        return ""
    return _HINTS.get(decision.subagent, "")


# ── Dynamic recursion budget (intent-routed) ─────────────────────────────────
# Never let a computed budget fall below this floor, even if FOCUSED_RECURSION_LIMIT
# is misconfigured — starving a run would violate Jessica's top-line "never break
# mid-workflow" contract. (The min() below still caps the result at the full limit.)
_RECURSION_FLOOR = 40


def recursion_budget_for(decision: RoutingDecision | None) -> int:
    """Map an intent-routing decision to a LangGraph ``recursion_limit`` for the turn.

    Policy — fail-safe by construction. The budget only ever SHRINKS for a turn we
    are confident is small; every uncertain or complex turn keeps the full budget:

    * ``None`` / router failed / ``confidence < _CONFIDENCE_THRESHOLD`` → FULL budget.
      (``route_message`` already returns ``confidence=0.0`` on timeout or error, and
      the caller passes ``None`` on auto-resume turns, which continue a live workflow.)
    * ``subagent == "general"`` → FULL budget. The router deliberately routes BOTH
      trivial chat AND any multi-step / multi-domain workflow to ``"general"`` (see
      ``_ROUTER_SYSTEM`` rules), so a ``"general"`` turn may be a large orchestration
      and must never be starved.
    * A confident, specific SINGLE-domain route → FOCUSED budget. One subagent's
      inline ReAct loop is bounded work (~8-15 super-steps, ~40-60 worst case), so
      FOCUSED (default 250) is many times that headroom yet trips a runaway well
      before the 500 hard wall.

    The result is clamped to ``[_RECURSION_FLOOR, CONVERSATION_RECURSION_LIMIT]`` so a
    misconfigured tier can neither starve a run nor exceed the hard backstop.
    """
    full = CONVERSATION_RECURSION_LIMIT
    if decision is None or decision.confidence < _CONFIDENCE_THRESHOLD:
        return full
    if decision.subagent == "general":
        return full
    # Confident, specific single-domain route → tighter, right-sized budget.
    return min(max(FOCUSED_RECURSION_LIMIT, _RECURSION_FLOOR), full)
