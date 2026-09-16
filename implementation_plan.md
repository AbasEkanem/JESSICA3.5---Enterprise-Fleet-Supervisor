# Architecture Refactor: Jessica 3.5 → Supervisor of Supervisors (Hierarchical Fleet)

**Status:** APPROVED for execution · **Date:** 2026-09-12 · **Stack:** deepagents 0.7.5 (pinned `>=0.7.5,<0.8.0`), LangChain agents, LangGraph, FastAPI/uvicorn (single-process monolith)

Transition Jessica from a flat orchestrator managing 13 scattered subagents and 12+ loose tool files in the root directory into a **Supervisor of Supervisors (Hierarchical Agent Team)**.

Jessica (Layer 0 Orchestrator) delegates exclusively to **4 Domain Supervisors**, each owning its tools, state, and leaf logic in a self-contained package under `agents/`:

1. **`google_workspace_agent`** — **pure LangGraph `StateGraph`**: custom routing, pre-call auth verification, bounded tool execution. Covers all Google Workspace + Classroom services (Drive, Docs, Sheets, Slides, Forms, Calendar, Classroom courses & coursework/Juliet).
2. **`comms_agent`** — messaging channels: **Slack (pure LangGraph)** + **Email** (Resend → Gmail SMTP fallback + IMAP inbox + Supabase scheduling; email leaf via `create_agent`).
3. **`project_mgmt_agent`** — **Jira (pure LangGraph)** for issue lifecycle/transitions + **Confluence (`create_agent`)** for pages/search.
4. **`research_agent`** — **`create_agent`** over Tavily, Exa, Linkup, datetime, think/synthesis, and file-output tools.

## Verified Ground Rules (deepagents 0.7.5 — checked against installed source, not docs)

- **No `harness=` kwarg exists** on `create_deep_agent` (params: `model, tools, system_prompt, middleware, subagents, skills, memory, permissions, backend, interrupt_on, response_format, state_schema, context_schema, checkpointer, store, debug, name, cache`). Harness profiles auto-select per model-id — exactly what `jessica_harness` already does at import.
- **Members register as `CompiledSubAgent`**: `{"name", "description", "runnable": <compiled graph>}`. The dispatcher (`deepagents/graph.py` L647-655) checks `"graph_id" in spec` → Async, `"runnable" in spec` → compiled, else → raw spec re-compiled by the harness. A **bare** `CompiledStateGraph` instance in `subagents=` raises `TypeError` — every member must be dict-wrapped.
- **Every member graph's state must include a `messages` key** — that is the report channel back to the parent (last non-empty `AIMessage`, or `structured_response` if returned). `CompiledSubAgent` runnables are used as-is and **do not inherit** JESSICA's `state_schema` — compile each with its own.
- **`AsyncSubAgent` is remote-only** (`name, description, graph_id, url, headers` → Agent-Protocol server via LangGraph SDK). NOT used in the monolith. Reserved for the later Railway split, where each domain deploys as its own service and JESSICA attaches via `AsyncSubAgent`.
- **`interrupt_on` at JESSICA level only gates JESSICA's own tool calls.** Tools that move inside custom member graphs are invisible to it → each domain supervisor must carry its own HITL gate (see HARD-RISK GATE).

---

## Architecture Overview

```
                          ┌───────────────────────────┐
                          │   Jessica 3.5 (Top L0)    │
                          │   Orchestrator Brain      │
                          └─────────────┬─────────────┘
                                        │  task() tool → [4 names]
           ┌────────────────────────────┼────────────────────────────┬────────────────────────────┐
           ▼                            ▼                            ▼                            ▼
┌──────────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
│ google_workspace     │     │ comms_agent          │     │ project_mgmt_agent   │     │ research_agent       │
│ Supervisor           │     │ Supervisor           │     │ Supervisor           │     │ Supervisor           │
│ (Pure LangGraph)     │     │ (LangGraph + Agent)  │     │ (LangGraph + Agent)  │     │ (create_agent)       │
└──────────┬───────────┘     └──────────┬───────────┘     └──────────┬───────────┘     └──────────┬───────────┘
           │                            │                            │                            │
   [Workspace + Classroom]      [Slack + Email]              [Jira + Confluence]         [Tavily+Exa+Linkup]
   Calendar · Drive             Slack/DM/Threads             Issues/Sprints              Web Search
   Docs · Sheets · Slides       Email send/read/draft        Pages/Spaces                Fact Verification
   Forms · Classroom+Juliet     Scheduled emails             Search/Update               Synthesis + Output
```

