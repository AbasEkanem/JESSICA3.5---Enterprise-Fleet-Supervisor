"""
loadenv.py — Environment bootstrap for Jessica 3.5.

Exports:
    routing_model    — stepfun-ai/step-3.7-flash  (Layer 2 intent router)

    # Dedicated subagent instances
    jira_agent_model, confluence_agent_model, email_agent_model,
    slack_agent_model, web_searcher_model, drive_agent_model,
    docs_agent_model, slides_agent_model, sheets_agent_model,
    forms_agent_model, calendar_agent_model, google_classroom_agent_model,
    juliet_agent_model

Observability:
    LangSmith tracing is bootstrapped here via LANGCHAIN_TRACING_V2,
    LANGCHAIN_API_KEY, and LANGCHAIN_PROJECT environment variables.
"""

from __future__ import annotations

import os
import time
from typing import Any

import structlog
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_openrouter import ChatOpenRouter

load_dotenv()

logger = structlog.get_logger(__name__)


# ── LangSmith Observability 
_tracing_enabled = os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true"
_langsmith_key   = os.getenv("LANGCHAIN_API_KEY", "")
_langsmith_proj  = os.getenv("LANGCHAIN_PROJECT", "jessica-default")

# OBS-01: expose the effective tracing state as a module-level flag so the
# /health endpoint can surface it. A passive warning in a log file is easy to
# miss on deploy; making tracing visibility part of the health payload means an
# operator (or an uptime check) can detect that a deployment went live with no
# trace coverage.
LANGSMITH_TRACING_ENABLED: bool = bool(_tracing_enabled and _langsmith_key)

if LANGSMITH_TRACING_ENABLED:
    logger.info(
        "langsmith.tracing_enabled",
        project=_langsmith_proj,
    )
else:
    logger.warning(
        "langsmith.tracing_disabled",
        reason="LANGCHAIN_TRACING_V2 or LANGCHAIN_API_KEY not set — "
               "set both in .env to enable LangSmith trace visibility",
    )



# ── API Key resolution ────────────────────────────────────────────────────────
jessica_brain_api_key = os.getenv("JESSICA_BRAIN_API_KEY")
research_api_key      = os.getenv("RESEARCH_MODEL_API_KEY")
# ── Key Isolation Tracking ────────────────────────────────────────────────────
_REGISTERED_KEYS: dict[str, str] = {}


# ── Helper for ChatNVIDIA model construction 
# Fixed decode seed. Combined with low temperature this makes tool-call
# generation deterministic and reproducible, which is a major reliability win:
# the model emits the same well-formed structured tool call for the same input
# instead of occasionally sampling a malformed one that LangChain files under
# `invalid_tool_calls`.
_DEFAULT_SEED = int(os.getenv("JESSICA_MODEL_SEED", "42"))

# RELIABILITY: hosted NIM endpoints intermittently return HTTP 429 (Too Many
# Requests) and transient 5xx/connection resets under load or cold start. This
# default is used ONLY for providers that expose a real client-side
# `max_retries` field (e.g. ChatGoogleGenerativeAI, which maps it to
# HttpRetryOptions).
#
# BUG-01: it must NOT be passed to ChatNVIDIA. ChatNVIDIA declares no
# `max_retries` field, so LangChain's `_build_model_kwargs` silently funnels the
# unknown kwarg into `model_kwargs`, and ChatNVIDIA then does
# `payload.update(self.model_kwargs)` — sending `max_retries` as an API BODY
# parameter. The hosted NIM endpoint rejects it with
# "400 Validation: Unsupported parameter(s): max_retries", killing the run. So
# the NVIDIA builder below deliberately does not set it.
_DEFAULT_MAX_RETRIES = int(os.getenv("JESSICA_MODEL_MAX_RETRIES", "5"))

