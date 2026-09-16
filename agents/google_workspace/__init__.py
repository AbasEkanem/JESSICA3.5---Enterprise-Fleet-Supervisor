# agents/google_workspace/ — Google Workspace domain supervisor.
#
# Public surface:
#   - agent.py        : AGENT_NAME, AGENT_DESCRIPTION, SYSTEM_PROMPT, model
#   - tools.py        : GOOGLE_WORKSPACE_TOOLS, per-service tool lists
#   - services/       : per-service leaf agents (calendar, classroom, coursework,
#                        docs, drive, forms, sheets, slides)
#   - auth.py         : shared OAuth / service-account helpers
#   - token_store.py  : per-service token storage

from .agent import AGENT_NAME, AGENT_DESCRIPTION, SYSTEM_PROMPT
from .tools import GOOGLE_WORKSPACE_TOOLS, GOOGLE_WORKSPACE_TOOL_MAP