---

## Directory Layout

```
jessica3.0.0/
├── agents/
│   ├── __init__.py
│   ├── google_workspace/
│   │   ├── __init__.py
│   │   ├── agent.py         # StateGraph: validate → route → tools → HITL gate
│   │   ├── tools.py         # Consolidated Google service tools (+ auth/token store)
│   │   └── prompts.md       # Domain system prompt
│   ├── comms/
│   │   ├── __init__.py
│   │   ├── agent.py         # Supervisor: Slack (LangGraph leaf) + Email (create_agent leaf)
│   │   ├── tools.py         # Slack + Email + scheduling tools
│   │   └── prompts.md
│   ├── project_mgmt/
│   │   ├── __init__.py
│   │   ├── agent.py         # Jira (LangGraph chain) + Confluence (create_agent leaf)
│   │   ├── tools.py         # Atlassian tools
│   │   └── prompts.md
│   └── research/
│       ├── __init__.py
│       ├── agent.py         # create_agent over search + synthesis + datetime
│       ├── tools.py         # Tavily/Exa/Linkup/think/write_file/datetime
│       └── prompts.md
├── subagent.yaml            # Registry INDEX of the 4 supervisors (module refs, not tool lists)
├── subagent_loader.py       # Imports each module → emits CompiledSubAgent specs
└── <root tool modules remain as thin shims during transition, then retire>
```


---

## Component Details

### `agents/google_workspace/`
**`tools.py`** — consolidates `google_calendar_tools.py`, `google_drive_tools.py`, `google_docs_tools.py`, `google_sheets_tools.py`, `google_slides_tools.py`, `google_forms_tools.py`, `google_classroom_tools.py` (+ `google_classroom_courses_tools` / `juliet_tools` split). Shared auth via `google_auth.py` / `google_token_store.py` — the per-module OAuth token model (`token_<api>.json`) is preserved unchanged, so a leaked Slides token still can't touch Classroom grades.

**`agent.py`** — pure LangGraph:
- `WorkspaceState(MessagesState)` — includes `messages` (satisfies the CompiledSubAgent contract).
- **Validation node** — verifies an active service account / OAuth token for the target service BEFORE any tool executes; fails fast with an actionable message instead of mid-run 401s.
- **Router node** — splits productivity (Drive/Docs/Sheets/Slides/Forms/Calendar) vs Classroom (courses vs coursework/grading) intents.
- **Tool node** — bounded retries + structured error interception (never surfaces raw tracebacks to JESSICA).
- **HITL gate** — hard-risk tool interrupt (see HARD-RISK GATE).
- exposes `make_graph() -> CompiledStateGraph`.

**`prompts.md`** — domain instructions + delegation boundaries; replaces the 8 Google thin personas (drive/docs/sheets/slides/forms/calendar/google_classroom/juliet).