# Fix #6 (startup resilience): how many times to retry the ChatNVIDIA
# constructor's live validation call on a TRANSIENT boot-time failure (DNS blip,
# NIM cold start, 5xx, timeout) before giving up. Deterministic failures (bad
# key -> 401/403, or a 400 "Unsupported parameter") are never retried — see
# _build_nvidia_model. This is OUR retry loop; we still never pass max_retries
# to ChatNVIDIA (BUG-01: it leaks into the API body -> 400).
_MODEL_BUILD_MAX_ATTEMPTS = int(os.getenv("JESSICA_MODEL_BUILD_ATTEMPTS", "3"))


def _build_nvidia_model(
    model: str,
    api_key: str | None,
    # MED-01: default lowered 1.0 → 0.3. Every current call site passes an
    # explicit temperature, so this is defensive only — but a future call that
    # forgets the kwarg should inherit the low-sampling default that makes
    # structured tool-call generation deterministic, not a sampling-heavy 1.0.
    temperature: float = 0.3,
    top_p: float = 0.95,

    max_tokens: int | None = None,
    enable_thinking: bool = False,
    seed: int | None = _DEFAULT_SEED,
    reasoning_budget: int | None = None,
    chat_template_kwargs: dict[str, Any] | None = None,
) -> ChatNVIDIA:
    # BUG-01: no `max_retries` here. ChatNVIDIA does not declare it as a field,
    # so passing it leaks into model_kwargs → the API body → a 400. Retry of
    # transient NIM failures is handled at the call site (the /ask and /resume
    # error triage), NOT via an unsupported constructor kwarg.
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "temperature": temperature,
        "top_p": top_p,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if seed is not None:
        kwargs["seed"] = seed

    # Native reasoning controls for thinking-capable NIM models (e.g.
    # nemotron-3-ultra). These are passed as top-level ChatNVIDIA constructor
    # kwargs — NOT nested under `extra_body` (which the hosted endpoint rejects
    # with "400 Unsupported parameter(s): extra_body"). Passing them directly
    # also keeps the object a plain ChatNVIDIA (a BaseChatModel), so deepagents'
    # `resolve_model` isinstance check still passes — unlike the
    # `with_thinking_mode(...)` wrapper, which returns a RunnableBinding.
    if reasoning_budget is not None:
        kwargs["reasoning_budget"] = reasoning_budget
    if chat_template_kwargs is not None:
        kwargs["chat_template_kwargs"] = chat_template_kwargs

    # RELIABILITY invariant — reasoning-budget starvation guard. With native
    # thinking on, `max_tokens` is the TOTAL output ceiling and `reasoning_budget`
    # is how much of it hidden reasoning may consume. If max_tokens is NOT strictly
    # greater than reasoning_budget, the model can spend its entire budget thinking
    # and terminate with an EMPTY visible turn (no answer, no tool call) — the blank
    # turn that starves the brain and subagents alike. We can only ever RAISE the
    # ceiling here, never lower it, so this strictly increases availability and
    # protects every thinking-enabled build regardless of what the call site passed.
    if (
        reasoning_budget is not None
        and max_tokens is not None
        and max_tokens <= reasoning_budget
    ):
        _bumped = reasoning_budget * 2
        logger.warning(
            "nvidia_model.max_tokens_bumped",
            model=model,
            requested_max_tokens=max_tokens,
            reasoning_budget=reasoning_budget,
            new_max_tokens=_bumped,
            note="max_tokens must exceed reasoning_budget or the model can emit a blank final turn.",
        )
        kwargs["max_tokens"] = _bumped

    # RELIABILITY (Fix #6): the ChatNVIDIA constructor performs a live HTTP
    # validation call against the hosted NIM endpoint, so a transient blip at
    # boot (DNS, cold start, 5xx, timeout) would otherwise raise straight out of
    # module import and crash the whole server. Retry a few times with short
    # backoff. Deterministic failures (bad key -> 401/403, or a 400 "Unsupported
    # parameter" bug) are NOT retryable, so re-raise those immediately rather
    # than burn attempts and stall startup.
    last_exc: Exception | None = None
    for _attempt in range(_MODEL_BUILD_MAX_ATTEMPTS):
        try:
            return ChatNVIDIA(**kwargs)
        except Exception as exc:
            last_exc = exc
            _status = (
                getattr(exc, "status_code", None)
                or getattr(getattr(exc, "response", None), "status_code", None)
            )
            _msg = str(exc)
            _deterministic = (
                _status in (400, 401, 403)
                or "[400]" in _msg or "[401]" in _msg or "[403]" in _msg
                or "Unsupported parameter" in _msg
                or "Forbidden" in _msg
            )
            if _deterministic or _attempt == _MODEL_BUILD_MAX_ATTEMPTS - 1:
                raise
            logger.warning(
                "nvidia_model.build_retry",
                model=model,
                attempt=_attempt + 1,
                max_attempts=_MODEL_BUILD_MAX_ATTEMPTS,
                error=_msg,
            )
            time.sleep(0.5 * (_attempt + 1))
    # Unreachable — the loop always returns or raises — but satisfies type checkers.
    assert last_exc is not None
    raise last_exc




