"""
agents/project_mgmt/services/confluence_graph.py
==================================================
Confluence service leaf graph — Connie.

Compiled LangGraph StateGraph that binds all 5 Confluence tools.
No tools in this domain currently appear in HARD_RISK_TOOLS.
"""

from __future__ import annotations

import logging

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import SystemMessage
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages, AnyMessage

from agents.project_mgmt.confluence import CONFLUENCE_TOOLS

_log = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """You are Connie, the Confluence specialist.

Handle all Confluence operations: create pages (storage-format XHTML body),
read page details, update title and/or body, CQL search, add page comments.

Rules:
- Always confirm space_key before creating pages.
- body must be valid Confluence storage-format XHTML (not Markdown).
- Never fabricate page IDs — only use IDs returned by Confluence tools.
- When updating, if only body is changed, use get_confluence_page to retrieve
  the existing title first rather than inventing one.
- If an operation fails, report the exact error.

Output contract:
EXPERIENCE: <action taken + key outcome in ≤20 words>
RESULT: page_id=<ID|->; url=<URL|->; status=<done|failed>
"""


class _ConfluenceState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


class _ConfluenceGraph:
    def __init__(self, model=None, system_prompt: str = ""):
        from loadenv import confluence_agent_model, project_mgmt_agent_model  # type: ignore
        chat_model = model or confluence_agent_model or project_mgmt_agent_model
        if chat_model is None:
            raise RuntimeError("[confluence_service] No model available.")

        _system = system_prompt or _DEFAULT_SYSTEM_PROMPT
        tool_calling_model = chat_model.bind_tools(CONFLUENCE_TOOLS)

        def confluence_agent(state: _ConfluenceState):
            prompt = SystemMessage(content=_system)
            response = tool_calling_model.invoke([prompt] + state["messages"])
            return {"messages": [response]}

        graph = StateGraph(_ConfluenceState)
        graph.add_node("confluence_agent", confluence_agent)
        graph.add_node("tools", ToolNode(CONFLUENCE_TOOLS))
        graph.set_entry_point("confluence_agent")
        graph.add_conditional_edges(
            "confluence_agent",
            tools_condition,
            {"tools": "tools", "__end__": END},
        )
        graph.add_edge("tools", "confluence_agent")

        memory = MemorySaver()
        self.graph = graph.compile(checkpointer=memory)


def create_confluence_graph(*, model=None, system_prompt: str = ""):
    """Entry point — called by project_mgmt forge."""
    return _ConfluenceGraph(model=model, system_prompt=system_prompt).graph


__all__ = ["create_confluence_graph"]
