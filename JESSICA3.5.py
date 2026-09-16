# Activate Jessica's durability harness BEFORE the deep agent is ever built.
# nemotron_harness.attach_to_deepagents() registers the portable anti-Nemotron
# middleware stack (empty-completion strict retry + backstop, tool-call repair,
# tool + delegation loop breakers, reasoning trim, wire compatibility, temporal
# date frame) as a deepagents HarnessProfile under Jessica's brain model id —
# both NVIDIA/nvidia key spellings and both Nemotron-3 specs — so
# create_deep_agent selects it by exact model-id lookup at build time.
#
# This REPLACES the previous profile-retune approach (jessica_harness.py, now
# removed): ONE harness, ONE source of truth — the built-in deepagents Ultra
# profile is no longer mirrored/re-tuned, so there is no double loop-breaking.
# Without this registration the brain would run with an empty profile (or, on
# ultra-550b, the built-in profile's too-tight 16-call cap) and drift/stop early
# on multi-step workflows. Kept first so registration precedes any build.
import os as _os_harness

from nemotron_harness import attach_to_deepagents as _attach_nemotron_harness

_BRAIN_MODEL_ID = _os_harness.getenv(
    "JESSICA_BRAIN_MODEL_ID", "nvidia/nemotron-3-super-120b-a12b"
)
# Also cover the routing / confluence model (step-3.7-flash) so deepagents
# doesn't emit "no harness profile matched" warnings for those sub-graphs.
_ROUTING_MODEL_ID = _os_harness.getenv(
    "ROUTING_MODEL_ID", "stepfun-ai/step-3.7-flash"
)
_attach_nemotron_harness(
    tuple(
        f"{prefix}:{spec}"
        for spec in (_BRAIN_MODEL_ID, "nvidia/nemotron-3-ultra-550b-a55b")
        for prefix in ("NVIDIA", "nvidia")
    ) + (f"NVIDIA:{_ROUTING_MODEL_ID}", f"stepfun:{_ROUTING_MODEL_ID}"),
)

from typing import Any
from langchain_core.runnables import RunnableConfig
from deepagents import create_deep_agent as _createJessicaAIAgent
from langchain.agents.middleware import ToolRetryMiddleware, ModelRetryMiddleware, PIIMiddleware
from memory_manager import memory_tools as _jessicaMemoryManager
from subagent_loader import load_subagents as _subagents
from pathlib import Path
from deepagents.backends import FilesystemBackend as _jessicaFilesystemBackend
from datetime_tools import date_time_tools as _jessicaDateTimeTools
from system_prompts import jessica_instructions
from loadenv import chat_model as _jessicasBrain
from background_tasks import bg_task_manager as _bg_manager
from langchain.agents.middleware import TodoListMiddleware as _todo_middleware
from config import HARD_RISK_TOOLS as _HARD_RISK_TOOLS
# create the file directory 
file_dir = Path(__file__).parent
# create the subagent_loader 
_yaml_file = file_dir / "subagent.yaml" if (file_dir / "subagent.yaml").exists() else file_dir / "subagents.yaml"
_subagent_loader = _subagents(_yaml_file)
# create the filsystem_backend_loader
_jessicaExecution_environment = _jessicaFilesystemBackend(root_dir=file_dir, virtual_mode=True)
# create the jessica tools
_bg_tools = _bg_manager.get_tools()
jessica_tools = _jessicaMemoryManager + _jessicaDateTimeTools + _bg_tools

# create the jessica AI agent
def create_jessicaAI(checkpointer=None, store=None):
    """create the Jessica ai agent"""
    return _createJessicaAIAgent(
        model= _jessicasBrain,
        tools= jessica_tools,
        system_prompt= jessica_instructions,
        subagents= _subagent_loader,
        skills=[str(file_dir / "skills")],
        memory=[str(file_dir / "JESSICA.md")],
        backend= _jessicaExecution_environment,
        store = store,
        checkpointer = checkpointer,
        interrupt_on={_tool_name: True for _tool_name in _HARD_RISK_TOOLS},
        # add the todo planning middleware, tool retry middleware, model retry middleware and PII middleware
        middleware = [
            _todo_middleware(),
            ToolRetryMiddleware(max_retries=3),
            ModelRetryMiddleware(max_retries=3),
            PIIMiddleware("credit_card", strategy = "mask" ),
            PIIMiddleware("api_key", detector= r"sk-[a-zA-Z0-9]{32}", strategy="mask")
        ]
    )

# Backward-compatible function aliases
create_jessica3_5_agent = create_jessicaAI
create_jessica_conversation_agent = create_jessicaAI
graph = None
def make_graph(config: RunnableConfig) -> Any:
    """LangGraph factory: build the Jessica graph for the platform runtime."""
    return create_jessicaAI(checkpointer=None, store=None)