# ── Main brain
# A frontier planning model (nvidia/nemotron-3-super-120b-a12b by default — see
# the rationale at the build call below for why super-120b, not ultra-550b).
# The orchestrator does all task decomposition and delegation across
# 12 subagents, so its reasoning quality is the single biggest driver of both
# tool-call accuracy and long-horizon reliability. Native thinking is enabled
# via `reasoning_budget` + `chat_template_kwargs` (passed as top-level ChatNVIDIA
# kwargs, not `extra_body`), keeping the object a BaseChatModel for deepagents.
_brain_thinking = os.getenv("JESSICA_BRAIN_ENABLE_THINKING", "true").lower() == "true"
_brain_reasoning_budget = int(os.getenv("JESSICA_BRAIN_REASONING_BUDGET", "16384"))
try:
    chat_model = _build_nvidia_model(
        # Default switched nemotron-3-ultra-550b → nemotron-3-super-120b-a12b: the
        # 550B endpoint was intermittently 503 (ResourceExhausted, worker limit
        # 32/32) and very slow (~32s tool-call), so a trivial turn could finish
        # entirely inside reasoning with EMPTY final content — surfacing the
        # "couldn't generate a response" fallback. super-120b is the reliable default.
        model=os.getenv("JESSICA_BRAIN_MODEL_ID", "nvidia/nemotron-3-super-120b-a12b"),
        api_key=jessica_brain_api_key,

        # Lowered default 1.0 → 0.3: the orchestrator's single job is to emit clean,
        # well-formed structured `task`/tool calls and route to the correct subagent.
        # Low sampling + the fixed seed (see _DEFAULT_SEED) make that deterministic
        # and reproducible — the biggest reliability lever for tool-call accuracy.
        temperature=float(os.getenv("JESSICA_BRAIN_TEMPERATURE", "0.3")),
        top_p=float(os.getenv("JESSICA_BRAIN_TOP_P", "0.95")),
        max_tokens=int(os.getenv("JESSICA_BRAIN_MAX_TOKENS", "16384")),
        reasoning_budget=_brain_reasoning_budget if _brain_thinking else None,
        chat_template_kwargs={"enable_thinking": True} if _brain_thinking else None,
    )
except Exception as exc:  # pragma: no cover - defensive startup guard
    # Fix #6: the brain build makes a live NIM validation call. If it fails even
    # after _build_nvidia_model's own retries, degrade to None instead of
    # crashing module import — the fastAPI_backend import guard tolerates this
    # and the lifespan then boots in degraded (in-memory) mode.
    logger.warning("chat_model.build_failed", error=str(exc))
    chat_model = None




