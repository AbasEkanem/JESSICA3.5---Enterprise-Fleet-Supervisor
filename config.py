"""
config.py — Centralised configuration for Jessica 3.5.
All tunable values are read from environment variables with sensible defaults.
"""
import os
import secrets
from dotenv import load_dotenv

import yaml
from pathlib import Path

load_dotenv()

# Load YAML configuration for structural harness boundaries
_yaml_path = Path(__file__).parent / "harness_config.yaml"
try:
    with open(_yaml_path, "r", encoding="utf-8") as f:
        _harness_config = yaml.safe_load(f) or {}
except FileNotFoundError:
    _harness_config = {}

def get_harness_cfg(section, key, default):
    return _harness_config.get(section, {}).get(key, default)

# ── Agent timeouts ────────────────────────────────────────────────────────────
RESEARCH_TIMEOUT_S      = int(os.getenv("RESEARCH_TIMEOUT_S",     get_harness_cfg("timeouts", "research_s", 360)))
CONVERSATION_TIMEOUT_S  = int(os.getenv("CONVERSATION_TIMEOUT_S", get_harness_cfg("timeouts", "conversation_s", 360)))
AGENT_HARD_TIMEOUT_S    = int(os.getenv("AGENT_HARD_TIMEOUT_S",   get_harness_cfg("timeouts", "agent_hard_s", 480)))
# recursion_limit bounds LangGraph SUPER-STEPS (node executions) for a single
# graph invocation — NOT user-visible "workflow steps". Jessica is a high-level
# orchestrator: one delegation to a subagent runs that subagent's ENTIRE
# model<->tool ReAct loop INLINE on the SAME budget (the pinned deepagents
# auto-propagates the parent's recursion_limit into subagents and they share the
# pool; a per-subagent limit in subagent.yaml is parsed but ignored). So a single
# multi-tool subagent easily burns 8-15 super-steps, so multi-step workflows
# need a generous budget. The real wall-clock bound is AGENT_HARD_TIMEOUT_S;
# recursion_limit is only an infinite-loop backstop. NOTE: harness_config.yaml
# is the operative source and sets limits.conversation_recursion=500 for this
# deployment; the 500 here is the standalone fallback if that YAML/env is absent.
CONVERSATION_RECURSION_LIMIT = int(os.getenv("CONVERSATION_RECURSION_LIMIT", get_harness_cfg("limits", "conversation_recursion", 500)))

# Background / subagent tasks (BackgroundTaskManager._execute_subagent) used to
# hardcode recursion_limit=40 — LOWER than the conversation budget, despite doing
# at least as much work (they re-plan from a cold synthetic prompt). That
# asymmetry is exactly what produced the observed background-path
# GraphRecursionError failures. Default to the conversation limit so background
# runs are never the starved path, while staying independently tunable.
BACKGROUND_RECURSION_LIMIT = int(os.getenv("BACKGROUND_RECURSION_LIMIT", get_harness_cfg("limits", "background_recursion", CONVERSATION_RECURSION_LIMIT)))

# Dynamic recursion budget (intent-routed) — see guardrails.router.recursion_budget_for.
# When Layer-2 routing (guardrails/router.py) classifies a turn as a CONFIDENT,
# SINGLE-DOMAIN request (one specific subagent, confidence >= threshold), the whole
# turn is bounded work: one subagent's inline ReAct loop (~8-15 super-steps, ~40-60
# worst case with retries) plus a little orchestration. It can never legitimately
# need the full 500, so it is handed this tighter FOCUSED budget — a right-sized
# drift detector that trips a runaway focused turn early WITHOUT risking real work.
# Fail-safe: anything the router marks "general" (its rules send BOTH trivial chat
# AND every multi-step / multi-domain workflow to "general"), any low-confidence
# classification, and every auto-resume turn keep the FULL CONVERSATION_RECURSION_LIMIT.
# The budget therefore only ever SHRINKS for a turn we are confident is small.
FOCUSED_RECURSION_LIMIT = int(os.getenv("FOCUSED_RECURSION_LIMIT", get_harness_cfg("limits", "focused_recursion", 1000)))

