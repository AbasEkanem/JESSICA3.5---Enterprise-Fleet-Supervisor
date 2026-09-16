"""
test_models.py — One-by-one health check for every model configured in loadenv.py.

For each model instance it runs two low-token probes:
  1. simple  — a plain "reply with OK" chat call (tests basic connectivity/auth)
  2. tools   — bind_tools() + a call that should trigger one tool call
               (tests structured tool-calling, which is what the Slack/agent
               subagents actually rely on — the NVIDIA NIM 500s happen here)

Run:
    jessica3.0_venv\\Scripts\\python.exe test_models.py

Nothing is written or sent anywhere; the dummy tool is never executed.
"""
from __future__ import annotations

import os
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout


warnings.filterwarnings("ignore")

from langchain_core.tools import tool

import loadenv

# Per-call wall-clock budget. A model that hangs on a tool schema (as
# minimaxai/minimax-m3 did) is reported as a TIMEOUT failure instead of
# stalling the whole sweep.
_CALL_TIMEOUT_S = float(os.getenv("MODEL_TEST_TIMEOUT_S", "45"))


def _with_timeout(fn, *args):
    """Run fn(*args) but give up after _CALL_TIMEOUT_S seconds."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn, *args)
        return fut.result(timeout=_CALL_TIMEOUT_S)



# A tiny, cheap tool the model should want to call for the tools probe.
@tool
def get_weather(city: str) -> str:
    """Get the current weather for a given city."""
    return f"Sunny in {city}."


# (attribute_name_in_loadenv, human_label, env_model_id_key)
MODELS: list[tuple[str, str, str | None]] = [
    ("chat_model",                   "Orchestrator (Jessica brain)", "JESSICA_BRAIN_MODEL_ID"),
    ("routing_model",                "Router (Layer 2)",             "ROUTING_MODEL_ID"),
    ("web_search_model",             "Web search / research",        "RESEARCH_MODEL_ID"),
    ("jira_agent_model",             "Jira agent (Morgan)",          "JIRA_AGENT_MODEL_ID"),
    ("confluence_agent_model",       "Confluence agent (Connie)",    "CONFLUENCE_AGENT_MODEL_ID"),
    ("email_agent_model",            "Email agent (Jordan)",         "EMAIL_AGENT_MODEL_ID"),
    ("slack_agent_model",            "Slack agent (Tyler)",          "SLACK_AGENT_MODEL_ID"),
    ("web_searcher_model",           "Web searcher (Sophie)",        "WEB_SEARCHER_MODEL_ID"),
    ("drive_agent_model",            "Drive agent (Alex)",           "DRIVE_AGENT_MODEL_ID"),
    ("docs_agent_model",             "Docs agent (Taylor)",          "DOCS_AGENT_MODEL_ID"),
    ("slides_agent_model",           "Slides agent (Riley)",         "SLIDES_AGENT_MODEL_ID"),
    ("sheets_agent_model",           "Sheets agent (Chris)",         "SHEETS_AGENT_MODEL_ID"),
    ("forms_agent_model",            "Forms agent (Francis)",        "FORMS_AGENT_MODEL_ID"),
    ("calendar_agent_model",         "Calendar agent (Casey)",       "CALENDAR_AGENT_MODEL_ID"),
    ("google_classroom_agent_model", "Classroom agent (Sam)",        "GOOGLE_CLASSROOM_AGENT_MODEL_ID"),
    ("juliet_agent_model",           "Classroom coursework (Juliet)", "JULIET_AGENT_MODEL_ID"),
]


def _model_id(instance, env_key: str | None) -> str:
    mid = getattr(instance, "model", None)
    if mid:
        return str(mid)
    if env_key:
        return os.getenv(env_key, "?") or "?"
    return "?"


def _short_err(exc: Exception) -> str:
    s = str(exc).replace("\n", " ")
    return (s[:180] + "…") if len(s) > 180 else s


def probe_simple(instance) -> tuple[bool, str, float]:
    """Returns (ok, detail, latency_ms). latency is the wall-clock time of the
    invoke() call, so a passing-but-slow model is still visible."""
    t0 = time.perf_counter()
    try:
        r = instance.invoke("Reply with exactly: OK")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        content = getattr(r, "content", "")
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )
        return True, (content or "").strip()[:40], elapsed_ms
    except Exception as exc:  # noqa: BLE001 — we want to classify every failure
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return False, f"{type(exc).__name__}: {_short_err(exc)}", elapsed_ms


def probe_tools(instance) -> tuple[bool, str, float]:
    """Returns (ok, detail, latency_ms) for the bind_tools() + tool-call probe —
    this is the path that actually matters for every subagent, so its latency is
    the headline number for tool-calling responsiveness."""
    try:
        bound = instance.bind_tools([get_weather])
    except Exception as exc:  # noqa: BLE001
        return False, f"bind_tools {type(exc).__name__}: {_short_err(exc)}", 0.0
    t0 = time.perf_counter()
    try:
        r = _with_timeout(bound.invoke, "What's the weather in Lagos? Use the tool.")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        calls = getattr(r, "tool_calls", None) or []
        if calls:
            return True, f"tool_call -> {calls[0].get('name')}", elapsed_ms
        # No tool call is not a hard failure — the endpoint still answered.
        return True, "answered (no tool_call)", elapsed_ms
    except FutureTimeout:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return False, f"TIMEOUT after {_CALL_TIMEOUT_S:.0f}s (model hung on tool schema)", elapsed_ms
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return False, f"{type(exc).__name__}: {_short_err(exc)}", elapsed_ms




def main() -> int:
    print("=" * 78)
    print("Jessica model health check")
    print("=" * 78)

    any_fail = False
    # (label, tool_ok, tool_latency_ms) rows for the latency leaderboard.
    latency_rows: list[tuple[str, bool, float]] = []
    for attr, label, env_key in MODELS:
        instance = getattr(loadenv, attr, None)
        if instance is None:
            print(f"\n[SKIP] {label} ({attr}) — not built (missing API key / model id).")
            any_fail = True
            continue

        mid = _model_id(instance, env_key)
        print(f"\n{label}")
        print(f"  attr : {attr}")
        print(f"  model: {mid}")

        ok_s, detail_s, ms_s = probe_simple(instance)
        print(f"  [{'PASS' if ok_s else 'FAIL'}] simple : {ms_s:8.0f} ms  {detail_s}")

        ok_t, detail_t, ms_t = probe_tools(instance)
        print(f"  [{'PASS' if ok_t else 'FAIL'}] tools  : {ms_t:8.0f} ms  {detail_t}")

        latency_rows.append((label, ok_t, ms_t))
        if not (ok_s and ok_t):
            any_fail = True

    # ── Latency leaderboard (tool-call path, slowest first) ──────────────────
    print("\n" + "=" * 78)
    print("Tool-call latency leaderboard (slowest first)")
    print("=" * 78)
    for label, ok_t, ms_t in sorted(latency_rows, key=lambda r: r[2], reverse=True):
        status = "PASS" if ok_t else "FAIL"
        print(f"  {ms_t:8.0f} ms  [{status}]  {label}")
    ok_latencies = [ms for _, ok, ms in latency_rows if ok and ms > 0]
    if ok_latencies:
        avg = sum(ok_latencies) / len(ok_latencies)
        print(f"\n  avg (passing): {avg:8.0f} ms   "
              f"min: {min(ok_latencies):.0f} ms   max: {max(ok_latencies):.0f} ms")

    print("\n" + "=" * 78)
    print("Done." + ("  Some models FAILED — see above." if any_fail else "  All models OK."))
    print("=" * 78)
    return 1 if any_fail else 0



if __name__ == "__main__":
    sys.exit(main())