# ── Web Search / research model ───────────────────────────────────────────────
# Model-agnostic: picks the provider from RESEARCH_MODEL_ID. Gemini quota is
# limited, so this defaults to an NVIDIA NIM model. Only routes
# to ChatGoogleGenerativeAI when the model id explicitly names a gemini model.
_research_model_id = os.getenv("RESEARCH_MODEL_ID", "nvidia/nemotron-3-ultra-550b-a55b")
try:
    if research_api_key and research_api_key.strip():
        if "gemini" in _research_model_id.lower():
            web_search_model = ChatGoogleGenerativeAI(
                model=_research_model_id,
                api_key=research_api_key.strip(),
                temperature=0.3,
                max_retries=_DEFAULT_MAX_RETRIES,
            )

        else:
            web_search_model = _build_nvidia_model(
                model=_research_model_id,
                api_key=research_api_key.strip(),
                temperature=0.3,
                top_p=0.95,
                max_tokens=16384,
            )
    else:
        logger.warning("web_search_model.missing_api_key", note="RESEARCH_MODEL_API_KEY not set in .env.")
        web_search_model = None
except Exception as exc:  # pragma: no cover - defensive startup guard
    # Fix #6: guard the eager research-model build the same way — a transient
    # boot-time endpoint failure yields None (research features degrade) instead
    # of aborting the whole loadenv import.
    logger.warning("web_search_model.build_failed", error=str(exc))
    web_search_model = None

# ── Dedicated subagent model instances ────────────────────────────────────────
def _build_subagent_model(
    env_model_key: str,
    env_api_key: str,
    extra_body: dict[str, Any] | None = None,
    default_model: str = "stepfun-ai/step-3.7-flash",
) -> Any:
    m_id  = os.getenv(env_model_key)
    k_val = os.getenv(env_api_key) or os.getenv("OPENROUTER_API_KEY")

    if not k_val or not k_val.strip():
        logger.warning(
            "subagent.missing_api_key",
            subagent=env_api_key,
            note=f"No API key provided for {env_api_key} in .env.",
        )
        clean_key = None
    else:
        clean_key = k_val.strip()

        # Enforce API key isolation audit
        if clean_key in _REGISTERED_KEYS:
            logger.warning(
                "subagent.api_key_shared",
                subagent=env_api_key,
                shared_with=_REGISTERED_KEYS[clean_key],
                note="Subagent API key collision detected. Ensure each subagent uses a unique API key in .env.",
            )
        else:
            _REGISTERED_KEYS[clean_key] = env_api_key

    model_name = m_id.strip() if m_id and m_id.strip() else default_model

    # NOTE: We intentionally do NOT pass `extra_body` (e.g.
    # {"chat_template_kwargs": {"thinking": False}}) to hosted NVIDIA NIM models.
    # The hosted endpoint rejects it outright with
    # "400 Validation: Unsupported parameter(s): extra_body".
    # Reasoning models handle thinking natively; the reliable lever we DO have
    # for clean, structured tool calls is low sampling (temperature/top_p below).

    if any(p in model_name.lower() for p in ("anthropic/", "openrouter/", "claude-", "sonnet")):
        or_kwargs: dict[str, Any] = {
            "model": model_name,
            "temperature": 0,
            "max_tokens": 1024,
            "max_retries": 2,
        }
        if clean_key:
            or_kwargs["api_key"] = clean_key
        built = ChatOpenRouter(**or_kwargs)
    elif "gemini" in model_name.lower():
        g_kwargs: dict[str, Any] = {
            "model": model_name,
            "temperature": 0.3,
            "max_retries": _DEFAULT_MAX_RETRIES,
        }
        if clean_key:
            g_kwargs["api_key"] = clean_key
        built = ChatGoogleGenerativeAI(**g_kwargs)
    else:
        is_nemotron = "nemotron" in model_name.lower()
        built = _build_nvidia_model(
            model=model_name,
            api_key=clean_key,
            temperature=0.3,
            top_p=0.95,
            # Mirror the brain's headroom (32768 > 16384): max_tokens is the TOTAL
            # output ceiling and reasoning_budget is how much hidden reasoning may
            # consume. Keeping them EQUAL (the old 16384==16384) let a thinking
            # subagent spend its whole budget on reasoning and terminate with a
            # BLANK visible answer — the exact starvation that made subagents loop.
            # A ceiling only prevents premature truncation; it adds no latency to
            # healthy turns. Belt-and-suspenders: _build_nvidia_model also enforces
            # max_tokens > reasoning_budget, so this is auto-corrected even if edited.
            max_tokens=32768,
            enable_thinking=is_nemotron,
            reasoning_budget=16384 if is_nemotron else None,
            chat_template_kwargs={"enable_thinking": True} if is_nemotron else None,
        )


    return built