# ── Durability harness — Nemotron-3 progress budget (loop-breaker) ────────────
# Jessica's brain id comes from JESSICA_BRAIN_MODEL_ID (loadenv.py). The .env
# currently pins it to ultra-550b (its own comments say the intent was super-120b
# to dodge ultra's 503s — value and comments disagree; flagged to the operator).
# deepagents selects a harness profile by EXACT {provider}:{id} lookup, and the
# built-in Nemotron-3 harness is registered ONLY for ultra-550b:
#   * brain = ultra (current): the harness IS active, but with TIGHT per-turn caps
#     (16 / 48 / 3) — the loop-breaker returns a graceful "here's what I gathered"
#     partial answer and ENDS the turn early on a real multi-subagent workflow.
#   * brain = super (the .env's intent): matches nothing → EMPTY profile, no
#     loop-breaker / completion guard / nudges at all.
# jessica_harness.py registers ONE re-tuned profile under BOTH Nemotron-3 specs so
# durability holds either way, and RAISES these caps generously so graceful
# degradation fires only on a genuinely runaway turn — not on a normal long
# research -> doc -> email -> slack -> jira orchestration. The identical-repeat
# guard stays tight (a real stuck-loop signal). Layered ceilings: harness budget
# (graceful) < chat _MAX_STEPS (blunt) < recursion_limit=500 (hard crash backstop).
HARNESS_MAX_MODEL_CALLS         = int(os.getenv("HARNESS_MAX_MODEL_CALLS",         get_harness_cfg("limits", "harness_max_model_calls", 60)))
HARNESS_MAX_TOOL_RESULTS        = int(os.getenv("HARNESS_MAX_TOOL_RESULTS",        get_harness_cfg("limits", "harness_max_tool_results", 200)))
HARNESS_MAX_REPEATED_TOOL_CALLS = int(os.getenv("HARNESS_MAX_REPEATED_TOOL_CALLS", get_harness_cfg("limits", "harness_max_repeated_tool_calls", 4)))

# ── Concurrency — separate semaphores so chat is never starved by research ────
RESEARCH_SEMAPHORE_SIZE      = int(os.getenv("RESEARCH_SEMAPHORE_SIZE",      get_harness_cfg("concurrency", "research_semaphore_size", 5)))
CONVERSATION_SEMAPHORE_SIZE  = int(os.getenv("CONVERSATION_SEMAPHORE_SIZE", get_harness_cfg("concurrency", "conversation_semaphore_size", 20)))
MAX_CONCURRENT_AGENTS        = int(os.getenv("MAX_CONCURRENT_AGENTS",        get_harness_cfg("concurrency", "max_concurrent_agents", 20)))

# ── Background tasks (start_bg_task / BackgroundTaskManager) ──────────────────
# Background subagent runs execute OUTSIDE the /ask handler, so they bypass the
# research/conversation semaphores above. Two guards keep them from running away:
#   1. BACKGROUND_TASK_TIMEOUT_S — an inline per-task wall-clock cap on the
#      graph ainvoke(). Without it a hung background run would only be reaped by
#      the 2x-TTL cleanup sweep (48h), holding a Postgres connection the whole
#      time. Sized below AGENT_HARD_TIMEOUT_S is NOT required (background runs
#      have no live SSE client waiting), but 600s is a generous ceiling for deep
#      research / document generation while still bounding the leak.
#   2. MAX_CONCURRENT_BG_TASKS — a dedicated semaphore so a burst of background
#      tasks cannot exhaust the shared Postgres pool and starve live chat turns.
BACKGROUND_TASK_TIMEOUT_S = float(os.getenv("BACKGROUND_TASK_TIMEOUT_S", get_harness_cfg("timeouts", "background_task_s", 600.0)))
MAX_CONCURRENT_BG_TASKS   = int(os.getenv("MAX_CONCURRENT_BG_TASKS",   get_harness_cfg("concurrency", "max_concurrent_bg_tasks", 5)))


# ── Per-user rate limiting ─────────────────────────────────────────────────────
USER_RATE_LIMIT_PER_MINUTE = int(os.getenv("USER_RATE_LIMIT_PER_MINUTE", get_harness_cfg("limits", "user_rate_per_minute", 10)))

# ── SSE ───────────────────────────────────────────────────────────────────────
SSE_QUEUE_MAXSIZE       = int(os.getenv("SSE_QUEUE_MAXSIZE",        get_harness_cfg("sse", "queue_maxsize", 512)))
SSE_KEEPALIVE_S         = float(os.getenv("SSE_KEEPALIVE_S",         get_harness_cfg("sse", "keepalive_s", 15.0)))
SSE_TOKEN_PUT_TIMEOUT_S = float(os.getenv("SSE_TOKEN_PUT_TIMEOUT_S", get_harness_cfg("sse", "token_put_timeout_s", 2.0)))

