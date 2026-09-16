# GEMMA WIRING — activation checklist

## 1. DONE — loader branch (`subagent_loader.py`, additive, verified)

A registry entry can now name a factory returning an **already-compiled** graph:

    name: <name>
    description: <what the orchestrator routes on>
    runtime: deep_agent
    module: package.module:factory        # factory takes NO args, returns a runnable

Registered as a deepagents `CompiledSubAgent` = `{"name","description","runnable"}`.
No `prompt_file` needed (the graph owns its prompt); `model`/`tools`/`permissions`/
`recursion_limit` are ignored on this path.

Verified via `scratch/_tmp_probe.yaml` against a REAL factory (`agents.google_workspace
.services.sheets:create_sheets_graph`):
`[('tmp_deep_probe', True, 'CompiledStateGraph'), ('tmp_inline_probe', False, 'no-runnable')]`
and the live registry unchanged: `REAL count: 13`.
Gotcha found by that test: a deep_agent entry first died at
`system_prompt = doc["system_prompt"]` (`KeyError`) because the branch sat *after* prompt
resolution — fixed with an `elif _is_deep_agent: system_prompt = ""` guard.

## 2. WAITING ON

1. **`agents/google_workspace/gemma.py` missing.** Contract:
   `def create_gemma_agent():` — no args, returns `create_deep_agent(...)` whose state
   includes `messages`. Suggested body: `model=google_workspace_agent_model`,
   `system_prompt=SYSTEM_PROMPT`, `subagents=load_google_workspace_subagents()`,
   `skills=[str(GOOGLE_WORKSPACE_SKILLS_DIR)]`. Parent reads `structured_response` if
   set, else the last non-empty `AIMessage`.
2. **Decision 14 or 6?** Add Gemma alongside the 8 flat Google agents (14) or replace
   them (6). Recommended: **14 first** — additive, reversible, and the router's existing
   hints preserve current behaviour until you switch.
3. **`.env` lacks `GOOGLE_WORKSPACE_AGENT_MODEL_ID`/`_API_KEY`** → model is `None`
   (loader logged `subagent.missing_api_key ... GOOGLE_WORKSPACE_AGENT_API_KEY`).
   All 8 leaf model keys exist.

## 3. APPLY ONCE gemma.py EXISTS — variant A (14)

`subagent.yaml`, new document after `juliet_agent`:

    ---

    name: google_workspace_agent
    description: >
      You are Gemma, Jessica's Google Workspace domain supervisor. Owns ALL Drive,
      Docs, Sheets, Slides, Forms, Calendar and Classroom work — files/folders,
      documents, spreadsheets, decks, forms, events, courses/rosters, coursework
      and grading — by planning a todo scratchpad and dispatching its 8 leaves.
    model: google_workspace_agent_model
    runtime: deep_agent
    module: agents.google_workspace.gemma:create_gemma_agent

`guardrails/router.py` (4 spots): docstring list + count; `SubagentType` Literal;
`_HINTS`; `_ROUTER_SYSTEM` ("13 specialized subagents" → 14, add item 14).

root `AGENTS.md` (**this is Jessica's LIVE system prompt** — `system_prompts.py:32`):
table row for Gemma; `## HARD LIMITS` "outside the 13 names" → 14; `**Routing:**` line
mentions Gemma for multi-service Google pipelines.

Variant B (6): same, plus delete the 8 Google documents from `subagent.yaml`, drop their
Literal/hint entries, recompute every count. No fallback if Gemma misbehaves.

## 4. HITL — CRITICAL (`deepagents/graph.py:485-503`)

- "This config always applies to the main agent."
- "**Declarative `SubAgent` specs inherit the top-level `interrupt_on` config by default.**"
- "**`CompiledSubAgent` runnables do not inherit top-level `interrupt_on`; configure
  human-in-the-loop behavior inside the compiled runnable itself.**"

Once Gemma is nested: Gemma inherits nothing from Jessica, and her 8 leaves (also
CompiledSubAgents) inherit nothing from her → `delete_drive_file`, `trash_drive_file`,
`share_drive_file_with_anyone`, `bulk_share_drive_files`, `delete_course`,
`delete_coursework` **stop being gated**. They ARE gated today, via inheritance into the
flat declarative specs (`graph.py:720`).

- **Route A (keep authored graphs):** gate inside each leaf, where tools are bound —
  `create_agent(..., middleware=[HumanInTheLoopMiddleware(interrupt_on={...})])`.
  docs/calendar/classroom/coursework use `StateGraph.compile()`, which only accepts
  `interrupt_before`/`interrupt_after` — migrate them to `create_agent` or scope their
  node interrupt to a dedicated gated node (currently it fires on EVERY tool call,
  including reads).
- **Route B (simpler):** declare Gemma's leaves as **raw** specs (`model`+`tools`+
  `system_prompt`) so they inherit Gemma's `interrupt_on`; costs the custom graph shapes.

Caveat: `interrupt_on` "requires a checkpointer", and all 8 leaves use `InMemorySaver()`
(per-process). Nested interrupt + resume across Jessica's checkpointer needs live testing.

## 5. VERIFY AFTER ACTIVATION

    python -c "from pathlib import Path; from subagent_loader import load_subagents; \
    b=load_subagents(Path('subagent.yaml')); print(len(b)); \
    print([x.get('name') for x in b]); print([('runnable' in x) for x in b])"

Expect 14 names incl. `google_workspace_agent` with `runnable=True`, no `KeyError`; then
`len(load_google_workspace_subagents()) == 8`; then prove a HARD_RISK call inside a leaf
still raises an interrupt.