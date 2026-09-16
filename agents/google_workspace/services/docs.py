"""
agents/google_workspace/services/docs.py
========================================
Docs service graph — fleet leaf. Pure LangGraph wiring is authored by the
owner. This template only wires the contract surface: the docs toolset and
the docs model.

Bound to the google_workspace supervisor via:
    {"name": "docs_service", "description": AGENT_DESCRIPTION,
     "runnable": make_docs_graph()}
"""

from __future__ import annotations

from ..tools import DOCS_TOOLS
from langchain.messages import SystemMessage
from langgraph.graph.message import AnyMessage, add_messages
from typing import TypedDict, Annotated
from langgraph.prebuilt import tools_condition, ToolNode
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, END
try:
    from loadenv import docs_agent_model
except Exception:  # pragma: no cover - loadenv failure must not break imports
    docs_agent_model = None

AGENT_NAME = "docs_service"
AGENT_DESCRIPTION = (
    "Google Docs operations: create, read, append, insert at index, find & "
    "replace, delete ranges, style text, insert page breaks."
)

DOCS_SYSTEM_PROMPT = """\
You are the Google Docs specialist.

SCOPE
- Create documents, read content, append/insert text, find & replace, delete
  ranges, style text, insert page breaks. Leaf agent — complete the task.

OPERATING RULES
1. AUTH FIRST: no connected account → friendly "connect your Google account".
2. READ BEFORE EDIT: insertion indices and ranges come from `read_google_doc`.
   Never guess indices — a wrong index corrupts content silently.
3. REPLACE vs DELETE+INSERT: prefer `replace_text_in_doc` for substitutions;
   use range deletes only when you know the exact bounds.
4. STYLING: style ranges taken from the read; hex colors (e.g. "#1F2937").
5. BOUNDED EXECUTION: retry once; clean errors, no tracebacks.
6. COMPLETE REPORT: document ID + webViewLink, what was written/changed.
"""

__all__ = [
    "AGENT_NAME",
    "AGENT_DESCRIPTION",
    "DOCS_SYSTEM_PROMPT",
    "DOCS_TOOLS",
    "docs_agent_model",
]
_tools = DOCS_TOOLS
_memory = InMemorySaver()

class state_graph(TypedDict):
    messages : Annotated[list[AnyMessage], add_messages]
   
# create the agent graph class
class agent_graph:
    def __init__(self, model = None, tools = None, prompt = DOCS_SYSTEM_PROMPT):
        self.model = model or docs_agent_model
        self.prompt = prompt or DOCS_SYSTEM_PROMPT
        tools = tools or _tools
        self.tools = {t.name: t for t in tools}
        chat_model = self.model.bind_tools(tools)

        def docs_agent(state: state_graph):
            system_prompt = SystemMessage(content=self.prompt)
            response = chat_model.invoke([system_prompt] + state["messages"])
            return{"messages": [response]}
        # create the graph
        graph_builder = StateGraph(state_graph)
        graph_builder.add_node("docs_agent", docs_agent)
        graph_builder.add_node("tools", ToolNode(tools))
        graph_builder.set_entry_point("docs_agent")
        graph_builder.add_conditional_edges(
            "docs_agent",
            tools_condition,
            {
                "tools" :"tools",
                "__end__":END
            }
        )
        # P1 FIX: this edge was missing. Without it the graph ran the tool node and
        # then TERMINATED — the model never saw the tool result, so any multi-step
        # task (call tool -> read result -> answer) silently ended after the first
        # tool call. Matches services/calendar.py and services/classroom.py.
        graph_builder.add_edge("tools", "docs_agent")
        self.graph_builder = graph_builder.compile(checkpointer=_memory, interrupt_before=["tools"])


def create_docs_graph(*, model=None, system_prompt: str = ""):
    """Entry point the google_workspace supervisor binds as its subagent."""
    return agent_graph(model, _tools, system_prompt).graph_builder