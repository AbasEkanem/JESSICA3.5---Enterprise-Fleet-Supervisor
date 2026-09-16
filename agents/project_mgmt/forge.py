"""
agents/project_mgmt/forge.py
==============================
Factory for the Forge deep-agent — the Project Management domain supervisor.

Forge sits at hierarchy level L1, directly below Jessica (L0). It owns
ALL Jira + Confluence work, orchestrates the 2 compiled leaf-agent graphs
(Morgan for Jira, Connie for Confluence), and returns synthesised reports to
Jessica once every todo item in its internal scratchpad is ticked.

Usage (called by agents/project_mgmt/agent.py via make_graph()):
    factory = agents.project_mgmt.forge:create_pm_agent
    runnable = factory()   # no arguments

Build contract:
  * Takes NO arguments.
  * Returns a compiled runnable whose state schema includes `messages`.
  * Owns its own model, system_prompt, subagents, skills, memory, middleware.
  * HITL: NOT set at this level — no tools in PM domain are currently in
    HARD_RISK_TOOLS. If transition_jira_issue is ever added, each leaf graph
    must install interrupt_before=["tools"] at that point.
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

from agents.project_mgmt.agent import (
    SYSTEM_PROMPT,
    PM_SKILLS_DIR,
    PM_TOOLS,
    pm_agent_model,
)
from agents.project_mgmt.services.jira_graph import create_jira_graph
from agents.project_mgmt.services.confluence_graph import create_confluence_graph

_log = logging.getLogger(__name__)

_FORGE_DIR = Path(__file__).parent
_forge_backend = FilesystemBackend(root_dir=_FORGE_DIR, virtual_mode=True)


def create_pm_agent():
    """
    Build and return the compiled Forge deep-agent graph.

    Called with NO arguments by agents/project_mgmt/agent.py make_graph().
    Returns a langgraph CompiledStateGraph satisfying the CompiledSubAgent contract.

    Architecture
    ------------
    Model       : project_mgmt_agent_model (dedicated PM model; falls back to None)
    Tools       : PM_TOOLS — flat union of all Jira + Confluence tools for direct
                  single-call shortcuts when a full leaf graph is overkill.
    System prompt: loaded from agents/project_mgmt/prompts.md at import time.
    Subagents   : 2 compiled leaf graphs — Morgan (Jira) + Connie (Confluence).
    Skills      : 2 SKILL.md directories under agents/project_mgmt/skills/.
    Memory      : FORGE.md pre-seeded into the memory store at build time.
    Middleware  : TodoListMiddleware + ToolRetryMiddleware + ModelRetryMiddleware.
    Backend     : FilesystemBackend (virtual, rooted at agents/project_mgmt/).
    HITL        : NOT set here — no PM tools in HARD_RISK_TOOLS currently.
    """

    _log.info("[forge] Building Forge deep-agent (Project Management supervisor)…")

    # Build the 2 leaf compiled graphs
    jira_graph = create_jira_graph()
    confluence_graph = create_confluence_graph()

    leaf_subagents = [
        {
            "name": "jira_agent",
            "description": (
                "Morgan — Jira specialist. Handles all Jira issue lifecycle: "
                "create, search (JQL or plain English), get details, list project issues, "
                "update fields, transition status, assign users, add/read comments."
            ),
            "runnable": jira_graph,
        },
        {
            "name": "confluence_agent",
            "description": (
                "Connie — Confluence specialist. Handles Confluence page operations: "
                "create pages (storage-format XHTML), read, update title/body, "
                "CQL search, add page comments."
            ),
            "runnable": confluence_graph,
        },
    ]

    _log.info(
        "[forge] Loaded %d leaf subagents: %s",
        len(leaf_subagents),
        [s["name"] for s in leaf_subagents],
    )

    # Memory file: FORGE.md (created below if absent)
    forge_memory = _FORGE_DIR / "FORGE.md"
    memory_args = [str(forge_memory)] if forge_memory.exists() else []

    forge = create_deep_agent(
        model=pm_agent_model,
        system_prompt=SYSTEM_PROMPT,
        tools=PM_TOOLS,
        subagents=leaf_subagents,
        skills=[str(PM_SKILLS_DIR)],
        memory=memory_args,
        backend=_forge_backend,
        middleware=[
            TodoListMiddleware(),
            ToolRetryMiddleware(max_retries=3),
            ModelRetryMiddleware(max_retries=3),
        ],
        name="forge_pm_supervisor",
    )

    _log.info("[forge] Forge deep-agent built successfully.")
    return forge


# Alias
create_forge_agent = create_pm_agent

__all__ = [
    "create_pm_agent",
    "create_forge_agent",
]
