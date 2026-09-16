"""
agents/research
===============
Research domain workspace for Jessica 3.5 — Scout.
"""

from agents.research.agent import (
    AGENT_DESCRIPTION,
    AGENT_NAME,
    AGENT_PERSONA,
    RESEARCH_SKILLS_DIR,
    RESEARCH_TOOL_MAP,
    RESEARCH_TOOLS,
    SYSTEM_PROMPT,
    make_graph,
    research_agent_model,
)
from agents.research.tools import (
    calculate_future_datetime,
    exa_search,
    get_current_datetime,
    linkup_search,
    tavily_search,
    think_tool,
    write_file,
)

__all__ = [
    "AGENT_NAME",
    "AGENT_PERSONA",
    "AGENT_DESCRIPTION",
    "SYSTEM_PROMPT",
    "RESEARCH_TOOLS",
    "RESEARCH_TOOL_MAP",
    "RESEARCH_SKILLS_DIR",
    "research_agent_model",
    "make_graph",
    "tavily_search",
    "exa_search",
    "linkup_search",
    "think_tool",
    "write_file",
    "get_current_datetime",
    "calculate_future_datetime",
]