def _safe_build_subagent_model(
    env_model_key: str,
    env_api_key: str,
    extra_body: dict[str, Any] | None = None,
    default_model: str = "stepfun-ai/step-3.7-flash",
) -> Any:
    """CRIT-01: isolate each subagent model construction.

    Every ChatNVIDIA/ChatGoogleGenerativeAI/ChatOpenRouter constructor runs at
    module import time and can raise on a transient network fault (DNS blip, NIM
    cold start, 5xx). Because these fire at module scope, a single failure would
    abort the whole `loadenv` import, `chat_model` would never be defined, and the
    fastAPI_backend startup guard could not engage. Wrapping each build means a
    failed subagent model returns None — and subagent_loader already treats a
    None model as "fall through to the default", so the app still boots.
    """
    try:
        return _build_subagent_model(env_model_key, env_api_key, extra_body, default_model=default_model)
    except Exception as exc:  # pragma: no cover - defensive startup guard
        logger.warning(
            "subagent_model.build_failed",
            key=env_model_key,
            error=str(exc),
        )
        return None


jira_agent_model              = _safe_build_subagent_model("JIRA_AGENT_MODEL_ID", "JIRA_AGENT_API_KEY")
confluence_agent_model        = _safe_build_subagent_model("CONFLUENCE_AGENT_MODEL_ID", "CONFLUENCE_AGENT_API_KEY")
email_agent_model             = _safe_build_subagent_model("EMAIL_AGENT_MODEL_ID", "EMAIL_AGENT_API_KEY")
slack_agent_model             = _safe_build_subagent_model("SLACK_AGENT_MODEL_ID", "SLACK_AGENT_API_KEY")
web_searcher_model            = _safe_build_subagent_model("WEB_SEARCHER_MODEL_ID", "WEB_SEARCHER_API_KEY")
drive_agent_model            = _safe_build_subagent_model("DRIVE_AGENT_MODEL_ID", "DRIVE_AGENT_API_KEY")
docs_agent_model             = _safe_build_subagent_model("DOCS_AGENT_MODEL_ID", "DOCS_AGENT_API_KEY")
slides_agent_model           = _safe_build_subagent_model("SLIDES_AGENT_MODEL_ID", "SLIDES_AGENT_API_KEY")
sheets_agent_model           = _safe_build_subagent_model("SHEETS_AGENT_MODEL_ID", "SHEETS_AGENT_API_KEY")
forms_agent_model            = _safe_build_subagent_model("FORMS_AGENT_MODEL_ID", "FORMS_AGENT_API_KEY")
calendar_agent_model         = _safe_build_subagent_model("CALENDAR_AGENT_MODEL_ID", "CALENDAR_AGENT_API_KEY")
google_classroom_agent_model  = _safe_build_subagent_model("GOOGLE_CLASSROOM_AGENT_MODEL_ID", "GOOGLE_CLASSROOM_AGENT_API_KEY")
juliet_agent_model            = _safe_build_subagent_model("JULIET_AGENT_MODEL_ID", "JULIET_AGENT_API_KEY")
# P0 FIX: agents/google_workspace/agent.py does `from loadenv import
# google_workspace_agent_model` (its header documents that name as being built from
# GOOGLE_WORKSPACE_AGENT_MODEL_ID / GOOGLE_WORKSPACE_AGENT_API_KEY), but this name
# did not exist here — the resulting ImportError was swallowed by that module's
# try/except, so the Gemma supervisor silently fell back to model=None. Built through
# the same guarded helper as every other leaf, so a missing key or a transient
# fault yields None instead of aborting the loadenv import.
google_workspace_agent_model  = _safe_build_subagent_model("GOOGLE_WORKSPACE_AGENT_MODEL_ID", "GOOGLE_WORKSPACE_AGENT_API_KEY")
comms_agent_model             = _safe_build_subagent_model("COMMS_AGENT_MODEL_ID", "COMMS_AGENT_API_KEY") or email_agent_model or slack_agent_model
project_mgmt_agent_model      = _safe_build_subagent_model("PROJECT_MGMT_AGENT_MODEL_ID", "PROJECT_MGMT_AGENT_API_KEY") or jira_agent_model or confluence_agent_model
research_agent_model          = _safe_build_subagent_model("RESEARCH_AGENT_MODEL_ID", "RESEARCH_AGENT_API_KEY") or web_searcher_model


