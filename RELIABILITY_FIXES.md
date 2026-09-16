# Jessica 3.5 — Reliability Audit & Fixes

**Date:** 2026-07-31 · **Harness:** deepagents 0.6.12

Architecture is solid: orchestrator + 12 subagents, layered guardrails, Postgres persistence, HITL `/resume`. Findings below, highest severity first.

---

## 🔴 CRITICAL: HITL guardrail is dead
`routes/chat.py` has a full HITL system (watches `__interrupt__`, classifies risk, emits SSE `interrupt`, exposes `/resume`), but `JESSICA3.5.py:create_jessicaAI()` **never passes `interrupt_on` to `create_deep_agent()`**. deepagents 0.6.12 gates all interrupts on that param, so send_email/schedule_email/send_slack_dm/transition_jira_issue execute with zero approval.

**Fix** — pass `interrupt_on` at both levels:
- `JESSICA3.5.py`: `interrupt_on={"send_research_email": True, "schedule_research_email": True}` on `create_jessicaAI`.
- `subagent.yaml`: add `interrupt_on:` blocks — email_agent (`send_research_email`, `schedule_research_email`), slack_agent (`send_slack_message`, `send_slack_dm`, `reply_to_slack_thread`), jira_agent (`transition_jira_issue`).
- `subagent_loader.py`: in the load loop, pass it through — `if "interrupt_on" in doc: subagent["interrupt_on"] = doc["interrupt_on"]`.

**Verify:** ask to send an email → SSE emits `{"type":"interrupt",...}` → stream pauses → POST `/resume {"decision":"approve"|"reject"}` → continues.

**API confirmation (0.6.12):** both `create_deep_agent(interrupt_on=...)` and the SubAgent TypedDict accept `dict[str, bool | InterruptOnConfig]`.

---

## 🔴 CRITICAL: Boot crash risk (partially fixed)
`loadenv.py` builds every `ChatNVIDIA(...)` at import; `__init__` makes a live HTTP call to NVIDIA. A DNS/network blip raises `ConnectionError` and breaks the whole import chain. Partially mitigated by degraded-mode fallback in `fastAPI_backend.py`, but the initial `loadenv` import still precedes the try/except.

**Fix:** make model construction lazy via `get_chat_model()` (build on first use, cache in a module global) and have `JESSICA3.5.py` call the loader. Simpler alternative: add `timeout=5` to each `_build_nvidia_model()` and rely on the existing degraded fallback.

---

## 🟠 HIGH: Import-time graph is wasteful & stateless
`JESSICA3.5.py` ran `graph = create_jessicaAI()` at import (no checkpointer/store) while `fastAPI_backend.py` builds the real Postgres-backed one. The import build triggers network calls and produces a graph that must never serve traffic.
**Fix:** keep `graph = None` and build lazily (a `get_graph()` accessor), or leave the export disabled since production builds it in the lifespan.

---

## 🟡 MEDIUM
- **Brain temperature too high for tool calls** — `loadenv.py` sets `temperature=1.0`; lower to `0.3` (env `JESSICA_BRAIN_TEMPERATURE=0.3`) for deterministic routing.
- **`reasoning_budget`/`chat_template_kwargs` runtime risk** — these land in `model_kwargs` and may hit the NIM as unsupported `extra_body` (400). Test a direct `ChatNVIDIA` invoke; if it 400s, remove or wrap in try/except.

## 🟢 LOW
- **Doc drift** — `guardrails/__init__.py` advertises a "Layer 3 output_guard" that doesn't exist (sanitization is inlined in `routes/chat.py`). Fix the docstring.

---

## Testing checklist
- [ ] HITL email/Slack/Jira: interrupt fires, approve sends, reject halts politely.
- [ ] Boot resilience: break DNS to NVIDIA → degraded mode still starts an in-memory agent.
- [ ] Tool-call determinism: same query ×10 → same subagent + tool structure (low temp + seed).

## Recommendations
1. Apply the HITL fix immediately (production-critical).
2. Lower brain temperature to 0.3.
3. Add `/ask → interrupt → /resume` integration tests.
4. Monitor `reasoning_budget` 400s for 48h; keep if none.
5. Consider `interrupt_on` for `delete_course`, `delete_coursework`, `delete_drive_file` (irreversible).
