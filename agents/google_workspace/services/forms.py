"""
agents/google_workspace/services/forms.py
=========================================
Forms service graph — fleet leaf. Pure LangGraph wiring is authored by the
owner. This template only wires the contract surface: the forms toolset and
the forms model.

NOTE: Google Forms are Drive-backed files, so sharing/publishing may need the
drive-share tools (search_drive_files, share_drive_file,
share_drive_file_with_anyone) — bind them here if the forms leaf must share
forms directly.

Bound to the google_workspace supervisor via:
    {"name": "forms_service", "description": AGENT_DESCRIPTION,
     "runnable": make_forms_graph()}
"""
from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langchain.agents import create_agent
from ..tools import FORMS_TOOLS

try:
    from loadenv import forms_agent_model
except Exception:  # pragma: no cover - loadenv failure must not break imports
    forms_agent_model = None

AGENT_NAME = "forms_service"
AGENT_DESCRIPTION = (
    "Google Forms operations: create, details, publish, add text/choice/section "
    "questions (checkbox etc.), delete items, read responses."
)

FORMS_SYSTEM_PROMPT = """\
You are the Google Forms survey specialist.

SCOPE
- Create forms, add text/choice questions and section headers, publish, delete
  items, read responses. Leaf agent — complete the task.

OPERATING RULES
1. AUTH FIRST: no connected account → friendly "connect your Google account".
2. ALWAYS PUBLISH: API-created forms default to UNPUBLISHED — call
   `publish_google_form` after `create_google_form`, or responses are rejected.
3. SHARING: forms are Drive-backed files; sharing one uses Drive permissions
   (bind the drive-share tools to this leaf if it must share forms directly).
4. QUESTION DESIGN: one question type per call; use section headers to group.
5. BOUNDED EXECUTION: retry once; clean errors, no tracebacks.
6. COMPLETE REPORT: form ID + link, published state, question count,
   response counts when read.
"""

__all__ = [
    "AGENT_NAME",
    "AGENT_DESCRIPTION",
    "FORMS_SYSTEM_PROMPT",
    "FORMS_TOOLS",
    "forms_agent_model",
]
_tools = FORMS_TOOLS

def create_forms_graph(*, model=None, system_prompt: str = ""):
    """Entry point the google_workspace supervisor binds as its subagent."""
    return create_agent(
        model=model or forms_agent_model,
        system_prompt=system_prompt or FORMS_SYSTEM_PROMPT,
        tools=_tools,
        checkpointer=InMemorySaver(),
    )