# NOTE: legacy aliases (atlassian_agent_model, docs_drive_agent_model,
# data_productivity_agent_model) have been removed — no active code references
# them. The subagent_loader models_map entries for those names return None and
# fall through to the dedicated {agent_name}_model lookup, which is correct.

# ── Routing model — Layer 2 intent classifier ────────────────────────────────
# CRIT-01: guard the router build too. It also fires at module scope, so an
# endpoint blip here would abort the whole loadenv import. route_message()
# already fails safe (returns RoutingDecision(subagent="general")) on any
# error, so a None routing_model simply means the main brain routes freely.
_routing_key = os.getenv("ROUTING_MODEL_API_KEY", "").strip()
try:
    routing_model = _build_nvidia_model(
        # Default switched off mistralai/mistral-medium-3.5-128b: it reached
        # end-of-life on 2026-08-07 and now returns [410] Gone on every call,
        # which spammed router.error and cost ~4s per turn before failing safe.
        model=os.getenv("ROUTING_MODEL_ID", "nvidia/nemotron-3-super-120b-a12b"),
        api_key=_routing_key,

        temperature=0.1,
        top_p=0.9,
        max_tokens=128,
    )
except Exception as exc:  # pragma: no cover - defensive startup guard
    logger.warning("routing_model.build_failed", error=str(exc))
    routing_model = None


# ── Empty-turn fallback responder — thinking-OFF recovery model ───────────────
# Used ONLY by routes/chat.py as a last resort. The orchestrator brain runs with
# native thinking ON, so on a trivial prompt (e.g. "hi") it can occasionally
# spend the whole turn inside <think>/reasoning_content and end with EMPTY final
# content. chat.py drops reasoning chunks by design, so that turn produced no
# visible text and previously surfaced the generic
# "I completed the task but couldn't generate a response." string.
#
# This is a cheap, thinking-DISABLED variant of the brain. When a turn ends with
# no visible text and nothing recoverable from the checkpoint, chat.py re-asks
# THIS model once for a plain final answer. Thinking is off (no reasoning_budget /
# chat_template_kwargs) so it reliably emits user-facing text. Guarded like the
# others so a transient build error simply yields None (chat.py then falls back
# to the generic string, i.e. no worse than before).
_fallback_responder_key = os.getenv("JESSICA_BRAIN_API_KEY")
try:
    fallback_responder_model = _build_nvidia_model(
        model=os.getenv(
            "JESSICA_FALLBACK_RESPONDER_MODEL_ID",
            os.getenv("JESSICA_BRAIN_MODEL_ID", "nvidia/nemotron-3-super-120b-a12b"),
        ),
        api_key=_fallback_responder_key,
        temperature=0.3,
        top_p=0.95,
        max_tokens=1024,
        # Thinking intentionally OFF — this model exists precisely to emit a
        # direct, visible answer when the thinking-enabled brain produced none.
    )
except Exception as exc:  # pragma: no cover - defensive startup guard
    logger.warning("fallback_responder_model.build_failed", error=str(exc))
    fallback_responder_model = None



