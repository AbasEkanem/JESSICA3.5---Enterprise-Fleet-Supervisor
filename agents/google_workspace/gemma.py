"""
agents/google_workspace/gemma.py
=================================
Factory for the Gemma deep-agent — the Google Workspace domain supervisor.

Gemma sits at hierarchy level L1, directly below Jessica (L0). She owns
ALL Google Workspace + Classroom work, orchestrates the 8 compiled leaf-
agent graphs loaded from subagents.yaml, and returns synthesised reports
to Jessica once every todo item in her internal scratchpad is ticked.

Usage (called by the root subagent_loader.py via the deep_agent branch):
    factory = agents.google_workspace.gemma:create_gemma_agent
    runnable = factory()   # no arguments
    # runnable is a CompiledStateGraph and satisfies CompiledSubAgent contract

Build contract:
  * Takes NO arguments — the root loader calls factory() with no args.
  * Returns a compiled runnable whose state schema includes `messages`.
  * Owns its own model, system_prompt, subagents, skills, and middleware —
    the parent (Jessica) passes nothing into these at dispatch time.
  * HITL (interrupt_on) is NOT inherited through CompiledSubAgent nesting.
    High-risk tools are gated inside each leaf graph via interrupt_before=[...].
  * The skills list tells create_deep_agent to surface SKILL.md files to
    Gemma's context so she can follow domain-specific operating procedures.
"""

from __future__ import annotations

import logging
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain.agents.middleware import (
    ToolRetryMiddleware,
    ModelRetryMiddleware,
    TodoListMiddleware,
)

from agents.google_workspace.agent import (
    SYSTEM_PROMPT,
    GOOGLE_WORKSPACE_SKILLS_DIR,
    GOOGLE_WORKSPACE_TOOLS,
    google_workspace_agent_model,
    load_google_workspace_subagents,
)

_log = logging.getLogger(__name__)

# ── Runtime directory (same folder as this file) ─────────────────────────────
_GEMMA_DIR = Path(__file__).parent

# ── FilesystemBackend: virtual; root is the workspace agent folder ────────────
# virtual_mode=True means Gemma gets a sandboxed view — she cannot escape the
# agents/google_workspace/ tree. If the project root is ever needed (e.g. to
# read a shared template), set root_dir=Path(__file__).parent.parent.parent.
_gemma_backend = FilesystemBackend(root_dir=_GEMMA_DIR, virtual_mode=True)


def create_gemma_agent():
    """
    Build and return the compiled Gemma deep-agent graph.

    Called with NO arguments by the root subagent_loader.py `deep_agent`
    branch.  Returns a langgraph CompiledStateGraph that satisfies the
    CompiledSubAgent contract expected by create_deep_agent(subagents=...).

    Architecture
    ------------
    Model       : google_workspace_agent_model (dedicated workspace model;
                  falls back to None → harness default if env var absent)
    Tools       : GOOGLE_WORKSPACE_TOOLS — the flat union of all 7 service
                  domains.  Gemma carries these for direct (non-leaf) calls
                  when a single tool is faster than a full leaf invocation.
    System prompt: loaded from agents/google_workspace/prompts.md at import
                  time; contains the full Gemma operating contract.
    Subagents   : 8 compiled leaf graphs from subagents.yaml, each a
                  CompiledSubAgent dict {name, description, runnable}.
    Skills      : 5 SKILL.md directories under agents/google_workspace/skills/
                  surfaced to Gemma so she follows domain procedures.
    Middleware  : TodoListMiddleware  — writes + ticks scratchpad per turn.
                  ToolRetryMiddleware — auto-retries transient tool errors.
                  ModelRetryMiddleware— auto-retries LLM errors (rate-limits).
    Backend     : FilesystemBackend (virtual, rooted at the workspace agent dir)
    HITL        : NOT set here. Each leaf graph gates its own HARD_RISK_TOOLS
                  via interrupt_before. Jessica (L0) owns the top-level gate.
    """

    _log.info("[gemma] Building Gemma deep-agent (Google Workspace supervisor)…")

    # Load + compile the 8 leaf graphs each time the factory is called so that
    # build errors are surfaced early and each leaf gets a fresh InMemorySaver.
    leaf_subagents = load_google_workspace_subagents()
    _log.info(
        "[gemma] Loaded %d leaf subagents: %s",
        len(leaf_subagents),
        [s["name"] for s in leaf_subagents],
    )

    gemma = create_deep_agent(
        # ── Intelligence ─────
        model=google_workspace_agent_model,
        system_prompt=SYSTEM_PROMPT,
        # ── Direct tool access (single-call shortcuts; leaves used for complex ops)
        tools=GOOGLE_WORKSPACE_TOOLS,
        # ── Leaf agent fleet (8 compiled CompiledSubAgent graphs) ──
        subagents=leaf_subagents,
        # ── Skills: SKILL.md files surfaced into Gemma's context 
        skills=[str(GOOGLE_WORKSPACE_SKILLS_DIR)],
        memory=[str(_GEMMA_DIR / "GEMMA.md")],
        # ── Durable execution environment ─
        backend=_gemma_backend,
        # ── Orchestration middleware 
        middleware=[
            TodoListMiddleware(),
            ToolRetryMiddleware(max_retries=3),
            ModelRetryMiddleware(max_retries=3),
        ],
        # name is injected so the compiled graph appears as "Gemma" in traces.
        name="gemma_google_workspace_supervisor",
    )

    _log.info("[gemma] Gemma deep-agent built successfully.")
    return gemma


# Backward-compatible alias ─
create_google_workspace_agent = create_gemma_agent

__all__ = [
    "create_gemma_agent",
    "create_google_workspace_agent",
]
