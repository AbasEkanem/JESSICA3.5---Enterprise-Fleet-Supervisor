"""
agents/project_mgmt/services/jira_graph.py
============================================
Jira service leaf graph — Morgan.

Compiled LangGraph StateGraph that binds all 11 Jira tools.
No tools in this domain currently appear in HARD_RISK_TOOLS (transition_jira_issue
was deliberately excluded per the implementation plan — issue 282). If that
decision changes, add interrupt_before=["tools"] with the filtered tool name set
and update config.HARD_RISK_TOOLS accordingly.
"""

from __future__ import annotations

import logging

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import SystemMessage
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages, AnyMessage

from agents.project_mgmt.jira import JIRA_TOOLS

_log = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """You are Morgan, the Jira specialist.

Handle all Jira operations: create issues/subtasks, search using JQL or plain
English, get issue details, list project issues, update fields, transition
status, assign users, add comments, read comments.

Rules:
- When creating issues, always confirm project_key with the user if unspecified.
- When transitioning issues, name the target status exactly (e.g. "In Progress").
- Resolve ambiguous assignees with search_jira_users before assigning.
- Never fabricate issue keys — only use keys returned by Jira tools.
- If an operation fails, report the exact error; do not retry silently.

Output contract:
EXPERIENCE: <action taken + key outcome in ≤20 words>
RESULT: key=<ISSUE_KEY|->; status=<done|failed>
"""


class _JiraState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


class _JiraGraph:
    def __init__(self, model=None, system_prompt: str = ""):
        from loadenv import jira_agent_model, project_mgmt_agent_model  # type: ignore
        chat_model = model or jira_agent_model or project_mgmt_agent_model
        if chat_model is None:
            raise RuntimeError("[jira_service] No model available.")

        _system = system_prompt or _DEFAULT_SYSTEM_PROMPT
        tool_calling_model = chat_model.bind_tools(JIRA_TOOLS)

        def jira_agent(state: _JiraState):
            prompt = SystemMessage(content=_system)
            response = tool_calling_model.invoke([prompt] + state["messages"])
            return {"messages": [response]}

        graph = StateGraph(_JiraState)
        graph.add_node("jira_agent", jira_agent)
        graph.add_node("tools", ToolNode(JIRA_TOOLS))
        graph.set_entry_point("jira_agent")
        graph.add_conditional_edges(
            "jira_agent",
            tools_condition,
            {"tools": "tools", "__end__": END},
        )
        graph.add_edge("tools", "jira_agent")

        memory = MemorySaver()
        # No HARD_RISK_TOOLS in Jira domain yet — no interrupt_before required.
        # If transition_jira_issue is promoted to hard-risk, add:
        #   interrupt_before=["tools"] with conditional HITL check.
        self.graph = graph.compile(checkpointer=memory)


def create_jira_graph(*, model=None, system_prompt: str = ""):
    """Entry point — called by project_mgmt forge."""
    return _JiraGraph(model=model, system_prompt=system_prompt).graph


__all__ = ["create_jira_graph"]
