"""
agents/google_workspace/agent.py
================================
Google Workspace domain supervisor — fleet member #1 (Gemma).

Contained here: the tool suite import, the domain system prompt, the
consolidated model, subagent loader, and skills directory for Gemma.

The LangGraph wiring for this agent is authored by the owner — this file
deliberately contains no graph code.
"""

from __future__ import annotations

from pathlib import Path

from agents.google_workspace.tools import (
    GOOGLE_WORKSPACE_TOOL_MAP,
    GOOGLE_WORKSPACE_TOOLS,
)
from agents.google_workspace.subagent_loader import load_google_workspace_subagents

# ── Model for the Google Workspace agent ──────────────────────────────────────
# Consolidated fleet model built in loadenv via the safe builder
# (GOOGLE_WORKSPACE_AGENT_MODEL_ID / GOOGLE_WORKSPACE_AGENT_API_KEY env vars;
# falls back to None -> harness default on build failure).
try:
    from loadenv import google_workspace_agent_model
except Exception:  # pragma: no cover - a loadenv failure must not break this import
    google_workspace_agent_model = None

AGENT_NAME = "google_workspace_agent"
AGENT_PERSONA = "Gemma"
AGENT_DESCRIPTION = (
    "Gemma — Domain supervisor for ALL Google Workspace + Classroom work (Drive, Docs, "
    "Sheets, Slides, Forms, Calendar, Classroom courses & coursework/grading). "
    "Orchestrates the 8 Google service leaf agents, drafts todos, tracks task completion, "
    "and returns synthesized reports to Jessica."
)

_prompt_file = Path(__file__).parent / "prompts.md"
if _prompt_file.exists():
    SYSTEM_PROMPT = _prompt_file.read_text(encoding="utf-8")
else:
    SYSTEM_PROMPT = """
You are Gemma, the Google Workspace domain supervisor.
You report directly to Jessica 3.5. You orchestrate all work across the 8 Google service leaf agents.
Always draft todos, track task progression, run to completion, tick your scratchpad, and return full reports to Jessica.
"""

GOOGLE_WORKSPACE_SKILLS_DIR = Path(__file__).parent / "skills"

__all__ = [
    "AGENT_NAME",
    "AGENT_PERSONA",
    "AGENT_DESCRIPTION",
    "SYSTEM_PROMPT",
    "GOOGLE_WORKSPACE_TOOLS",
    "GOOGLE_WORKSPACE_TOOL_MAP",
    "GOOGLE_WORKSPACE_SKILLS_DIR",
    "load_google_workspace_subagents",
    "google_workspace_agent_model",
]

# Graph wiring lives in agents/google_workspace/gemma.py
# (create_deep_agent factory: create_gemma_agent)
