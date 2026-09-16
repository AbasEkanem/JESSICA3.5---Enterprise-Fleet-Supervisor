"""
agents/project_mgmt/tools.py
==============================
Consolidated tool suite for the project_mgmt domain (Forge).

Imports both the Jira and Confluence tool sets, merges them into:
  - PM_TOOLS   : flat list of all LangChain tools for agent binding
  - PM_TOOL_MAP: name → tool dict for fast lookup
  - JIRA_TOOLS : Jira-only subset
  - CONFLUENCE_TOOLS : Confluence-only subset
"""

from __future__ import annotations

from agents.project_mgmt.jira import JIRA_TOOLS
from agents.project_mgmt.confluence import CONFLUENCE_TOOLS

# ── Combined tool lists ───────────────────────────────────────────────────────
PM_TOOLS: list = JIRA_TOOLS + CONFLUENCE_TOOLS
PM_TOOL_MAP: dict = {t.name: t for t in PM_TOOLS}

__all__ = [
    "PM_TOOLS",
    "PM_TOOL_MAP",
    "JIRA_TOOLS",
    "CONFLUENCE_TOOLS",
]
