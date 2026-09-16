import os
import sys
import shutil

# On Windows, shutil.move uses os.rename under the hood which raises FileExistsError (WinError 183)
# when destination checkpoint files (.langgraph_checkpoint.*.pckl) already exist during langgraph dev sync.
# Patching shutil.move with os.replace ensures atomic destination overwrite on Windows.
if sys.platform == "win32":
    _orig_move = shutil.move
    def _win_safe_move(src, dst, copy_function=shutil.copy2):
        try:
            os.replace(src, dst)
            return dst
        except Exception:
            return _orig_move(src, dst, copy_function=copy_function)
    shutil.move = _win_safe_move

import importlib.util as _ilu

_spec = _ilu.spec_from_file_location(
    "jessica35",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "JESSICA3.5.py"),
)
_j35 = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_j35)
create_jessicaAI = getattr(_j35, "create_jessicaAI", getattr(_j35, "create_jessica3_5_agent", None))
create_jessica3_5_agent = create_jessicaAI
create_jessica_conversation_agent = create_jessicaAI

# LangGraph API (>=0.10.0) manages the store automatically — it injects its own
# SQLite-backed store at runtime during `langgraph dev`, and a Postgres-backed
# store in production. Do NOT pass a custom store here or it will be rejected.
# The langmem ManageMemory / SearchMemory tools will receive the platform store
# via the LangGraph runtime context automatically.
graph = getattr(_j35, "graph", None) or create_jessicaAI(checkpointer=None, store=None)



