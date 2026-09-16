"""
agents/comms/agent.py
=====================
Communications domain supervisor — Relay.

Contained here: tool suite import, domain system prompt, consolidated model,
subagent loader, and skills directory for Relay.

Graph wiring lives in agents/comms/relay.py (create_comms_agent factory).
"""

from __future__ import annotations

from pathlib import Path

from agents.comms.tools import COMMS_TOOLS, COMMS_TOOL_MAP
from agents.comms.subagent_loader import load_comms_subagents

# ── Model ─────────────────────────────────────────────────────────────────────
try:
    from loadenv import comms_agent_model
except Exception:
    comms_agent_model = None  # pragma: no cover

AGENT_NAME = "comms_agent"
AGENT_PERSONA = "Relay"
AGENT_DESCRIPTION = (
    "Relay — Domain supervisor for ALL communications work: Slack (messages, threads, "
    "DMs, reactions, channel ops) and Email (send, schedule, read inbox, search, sent log). "
    "Orchestrates the 2 comms leaf agents, drafts todos, tracks task completion, "
    "and returns synthesized reports to Jessica."
)

# ── System prompt ─────────────────────────────────────────────────────────────
_prompt_file = Path(__file__).parent / "prompts.md"
if _prompt_file.exists():
    SYSTEM_PROMPT = _prompt_file.read_text(encoding="utf-8")
else:
    SYSTEM_PROMPT = (
        "You are Relay, the Communications domain supervisor. "
        "You report directly to Jessica 3.5. You orchestrate all Slack and Email work "
        "via the 2 comms leaf agents. Always draft todos, track progression, run to "
        "completion, tick your scratchpad, and return full reports to Jessica."
    )

COMMS_SKILLS_DIR = Path(__file__).parent / "skills"

__all__ = [
    "AGENT_NAME",
    "AGENT_PERSONA",
    "AGENT_DESCRIPTION",
    "SYSTEM_PROMPT",
    "COMMS_TOOLS",
    "COMMS_TOOL_MAP",
    "COMMS_SKILLS_DIR",
    "load_comms_subagents",
    "comms_agent_model",
]

# Graph wiring lives in agents/comms/relay.py
# (create_deep_agent factory: create_comms_agent)
