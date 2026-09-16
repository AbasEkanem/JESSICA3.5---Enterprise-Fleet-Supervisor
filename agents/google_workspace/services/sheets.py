"""
agents/google_workspace/services/sheets.py
==========================================
Sheets service graph — fleet leaf. Pure LangGraph wiring is authored by the
owner. This template only wires the contract surface: the sheets toolset and
the sheets model.

Bound to the google_workspace supervisor via:
    {"name": "sheets_service", "description": AGENT_DESCRIPTION,
     "runnable": make_sheets_graph()}
"""

from __future__ import annotations

from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver
from ..tools import SHEETS_TOOLS

try:
    from loadenv import sheets_agent_model
except Exception:  # pragma: no cover - loadenv failure must not break imports
    sheets_agent_model = None

AGENT_NAME = "sheets_service"
AGENT_DESCRIPTION = (
    "Google Sheets operations: create, read/write ranges, batch reads, append "
    "rows, clear, add/delete tabs, format cells."
)

SHEETS_SYSTEM_PROMPT = """\
You are the Google Sheets specialist.

SCOPE
- Create spreadsheets, read/write cell ranges, batch reads, append rows, clear
  ranges, add/delete tabs, format cells. Leaf agent — complete the task.

OPERATING RULES
1. AUTH FIRST: no connected account → friendly "connect your Google account".
2. A1 DISCIPLINE: explicit tab-qualified ranges ("Sheet1!A1:D10"). Read a range
   before overwriting it — never blind-write over unknown data.
3. DESTRUCTIVE CARE: `clear_sheet_range` wipes values in the range;
   `delete_sheet_tab` removes the tab and ALL its data. Confirm the exact
   scope in your report before executing either.
4. STRUCTURE: create tabs before writing to them; keep headers in row 1.
5. BOUNDED EXECUTION: retry once; clean errors, no tracebacks.
6. COMPLETE REPORT: spreadsheet ID + link, tab(s) touched, ranges written.
"""

__all__ = [
    "AGENT_NAME",
    "AGENT_DESCRIPTION",
    "SHEETS_SYSTEM_PROMPT",
    "SHEETS_TOOLS",
    "sheets_agent_model",
]

_tools = SHEETS_TOOLS

def create_sheets_graph(*, model=None, system_prompt: str = ""):
    """Entry point the google_workspace supervisor binds as its subagent."""
    return create_agent(
        model=model or sheets_agent_model,
        system_prompt=system_prompt or SHEETS_SYSTEM_PROMPT,
        tools=_tools,
        checkpointer=InMemorySaver(),
    )