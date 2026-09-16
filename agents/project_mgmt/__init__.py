"""
agents/project_mgmt/__init__.py
================================
Project Management domain supervisor package (Forge).

Exports the agent metadata and consolidated tool suite.
"""

from agents.project_mgmt.agent import (
    AGENT_NAME,
    AGENT_PERSONA,
    AGENT_DESCRIPTION,
    SYSTEM_PROMPT,
    PM_SKILLS_DIR,
    pm_agent_model,
    make_graph,
)
from agents.project_mgmt.tools import (
    PM_TOOLS,
    PM_TOOL_MAP,
    JIRA_TOOLS,
    CONFLUENCE_TOOLS,
)

__all__ = [
    "AGENT_NAME",
    "AGENT_PERSONA",
    "AGENT_DESCRIPTION",
    "SYSTEM_PROMPT",
    "PM_SKILLS_DIR",
    "pm_agent_model",
    "make_graph",
    "PM_TOOLS",
    "PM_TOOL_MAP",
    "JIRA_TOOLS",
    "CONFLUENCE_TOOLS",
]
