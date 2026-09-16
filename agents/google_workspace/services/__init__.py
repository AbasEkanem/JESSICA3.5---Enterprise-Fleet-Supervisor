# agents/google_workspace/services/ — per-service leaf agents.
#
# Each module exports:
#   AGENT_NAME, AGENT_DESCRIPTION, <SERVICE>_SYSTEM_PROMPT,
#   <SERVICE>_TOOLS, <service>_agent_model, and a create_<service>_graph() factory.
#
# Service modules:
#   calendar, classroom, coursework, docs, drive, forms, sheets, slides
