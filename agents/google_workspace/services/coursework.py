"""
agents/google_workspace/services/coursework.py
==============================================
Coursework & grading (Juliet) service graph — fleet leaf. Pure LangGraph wiring
is authored by the owner. This template only wires the contract surface: the
coursework toolset and the juliet model.

Bound to the google_workspace supervisor via:
    {"name": "coursework_service", "description": AGENT_DESCRIPTION,
     "runnable": make_coursework_graph()}
"""

from __future__ import annotations

from ..tools import JULIET_COURSEWORK_TOOLS
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from langchain.messages import SystemMessage

try:
    from loadenv import juliet_agent_model
except Exception:  # pragma: no cover - loadenv failure must not break imports
    juliet_agent_model = None

AGENT_NAME = "coursework_service"
AGENT_DESCRIPTION = (
    "Google Classroom work & grading: assignments (create/list/update/delete, "
    "delete HITL-gated), submissions, grading, returns, announcements, topics."
)

COURSEWORK_SYSTEM_PROMPT = """\
You are the Google Classroom coursework & grading specialist.

SCOPE
- Assignments (create/list/update/delete), student submissions, grading,
  returning work, announcements, course topics. Leaf agent — complete the task.

OPERATING RULES
1. AUTH FIRST: no connected account → friendly "connect your Google account".
2. DELETE COURSEWORK = HITL-GATED: permanent removal of student-visible work
   requires human approval. Never routine.
3. GRADING TOUCHES REAL RECORDS: review the submission first; grade only what
   the request specifies; never alter grades beyond the instruction. Return
   work only when asked (returning notifies the student).
4. ANNOUNCEMENTS BROADCAST to every student — quote the final text in your
   report before considering the task done.
5. TOPICS: create/list course topics here (structural, low risk).
6. BOUNDED EXECUTION: retry once; clean errors, no tracebacks.
7. COMPLETE REPORT: course/assignment/submission IDs, grades set, who was
   notified.
"""

__all__ = [
    "AGENT_NAME",
    "AGENT_DESCRIPTION",
    "COURSEWORK_SYSTEM_PROMPT",
    "JULIET_COURSEWORK_TOOLS",
    "juliet_agent_model",
]

# define the tools
_tools = JULIET_COURSEWORK_TOOLS

# set the memory 
memory = InMemorySaver()
# create the state of the graph
class Agent_state(MessagesState):
    pass
# create the agentgraph class
class AgentGraph:
    def __init__(self, model=None, tools = None, system_prompt = COURSEWORK_SYSTEM_PROMPT):
        self.model = juliet_agent_model
        self.system_prompt = system_prompt or COURSEWORK_SYSTEM_PROMPT
        tools = _tools 
        self.tools = {t.name: t for t in tools}
        chat_model = self.model.bind_tools(tools)
        # create the agent node
        def course_agent(state:Agent_state):
            # create the system prompt
            prompt = SystemMessage(content=self.system_prompt)
            # create the tool response as the ai message
            response = chat_model.invoke([prompt] + state["messages"])
            # return the response as the update to the state
            return{"messages":[response]}
        # create the graph
        course_graph = StateGraph(Agent_state)
        # create the nodes
        course_graph.add_node("course_agent", course_agent)
        course_graph.add_node("tools", ToolNode(tools))
        # create the edges: the workflow
        course_graph.set_entry_point("course_agent")
        course_graph.add_conditional_edges(
            "course_agent",
            tools_condition,
            # create the routing condition
            {"tools":"tools", "__end__": END}

        )
        # P1 FIX: same missing-edge defect as services/docs.py — the graph ended
        # right after the tool node and the model never consumed the tool result.
        course_graph.add_edge("tools", "course_agent")
    # compile the graph
        self.course_graph = course_graph.compile(checkpointer=memory, interrupt_before=["tools"])

# create the course graph
def create_course_graph(*, model=None, system_prompt: str = ""):
    """Entry point the google_workspace supervisor binds as its subagent."""
    return AgentGraph(model, _tools, system_prompt).course_graph
