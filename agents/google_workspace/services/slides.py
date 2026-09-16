"""
agents/google_workspace/services/slides.py
==========================================
Slides service graph — fleet leaf. Pure LangGraph wiring is authored by the
owner. This template only wires the contract surface: the slides toolset and
the slides model.

Bound to the google_workspace supervisor via:
    {"name": "slides_service", "description": AGENT_DESCRIPTION,
     "runnable": make_slides_graph()}
"""

from __future__ import annotations

from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver
from ..tools import SLIDES_TOOLS

try:
    from loadenv import slides_agent_model
except Exception:  # pragma: no cover - loadenv failure must not break imports
    slides_agent_model = None

AGENT_NAME = "slides_service"
AGENT_DESCRIPTION = (
    "Google Slides operations: full-deck build, add/populate slides, duplicate, "
    "reorder, replace text, images, tables, Sheets chart embeds, backgrounds."
)

SLIDES_SYSTEM_PROMPT = """\
You are the Google Slides presentation specialist.

SCOPE
- Build decks, add/populate/duplicate/reorder slides, batch text replace,
  insert images/tables, embed & refresh Sheets charts, background colors.
  Leaf agent — complete the task.

OPERATING RULES
1. AUTH FIRST: no connected account → friendly "connect your Google account".
2. PREFER ATOMIC TOOLS: `create_slides_deck` builds an ENTIRE deck in one call;
   `add_slide_with_content` adds one populated slide safely. Do NOT chain
   add_slide → insert_text yourself — made-up shape IDs produce blank slides.
3. IMAGES: only public HTTP(S) URLs (e.g. Mermaid.ink / QuickChart renderers).
4. CHARTS: `embed_sheets_chart_on_slide` links but does not auto-refresh —
   call `refresh_slide_sheets_chart` after the source data changes.
5. BOUNDED EXECUTION: retry once; clean errors, no tracebacks.
6. COMPLETE REPORT: presentation ID + link, slide count, what was built.
"""

__all__ = [
    "AGENT_NAME",
    "AGENT_DESCRIPTION",
    "SLIDES_SYSTEM_PROMPT",
    "SLIDES_TOOLS",
    "slides_agent_model",
]
_tools = SLIDES_TOOLS

def create_slides_graph(*, model=None, system_prompt: str = ""):
    """Entry point the google_workspace supervisor binds as its subagent."""
    return create_agent(
        model=model or slides_agent_model,
        system_prompt=system_prompt or SLIDES_SYSTEM_PROMPT,
        tools=_tools,
        checkpointer=InMemorySaver(),
    )