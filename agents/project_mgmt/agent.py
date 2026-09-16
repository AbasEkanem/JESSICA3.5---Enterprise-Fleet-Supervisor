"""
agents/project_mgmt/agent.py
==============================
Project Management domain supervisor — Forge.

Metadata, system prompt, model, and make_graph() factory for the project_mgmt
domain member. The actual graph wiring lives in agents/project_mgmt/forge.py.
"""

from __future__ import annotations

from pathlib import Path

from agents.project_mgmt.tools import PM_TOOLS, PM_TOOL_MAP

# ── Model ─────────────────────────────────────────────────────────────────────
try:
    from loadenv import project_mgmt_agent_model  # type: ignore
except Exception:
    project_mgmt_agent_model = None  # pragma: no cover

pm_agent_model = project_mgmt_agent_model

# ── Identity ──────────────────────────────────────────────────────────────────
AGENT_NAME = "project_mgmt_agent"
AGENT_PERSONA = "Forge"
AGENT_DESCRIPTION = (
    "Forge — Domain supervisor for ALL project management work: Jira (create, search, "
    "update, transition, assign, comment on issues) and Confluence (create/read/update "
    "pages, CQL search, page comments). Orchestrates Jira and Confluence leaf agents, "
    "drafts todos, tracks task completion, and returns synthesized reports to Jessica."
)

# ── System prompt ─────────────────────────────────────────────────────────────
_prompt_file = Path(__file__).parent / "prompts.md"
if _prompt_file.exists():
    SYSTEM_PROMPT = _prompt_file.read_text(encoding="utf-8")
else:
    SYSTEM_PROMPT = (
        "You are Forge, the Project Management domain supervisor. "
        "You report directly to Jessica 3.5. You orchestrate all Jira and Confluence work "
        "via the 2 project-management leaf agents. Always draft todos, track progression, "
        "run to completion, tick your scratchpad, and return full reports to Jessica."
    )

PM_SKILLS_DIR = Path(__file__).parent / "skills"


# ── Graph factory ─────────────────────────────────────────────────────────────
def make_graph():
    """Compile and return the project_mgmt CompiledStateGraph.

    Imports forge.py lazily to avoid circular imports at module load time.
    Returns a compiled LangGraph StateGraph that satisfies the CompiledSubAgent
    contract (state schema must contain `messages`).
    """
    from agents.project_mgmt.forge import create_pm_agent
    return create_pm_agent()


__all__ = [
    "AGENT_NAME",
    "AGENT_PERSONA",
    "AGENT_DESCRIPTION",
    "SYSTEM_PROMPT",
    "PM_TOOLS",
    "PM_TOOL_MAP",
    "PM_SKILLS_DIR",
    "pm_agent_model",
    "make_graph",
]