# ── Greeting ─────────────────────────────────────────────────────────────────
GREETING_LLM_TIMEOUT_S = float(os.getenv("GREETING_LLM_TIMEOUT_S", get_harness_cfg("timeouts", "greeting_llm_s", 15.0)))
GREETING_CACHE_TTL     = int(os.getenv("GREETING_CACHE_TTL_S", get_harness_cfg("cache", "greeting_ttl_s", 300)))

# ── Upload ───────────────────────────────────────────────────────────────────
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES_MB", get_harness_cfg("limits", "max_upload_bytes_mb", 20))) * 1024 * 1024

# ── Post-response deadline ────────────────────────────────────────────────────
AGENT_POST_RESPONSE_DEADLINE_S = float(os.getenv("AGENT_POST_RESPONSE_DEADLINE_S", get_harness_cfg("timeouts", "agent_post_response_deadline_s", 15.0)))

# ── Thread-history response cache ─────────────────────────────────────────────
THREAD_HISTORY_CACHE_TTL_S   = float(os.getenv("THREAD_HISTORY_CACHE_TTL_S", get_harness_cfg("cache", "thread_history_ttl_s", 2.0)))
THREAD_HISTORY_CACHE_MAXSIZE = int(os.getenv("THREAD_HISTORY_CACHE_MAXSIZE", get_harness_cfg("cache", "thread_history_maxsize", 512)))

# ── Redis ────────────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL")  # None → in-process fallback

# ── Environment ──────────────────────────────────────────────────────────────
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()

# ── Google OAuth ─────────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

# SEC-02: SESSION_SECRET must be a stable, externally-provided value in
# production. If it is left unset, `secrets.token_hex(32)` generates a NEW
# random secret on every process restart, which silently invalidates every
# existing user session on each redeploy or worker respawn. In production this
# is a hard failure — fail fast at startup rather than degrade sessions
# unpredictably. In development we still allow the ephemeral fallback.
_session_secret_env = os.getenv("SESSION_SECRET")
if ENVIRONMENT == "production" and not _session_secret_env:
    raise RuntimeError(
        "SESSION_SECRET must be set in production. Without it a new random "
        "secret is generated per process restart, invalidating all existing "
        "sessions. Set the SESSION_SECRET environment variable."
    )
SESSION_SECRET = _session_secret_env or secrets.token_hex(32)

BACKEND_URL    = os.getenv("BACKEND_URL", "http://localhost:8000")

# ── NextAuth ─────────────────────────────────────────────────────────────────
# Must match NEXTAUTH_SECRET in ui/.env.local — used to decrypt session JWTs.
NEXTAUTH_SECRET = os.getenv("NEXTAUTH_SECRET", "")

# ── Human-in-the-loop: high-risk (irreversible / broad-exposure) tool gate ────
# SINGLE SOURCE OF TRUTH for which tools pause for explicit human approval. A
# tool in this set installs a LangGraph `interrupt()` (via create_deep_agent's
# `interrupt_on` in JESSICA3.5.py) BEFORE it executes, and chat.py surfaces it to
# the client as risk="high" (everything else that interrupts is "medium"). It is
# defined ONCE here and imported by BOTH JESSICA3.5.py (to build interrupt_on)
# and routes/chat.py (to tier the risk), so the enforcement point and the
# transport can never drift apart.
#
# Scope = IRREVERSIBLE side effects and BROAD external exposure only. Reversible
# actions (e.g. transition_jira_issue, create/update docs) are intentionally
# EXCLUDED so Jessica runs a long workflow to completion without over-pausing —
# she pauses only for a genuine point of no return, honoring "don't break the run
# except for human-in-the-loop".
HARD_RISK_TOOLS: frozenset[str] = frozenset({
    # outbound communication (cannot be un-sent)
    "send_research_email", "schedule_research_email",
    "send_slack_message", "send_slack_dm", "reply_to_slack_thread",
    # irreversible destructive ops
    "delete_drive_file", "trash_drive_file",
    "delete_calendar_event",
    "delete_course", "delete_coursework",
    # public / broad data exposure — same risk tier as deletion
    "share_drive_file_with_anyone", "bulk_share_drive_files",
})

