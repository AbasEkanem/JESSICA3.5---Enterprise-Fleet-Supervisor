"""
agents/google_workspace/services/classroom.py
=============================================
Classroom (courses & rosters) service graph — fleet leaf. Pure LangGraph wiring
is authored by the owner. This template only wires the contract surface: the
classroom-courses toolset and the classroom model.

Bound to the google_workspace supervisor via:
    {"name": "classroom_service", "description": AGENT_DESCRIPTION,
     "runnable": make_classroom_graph()}
"""

from __future__ import annotations

from ..tools import CLASSROOM_COURSES_TOOLS

# ── LangGraph primitives (same import set as the completed calendar graph) ────
from langchain_core.messages import SystemMessage
from langgraph.graph import (
    StateGraph,
    MessagesState,
    END,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolNode, tools_condition

try:
    from loadenv import google_classroom_agent_model
except Exception:  # pragma: no cover - loadenv failure must not break imports
    google_classroom_agent_model = None

AGENT_NAME = "classroom_service_agent"
AGENT_DESCRIPTION = (
    "Google Classroom structure: create/list/get/update/delete courses "
    "(delete HITL-gated), student/teacher rosters, invites."
)

CLASSROOM_SYSTEM_PROMPT = """\
You are the Google Classroom structure specialist (courses & rosters).

SCOPE
- Create, list, get, update, and delete courses; manage student/teacher
  rosters; send invitations. Leaf agent — complete the task.

OPERATING RULES
1. AUTH FIRST: no connected account → friendly "connect your Google account".
2. DELETE COURSE = HITL-GATED: `delete_course` permanently removes a course
   and all its work — it requires human approval. Never routine.
3. ROSTER CHANGES TOUCH REAL PEOPLE: add/remove/invite only when explicitly
   requested; always name the affected users in your report.
4. STAY IN LANE: assignments, submissions, grading, announcements, and topics
   belong to the coursework leaf — do not attempt them here.
5. BOUNDED EXECUTION: retry once; clean errors, no tracebacks.
6. COMPLETE REPORT: course IDs + links, roster deltas (who added/removed).
"""

__all__ = [
    "AGENT_NAME",
    "AGENT_DESCRIPTION",
    "CLASSROOM_SYSTEM_PROMPT",
    "CLASSROOM_COURSES_TOOLS",
    "google_classroom_agent_model",
]
# set the memory
memory = InMemorySaver()
# set the tools 

_tools = CLASSROOM_COURSES_TOOLS
# create a class room ai agent using the google classroom
# to set up a graph we first define the state of the graph
class Classroom_State(MessagesState):
    pass

# next we define the nodes - the execution points in the graph
def classroom_agent(state: Classroom_State):
    # grab the system prompt 
    prompt = SystemMessage(content=CLASSROOM_SYSTEM_PROMPT)
    # set the chat_model 
    chat_model = google_classroom_agent_model.bind_tools(_tools)
    # create the ai response as the tool  response
    response = chat_model.invoke([prompt] + state["messages"])
    # return the update to the state key
    return{"messages":[response]}

# create the graph builder
graph_builder = StateGraph(Classroom_State)
# add the nodes
graph_builder.add_node("classroom_agent", classroom_agent)
graph_builder.add_node("classroom_tools", ToolNode(_tools))
# create the edges : the connection flow
graph_builder.set_entry_point("classroom_agent")
graph_builder.add_conditional_edges(
    "classroom_agent",
    tools_condition,
    # create the routing logic
    {"tools":"classroom_tools", "__end__": END}
)
graph_builder.add_edge("classroom_tools", "classroom_agent")
# compile the graph
compiled_graph = graph_builder.compile(checkpointer=memory, interrupt_before=["classroom_tools"])
# create the classroom agent
def create_classroom_agent():
    return compiled_graph