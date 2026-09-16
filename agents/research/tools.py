"""
agents/research/tools.py
==========================
Consolidated tool suite for the Research domain (Scout / Sophie).

Includes:
- Multi-engine search: tavily_search, exa_search, linkup_search
- Research utilities: think_tool, write_file
- Temporal grounding: get_current_datetime, calculate_future_datetime
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from agents.research.websearch import (
    tavily_search,
    exa_search,
    linkup_search,
    think_tool,
    write_file,
    SEARCH_TOOLS,
)
from agents.research.datetime_tools import (
    get_current_datetime,
    calculate_future_datetime,
    DATETIME_TOOLS,
)

RESEARCH_TOOLS: list[BaseTool] = SEARCH_TOOLS + DATETIME_TOOLS

RESEARCH_TOOL_MAP: dict[str, BaseTool] = {t.name: t for t in RESEARCH_TOOLS}

__all__ = [
    "tavily_search",
    "exa_search",
    "linkup_search",
    "think_tool",
    "write_file",
    "get_current_datetime",
    "calculate_future_datetime",
    "SEARCH_TOOLS",
    "DATETIME_TOOLS",
    "RESEARCH_TOOLS",
    "RESEARCH_TOOL_MAP",
]
