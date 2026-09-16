"""
agents/google_workspace/services/drive.py
=========================================
Drive service graph — fleet leaf. Pure LangGraph wiring is authored by the
owner. This template only wires the contract surface: the drive toolset and
the drive model.

Bound to the google_workspace supervisor via:
    {"name": "drive_service", "description": AGENT_DESCRIPTION,
     "runnable": make_drive_graph()}
"""



from __future__ import annotations
from langgraph.checkpoint.memory import InMemorySaver
from ..tools import DRIVE_TOOLS
from langchain.agents import create_agent
try:
    from loadenv import drive_agent_model
except Exception:  # pragma: no cover - loadenv failure must not break imports
    drive_agent_model = None

AGENT_NAME = "drive_service"
AGENT_DESCRIPTION = (
    "Drive operations: search, upload, download, export, create folders, move, "
    "rename, share & permissions, trash/delete. HITL-gated: delete/trash/broad-share."
)

DRIVE_SYSTEM_PROMPT = """\
You are the Google Drive file-management specialist.

SCOPE
- Search, upload, download, export, folder creation, move, rename, sharing &
  permissions, trash, and permanent delete. You are a leaf agent inside the
  Google Workspace domain — complete the task; do not push work back.

OPERATING RULES
1. AUTH FIRST: no connected account / valid token → friendly "connect your
   Google account" message, nothing else.
2. SHARE = EXPOSURE: `share_drive_file_with_anyone` and `bulk_share_drive_files`
   are HITL-gated — confirm the exact recipients/audience before executing.
   `share_drive_file` needs explicit grantee emails. Revoke permissions when asked.
3. TRASH vs DELETE: trash is reversible; `delete_drive_file` is permanent and
   HITL-gated — never present it as routine.
4. SEARCH PRECISION: build targeted queries; report result counts and paths.
5. BOUNDED EXECUTION: retry transient failures once; clean, actionable errors.
6. COMPLETE REPORT: file/folder IDs + webViewLinks, what changed, follow-ups.
"""

__all__ = [
    "AGENT_NAME",
    "AGENT_DESCRIPTION",
    "DRIVE_SYSTEM_PROMPT",
    "DRIVE_TOOLS",
    "drive_agent_model",
]

# creating the drive agent using the base harness - the create agent
_tools = DRIVE_TOOLS

def create_drive_graph(*, model=None, system_prompt: str = ""):
    """Entry point the google_workspace supervisor binds as its subagent."""
    return create_agent(
        model=model or drive_agent_model,
        system_prompt=system_prompt or DRIVE_SYSTEM_PROMPT,
        tools=_tools,
        checkpointer=InMemorySaver(),
    )