### `agents/comms/`
**`tools.py`** — consolidates `slack_tools.py`, `email_tools.py`, `schedule_email.py` (Supabase queue `jessica_scheduled_emails`). The inbound `slack_webhook` stays a FastAPI route (it's transport, not agent logic) and forwards into this domain.

**`agent.py`** — supervisor with two leaves:
- **Slack leaf**: pure LangGraph subgraph (messages, threads, DMs, history, reactions).
- **Email leaf**: `create_agent` (send via Resend→Gmail SMTP, read/search inbox via IMAP, sent-log, scheduling).
- Coordinates draft-approval flow for outbound email (recipient confirmation is non-negotiable — see HARD-RISK GATE).

**`prompts.md`** — replaces Jordan + Tyler personas.

### `agents/project_mgmt/`
**`tools.py`** — consolidates `atlassian_tools.py` (Jira create/search/update/transition/assign/comment + Confluence create/read/update/search/comment).

**`agent.py`** — blends:
- **Jira leaf**: pure LangGraph chain for issue lifecycle (create → update → transition → assign → comment), with the HITL gate on transitions if promoted to hard-risk later.
- **Confluence leaf**: `create_agent` for page search/generation.

**`prompts.md`** — replaces Morgan + Connie personas.

### `agents/research/`
**`tools.py`** — consolidates `websearch_tools.py` (Tavily, Exa, Linkup, think_tool, write_file) + `datetime_tools` (never write a date from memory).

**`agent.py`** — `create_agent` with: deep-research system prompt, multi-query search synthesis, citation formatting (sources + flagged gaps — never fabricate), and output-to-file via `write_file`.

**`prompts.md`** — replaces the Sophie persona; carries the skill pipeline order (`research-engine → analysis-synthesis → report-and-email-delivery`) as operating instructions since skills live at JESSICA level.


---

## Registry Strategy (Option 3, resolved)

`subagent.yaml` remains the **single registry index JESSICA sees** — 4 entries, NOT 13 — but it no longer declares raw tool lists/prompts for harness compilation. Each entry names the package module that owns the compiled graph:

```yaml
name: google_workspace_agent
description: >-
  Domain supervisor for ALL Google Workspace + Classroom work (Drive, Docs, Sheets,
  Slides, Forms, Calendar, Classroom courses & grading). Pre-validates auth before tools.
module: agents.google_workspace.agent:make_graph
```

- **YAML = the index** (name + description are what JESSICA sees in her routing prompt — 4 descriptions ≈ zero context bloat vs 13).
- **`agents/` = the source of truth** (the actual custom graph, prompt, and state live in the package).
- **`subagent_loader.py`** imports each `module:` entry (`importlib`), calls it, and emits `{"name", "description", "runnable": graph}` — a `CompiledSubAgent`. `create_deep_agent(subagents=…)` then uses each graph as-is.
- Raw `SubAgent` specs remain supported for any future leaf that doesn't need a custom graph — the dispatcher forks on `"runnable" in spec`.

---

## Integration Changes

### [MODIFY] `subagent.yaml`
Replace the 13 documents with 4 entries (`google_workspace_agent`, `comms_agent`, `project_mgmt_agent`, `research_agent`), each with rich domain-boundary descriptions and a `module:` field.

### [MODIFY] `subagent_loader.py`
- Parse the 4 entries; resolve `module:` via `importlib.import_module` + attribute fetch; build `CompiledSubAgent` dicts.
- Validate: every loaded spec contains `"runnable"`; names unique; `make_graph()` returns a compiled graph whose state schema includes `messages`.
- Backward-compat: keep `load_subagents(path)` signature and return shape (list of dicts) so `JESSICA3.5.py` needs a one-line change.

### [MODIFY] `JESSICA3.5.py`
- `subagents=_subagent_loader` now receives the 4 `CompiledSubAgent` entries. Everything else (tools, memory, skills, backend, `interrupt_on` over `HARD_RISK_TOOLS`, middleware) stays as-is.

### [MODIFY] `guardrails/router.py`
- `SubagentType` literal, `_HINTS`, and `_ROUTER_SYSTEM` currently enumerate 13 names → replace with the 4 supervisor names (+ `general`). Recursion budget policy unchanged (`general`/low-confidence/resume → full 500; confident single-domain → focused 250).

### [MODIFY] `routes/chat_utils.py` + `system_prompts.py` + `JESSICA.md` + `AGENTS.md`
- The 13-name tables/hints in these files move to the 4 supervisors (CRIT-03 lesson: keep the router, prompts, and docs in lockstep — drift is how `juliet_agent` went invisible).
- `AGENTS.md` operating-contract table: 4 domain supervisors + `general`; delegation rules rewritten for domain boundaries.

### [MODIFY] `background_tasks.py`
- `start_bg_task(subagent_name, …)` resolves by name against the compiled graph — works unchanged with the 4 new names. Sweep any call sites/UI strings referencing the old 13.

### [MODIFY] `langgraph.json`
- Add graph entries per domain (`google_workspace`, `comms`, `project_mgmt`, `research`) pointing at each `agents/<domain>/agent.py:make_graph` so every member can boot/deploy standalone (also enables `langgraph dev` debugging per member). JESSICA's entries stay.

### [MODIFY] root tool files → moved → removed (hard cut, no shims — executed 2026-09-12)
- The 7 `google_*_tools.py` implementations + `google_auth.py` + `google_token_store.py` were **moved** into `agents/google_workspace/` as `drive.py`, `docs.py`, `sheets.py`, `slides.py`, `forms.py`, `calendar.py`, `classroom.py`, `auth.py`, `token_store.py` (short names, relative in-package imports).
- Readiness was proven (auth is Supabase/env-backed, credential paths are CWD-relative, not `__file__`-based) so no path anchoring was needed.
- External importers repointed in the same pass: `subagent_loader.py` (7 import blocks), `routes/chat.py`, `routes/google_oauth.py` (auth + 3 token-store uses), `background_tasks.py`.
- Verified: residue sweep clean (only third-party `google_auth_*` packages, registry keys, log prefixes remain), `py_compile` 14/14, live imports — 85/85 tool suite, loader (34 keys), oauth route, background tasks.
- NOTE: creds/token DATA files (`credentials.json`, `token.json`, `google_service_account.json`) stay at root (CWD-relative resolution).


---

## HARD-RISK GATE (HITL preservation — highest-priority technical item)

Today `config.HARD_RISK_TOOLS` → `JESSICA3.5.py` `interrupt_on` gates: `send_research_email`, `schedule_research_email`, `send_slack_message`, `send_slack_dm`, `reply_to_slack_thread`, `delete_drive_file`, `trash_drive_file`, `delete_calendar_event` (added 2026-09-12 when it became a true permanent delete — previously an alias of the soft-cancel), `delete_course`, `delete_coursework`, `share_drive_file_with_anyone`, `bulk_share_drive_files`.

**The regression risk:** once these tools execute *inside* a domain member's custom graph, JESSICA's `interrupt_on` no longer sees them (it only interrupts her own tool calls). HITL must be re-implemented per member:

- **Rule:** every member that owns a hard-risk tool installs a **pre-tool interrupt gate node** in its own graph. For pure-LangGraph members this is `interrupt_before=["tools"]` with a conditional check (or a dedicated gate node before the tool node that raises `langgraph.types.interrupt()` when the pending tool call is in the member's hard-risk set). For `create_agent` leaves, pass `interrupt_before`/middleware equivalents at build time.
- Each member defines its hard-risk set as a module constant (mirroring `config.HARD_RISK_TOOLS`, imported from it — single source of truth, no drift).
- JESSICA-level `interrupt_on` stays for her own remaining direct tools.
- **Verify:** delegation that would `delete_drive_file` pauses with an interrupt surfaced through the existing SSE `interrupt` card + `/resume` flow; approve/reject both work. This test is a release blocker.

**Model wiring:** `loadenv.py` already builds 13 dedicated subagent models. Map to 4 fleet models (reuse the existing per-domain constructors — e.g. the Google model for `google_workspace_agent`, slack+email models for the two comms leaves). Brain/routing/fallback models unchanged. Key isolation (`_REGISTERED_KEYS`) and no-`max_retries`-to-ChatNVIDIA rules carry over.

**State & middleware notes:**
- Member graphs compile with their own state schemas; they do NOT inherit JESSICA's — by design.
- `response_format` (dynamic structured output from the caller) is unsupported on compiled members — members handle their own structured returns via `structured_response` in state.
- FilesystemBackend / permissions / skills remain JESSICA-level (deep agent). Members needing file output (research `write_file`) use their own tool implementations.
- Shared infra untouched: Postgres checkpointer/store, Redis rate limiting, `guardrails/input_guard.py`, PII middleware (JESSICA-level), email worker, background-task manager, `/health`.


---

## Rollout Phases

**Phase 1 — Package layout + tool consolidation (no behavior change)**
1. Create `agents/` packages (`__init__.py` × 5).
2. Build `agents/google_workspace/tools.py` consolidating the 7 Google modules + auth/token-store integration; root files become shims re-exporting from it.
3. Sweep imports (`subagent_loader.py`, `background_tasks.py`, `routes/chat.py`, `routes/google_oauth.py`, `schedule_email.py`, `slack_webhook.py`).
4. Acceptance: `python -m py_compile` on all touched files; existing import graph loads; boot smoke (degraded mode OK).

**Phase 2 — Google Workspace member (first fleet member, reference implementation)**
1. `agents/google_workspace/agent.py`: `WorkspaceState(MessagesState)` + validate → route → tools → HITL gate; `make_graph()`.
2. `agents/google_workspace/prompts.md`.
3. Acceptance: `make_graph()` compiles; state schema contains `messages`; graph lists correct tool bindings; dry-run delegation through JESSICA's `task` tool works (auth-valid + auth-invalid paths).

**Phase 3 — Remaining members (comms, project_mgmt, research)**
- Build each per its runtime split (comms: Slack subgraph + email `create_agent`; project_mgmt: Jira chain + Confluence `create_agent`; research: `create_agent`).
- Acceptance per member: compiles; HITL gate present for owned hard-risk tools (comms: sends; google: deletes/shares); dry-run delegation.

**Phase 4 — Registry + loader + orchestration cutover**
1. Rewrite `subagent.yaml` to 4 module-referencing entries; update `subagent_loader.py` to emit `CompiledSubAgent`s.
2. `JESSICA3.5.py` unchanged wiring now receives 4 runnables.
3. Sweep: `guardrails/router.py` (4 names + hints), `chat_utils.py`, `system_prompts.py`, `JESSICA.md`, `AGENTS.md`, `background_tasks.py` strings.
4. `langgraph.json`: add 4 standalone graph entries.
5. Acceptance: loader validation passes (4 unique names, all with `runnable`); JESSICA builds; router classifies into the 4 (+general).

**Phase 5 — Regression & release**
1. Remove the 13 thin specs from `subagent.yaml` (cutover complete); retire root shims once import sweep is green.
2. Full verification plan below; HITL delete/send interrupt test = **release blocker**.
3. Update `GOOGLE_WORKSPACE.md` + docs to reflect `agents/` layout.

**Phase 6 — (Later) Railway split** — each domain as its own Agent-Protocol service; JESSICA attaches remote members via `AsyncSubAgent` (`graph_id`/`url`/`headers`). Out of scope for this refactor.

---

## Verification Plan

```bash
# 1. Syntax gate — every touched file
python -m py_compile agents/google_workspace/tools.py agents/google_workspace/agent.py agents/comms/agent.py agents/project_mgmt/agent.py agents/research/agent.py subagent_loader.py JESSICA3.5.py

# 2. Member compile checks (per domain; via importlib — module name has a dot)
python -c "from agents.google_workspace.agent import make_graph as g; gg=g(); print('google_workspace compiled:', type(gg).__name__)"
python -c "from agents.comms.agent import make_graph as g; print('comms compiled:', type(g()).__name__)"
python -c "from agents.project_mgmt.agent import make_graph as g; print('project_mgmt compiled:', type(g()).__name__)"
python -c "from agents.research.agent import make_graph as g; print('research compiled:', type(g()).__name__)"

# 3. Loader validation — 4 CompiledSubAgent specs, unique names, runnable present
python -c "from subagent_loader import load_subagents; from pathlib import Path; a=load_subagents(Path('subagent.yaml')); assert len(a)==4; assert all('runnable' in s for s in a); assert len({s['name'] for s in a})==4; print('registry OK:', [s['name'] for s in a])"

# 4. Orchestrator smoke — JESSICA3.5.py has a dot; import dynamically (network required for models)
python -c "import importlib.util as u; s=u.spec_from_file_location('j35','JESSICA3.5.py'); m=u.module_from_spec(s); s.loader.exec_module(m); app=m.create_jessicaAI(); print('Jessica initialized with hierarchical fleet')"
```

**Dry-run delegation tests (live):**
- "Find the latest BSE sprint issues and comment status" → routes to `project_mgmt_agent`.
- "Draft an email to <user> with the research summary and schedule it for tomorrow 9am" → `comms_agent` (draft → approve → send; HITL fires on send).
- "Create a folder in Drive, share the Q3 deck with the team" → `google_workspace_agent` (HITL fires on broad share).
- "Research X and write a sourced brief" → `research_agent`.
- Ambiguous/multi-domain → `general` (JESSICA plans across supervisors).


---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| HITL silently lost inside member graphs | Unapproved sends/deletes | Per-member pre-tool interrupt gates imported from `config.HARD_RISK_TOOLS`; interrupt test = release blocker |
| Root import sweep breaks hidden importers | Boot failure at import | Root shims during transition; `py_compile` + import-graph load check per phase; concurrent-editor watch (fastAPI_backend was edited mid-session — re-read before touching) |
| Router/prompt drift (CRIT-03 lesson) | Wrong delegation, invisible members | Router + `_HINTS` + `chat_utils` + `system_prompts` + docs updated in the SAME phase; count assertions in loader validation |
| Concurrent edits to shared files | Merge conflicts | Phases touch disjoint files where possible; `subagent_loader.py`/`JESSICA3.5.py` edits are minimal and isolated to Phase 4 |
| Tool-selection quality with 1 big Google toolset (~30 tools) | Wrong-tool calls | Google member's router node splits productivity vs classroom; prompt lists tool families explicitly; bounded retries on tool node |
| Recursion budget with nested delegation | GraphRecursionError on long runs | Budgets unchanged (conversation 500 / focused 250 / background 500); focused tier only shrinks confident single-domain turns; monitor during dry-runs |
| Email is NOT a Google API service (Resend + SMTP/IMAP) | Mis-grouping | Email lives in `comms`, never in `google_workspace`; if Gmail-as-OAuth arrives later it joins `google_workspace` as a new module |
| `jessica_harness` source absent (only `.pyc`) | Fresh-machine import failure | Confirm source location/installation before deploy; not a blocker locally (Python 3.14) |

## Open Items (decide during build)

1. Exact names: `google_workspace_agent` / `comms_agent` / `project_mgmt_agent` / `research_agent` (current working set).
2. Whether `transition_jira_issue` joins the hard-risk set now (it was deliberately excluded today) — default: keep excluded.
3. Persona names (Morgan/Connie/Jordan/Tyler/Sophie/Alex/…) — fold into member `prompts.md` as flavor or drop.

## Appendix — deepagents 0.7.5 API facts (verified in installed source)

| Type | Fields | Behavior |
|---|---|---|
| `SubAgent` (raw spec) | `name, description, system_prompt, tools, model, middleware, interrupt_on, skills, permissions, response_format` | Harness compiles it; inherits parent state schema; supports caller-driven `response_format` |
| `CompiledSubAgent` | `name, description, runnable` | Used as-is (`with_config` tagged with name); state must contain `messages`; no parent `state_schema` inheritance; no dynamic `response_format` |
| `AsyncSubAgent` | `name, description, graph_id, url?, headers?` | Remote Agent-Protocol server via LangGraph SDK; background task IDs persisted in `async_tasks` state |
| Dispatcher | `graph.py` L647-655 | `if "graph_id" in spec → async; elif "runnable" in spec → compiled; else → raw` |
| `create_deep_agent` params | `model, tools, system_prompt, middleware, subagents, skills, memory, permissions, backend, interrupt_on, response_format, state_schema, context_schema, checkpointer, store, debug, name, cache` | No `harness` kwarg; profiles auto-select per model-id |





