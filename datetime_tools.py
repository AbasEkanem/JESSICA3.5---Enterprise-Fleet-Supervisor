"""
datetime_tools.py  ← SHIM (backward-compatibility re-export)
================================================================
The canonical implementations live in agents/research/datetime_tools.py.
This file exists only so that JESSICA3.5.py and subagent_loader.py keep
importing from the root without changes.

Do NOT add new logic here. All changes go to:
  agents/research/datetime_tools.py
"""

from agents.research.datetime_tools import (  # noqa: F401
    get_current_datetime,
    calculate_future_datetime,
    DATETIME_TOOLS,
)

# Legacy export name used by JESSICA3.5.py
date_time_tools = [get_current_datetime, calculate_future_datetime]

__all__ = [
    "get_current_datetime",
    "calculate_future_datetime",
    "date_time_tools",
    "DATETIME_TOOLS",
]
