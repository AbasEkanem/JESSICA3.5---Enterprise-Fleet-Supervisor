"""
agents/comms/relay.py
======================
Factory for the Relay deep-agent — the Communications domain supervisor.

Relay sits at hierarchy level L1, directly below Jessica (L0). She owns
ALL Slack + Email work, orchestrates the 2 compiled leaf-agent graphs loaded
from subagents.yaml, and returns synthesised reports to Jessica once every
todo item in her internal scratchpad is ticked.

Usage (called by root subagent_loader.py via the deep_agent branch):
    factory = agents.comms.relay:create_comms_agent
    runnable = factory()   # no arguments

Build contract:
  * Takes NO arguments.
  * Returns a compiled runnable whose state schema includes `messages`.
  * Owns its own model, system_prompt, subagents, skills, memory, middleware.
  * HITL gated inside each leaf graph via interrupt_before=[...].
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

from agents.comms.agent import (
    SYSTEM_PROMPT,
    COMMS_SKILLS_DIR,
    COMMS_TOOLS,
    comms_agent_model,
    load_comms_subagents,
)

_log = logging.getLogger(__name__)

_RELAY_DIR = Path(__file__).parent
_relay_backend = FilesystemBackend(root_dir=_RELAY_DIR, virtual_mode=True)


def create_comms_agent():
    """
    Build and return the compiled Relay deep-agent graph.

    Called with NO arguments by the root subagent_loader.py `deep_agent` branch.
    Returns a langgraph CompiledStateGraph satisfying the CompiledSubAgent contract.

    Architecture
    ------------
    Model       : comms_agent_model (dedicated comms model; falls back to None)
    Tools       : COMMS_TOOLS — flat union of all Slack + Email tools for direct
                  single-call shortcuts when a full leaf graph is overkill.
    System prompt: loaded from agents/comms/prompts.md at import time.
    Subagents   : 2 compiled leaf graphs from subagents.yaml.
    Skills      : 2 SKILL.md directories under agents/comms/skills/.
    Memory      : RELAY.md pre-seeded into the memory store at build time.
    Middleware  : TodoListMiddleware + ToolRetryMiddleware + ModelRetryMiddleware.
    Backend     : FilesystemBackend (virtual, rooted at agents/comms/).
    HITL        : NOT set here — gated inside each leaf via interrupt_before.
    """

    _log.info("[relay] Building Relay deep-agent (Communications supervisor)…")

    leaf_subagents = load_comms_subagents()
    _log.info(
        "[relay] Loaded %d leaf subagents: %s",
        len(leaf_subagents),
        [s["name"] for s in leaf_subagents],
    )

    relay = create_deep_agent(
        model=comms_agent_model,
        system_prompt=SYSTEM_PROMPT,
        tools=COMMS_TOOLS,
        subagents=leaf_subagents,
        skills=[str(COMMS_SKILLS_DIR)],
        memory=[str(_RELAY_DIR / "RELAY.md")],
        backend=_relay_backend,
        middleware=[
            TodoListMiddleware(),
            ToolRetryMiddleware(max_retries=3),
            ModelRetryMiddleware(max_retries=3),
        ],
        name="relay_comms_supervisor",
    )

    _log.info("[relay] Relay deep-agent built successfully.")
    return relay


# Backward-compatible alias
create_relay_agent = create_comms_agent

__all__ = [
    "create_comms_agent",
    "create_relay_agent",
]
