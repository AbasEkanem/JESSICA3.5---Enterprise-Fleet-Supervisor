"""
agents/google_workspace/services/calendar.py
============================================
Calendar service graph — fleet leaf. Pure LangGraph wiring is authored by the
owner. This template only wires the contract surface: the calendar toolset and
the calendar model.

Bound to the google_workspace supervisor via:
    {"name": "calendar_service", "description": AGENT_DESCRIPTION,
     "runnable": make_calendar_graph()}
"""


from __future__ import annotations
from langchain_core.messages import SystemMessage
from ..tools import CALENDAR_TOOLS
from langgraph.graph import(
    StateGraph,
    MessagesState,
    END
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolNode, tools_condition


try:
    from loadenv import calendar_agent_model
except Exception:  # pragma: no cover - loadenv failure must not break imports
    calendar_agent_model = None

AGENT_NAME = "calendar_service_agent"
AGENT_DESCRIPTION = (
    "Google Calendar operations: create/list/get/update events, cancel (soft) / "
    "delete (permanent, HITL-gated), respond to invites, check free/busy."
)

CALENDAR_SYSTEM_PROMPT = """\
You are the Google Calendar scheduling specialist.

SCOPE
- You handle every calendar operation: creating, listing, and updating events,
  getting event details, cancelling (soft) or deleting (permanent) events,
  responding to invitations, and checking free/busy availability.
- You are a leaf agent inside the Google Workspace domain. Complete the task
  you are given; do not push work back to the supervisor.

OPERATING RULES
1. AUTH FIRST: if the acting user has no connected Google account / valid
   token, fail fast with a friendly "connect your Google account" message.
2. ABSOLUTE TIMES ONLY: never invent dates or times. If the instruction uses
   relative wording ("tomorrow 9am", "this week"), resolve it to an absolute
   ISO datetime before calling any tool; if you cannot resolve it, ask for
   the exact date/time in your report instead of guessing.
3. REQUIRED FIELDS: to create or update an event you need at minimum a title
   and a start time; attendees and duration/end time are optional but
   recommended. Missing critical details → ask in the report, don't guess.
4. CANCEL vs DELETE: `cancel_calendar_event` is a SOFT cancel (status →
   'cancelled', record retained). `delete_calendar_event` PERMANENTLY removes
   the event and is HITL-gated — it must be approved by the human before it
   runs. Never present delete as a routine action.
5. FREE/BUSY: when scheduling, check availability first to avoid double-booking.
6. BOUNDED EXECUTION: retry transient failures once; never surface raw
   tracebacks — report clean, actionable errors.
7. COMPLETE REPORT: your final message is what the supervisor sees. Include
   what was done, the event ID(s) and links, the resolved times (with
   timezone), and any follow-up needed.
"""

__all__ = [
    "AGENT_NAME",
    "AGENT_DESCRIPTION",
    "CALENDAR_SYSTEM_PROMPT",
    "CALENDAR_TOOLS",
    "calendar_agent_model",
]

memory = InMemorySaver()
config = {"configurable":{"thread_id": "1234"}}

#To create a graph we start with the state ofthe graph - the shared dictionary of data
class Calendar_Agent_state(MessagesState):
    pass

_tools = CALENDAR_TOOLS

# create the calendar agent_graph class
class Calendar_AgentGraph:
    def __init__(self, calendar_model=None, tools=None, system_prompt=CALENDAR_SYSTEM_PROMPT):
        self.system_prompt = system_prompt or CALENDAR_SYSTEM_PROMPT
        active_model = calendar_model or calendar_agent_model
        active_tools = tools or _tools
        self.calendar_model = active_model.bind_tools(active_tools)
        # map the tool name to each tool item in the tool object
        self.tools = {t.name: t for t in active_tools}

        # create the node function — NO `self` (nested closure; LangGraph passes state only)
        def calendar_agent(state: Calendar_Agent_state):
            # create the node that calls the calendar model
            prompt = SystemMessage(content=self.system_prompt)
            # define the response as the ai message
            response = self.calendar_model.invoke([prompt] + state["messages"])
            # update the state key with the update as the response
            return {"messages": [response]}

        # create the graph
        calendar_graph = StateGraph(Calendar_Agent_state)
        # create the nodes... - the execution points - python functions that updates the state graph
        calendar_graph.add_node("calendar_agent", calendar_agent)
        calendar_graph.add_node("calendar_tools", ToolNode(active_tools))
        #add the edges - the connection flows
        calendar_graph.set_entry_point("calendar_agent")
        calendar_graph.add_conditional_edges(
            "calendar_agent",
            tools_condition,
            # add the routing condition
            {"tools": "calendar_tools", "__end__": END},
        )
        calendar_graph.add_edge("calendar_tools", "calendar_agent")
        # compile the graph
        self.calendar_graph = calendar_graph.compile(checkpointer=memory, interrupt_before=["calendar_tools"])

# create the calendar agent
def create_calendar_graph(*, model=None, system_prompt: str = ""):
    """Entry point the google_workspace supervisor binds as its subagent."""
    return Calendar_AgentGraph(model, _tools, system_prompt).calendar_graph

