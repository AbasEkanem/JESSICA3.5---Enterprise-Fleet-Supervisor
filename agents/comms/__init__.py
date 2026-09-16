"""
agents/comms/__init__.py
========================
Communications domain supervisor package (Relay).

Exports the create_comms_agent factory and the consolidated tool suite.
"""

from agents.comms.agent import (
    AGENT_NAME,
    AGENT_PERSONA,
    AGENT_DESCRIPTION,
    SYSTEM_PROMPT,
    COMMS_SKILLS_DIR,
    comms_agent_model,
    load_comms_subagents,
)
from agents.comms.tools import (
    COMMS_TOOLS,
    SLACK_TOOLS,
    EMAIL_TOOLS,
)

__all__ = [
    "AGENT_NAME",
    "AGENT_PERSONA",
    "AGENT_DESCRIPTION",
    "SYSTEM_PROMPT",
    "COMMS_SKILLS_DIR",
    "comms_agent_model",
    "load_comms_subagents",
    "COMMS_TOOLS",
    "SLACK_TOOLS",
    "EMAIL_TOOLS",
]
