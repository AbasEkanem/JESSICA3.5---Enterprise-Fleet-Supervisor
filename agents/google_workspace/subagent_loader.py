"""
agents/google_workspace/subagent_loader.py
==========================================
Loads and compiles the 8 Google Workspace service leaf agents from subagents.yaml
into subagent specifications ready for create_deep_agent(subagents=...).

Each entry in subagents.yaml defines:
  - name: unique subagent identifier (e.g. 'sheets_service')
  - description: description shown to Gemma for routing
  - module: entry point path in 'module.path:factory_callable' format
  - runtime: 'langgraph' or 'create_agent'
  - hitl_tools: list of high-risk tools requiring HITL approval
  - tools: list of tool names associated with this subagent

Returns a list of CompiledSubAgent dicts:
  {"name": str, "description": str, "runnable": <compiled graph>}
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

import yaml

_log = logging.getLogger(__name__)


def _import_factory(entry_point: str):
    """Dynamically import a callable given 'package.module:callable_name'."""
    if ":" not in entry_point:
        raise ValueError(
            f"[google_workspace_subagent_loader] Invalid factory specification '{entry_point}'. "
            "Expected format 'module.submodule:callable_name'."
        )
    module_path, callable_name = entry_point.split(":", 1)
    module = importlib.import_module(module_path)
    factory = getattr(module, callable_name, None)
    if factory is None:
        raise AttributeError(
            f"[google_workspace_subagent_loader] Callable '{callable_name}' not found in '{module_path}'."
        )
    return factory


def load_google_workspace_subagents(
    config_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """
    Parse subagents.yaml and instantiate/compile each of the 8 Google Workspace leaf graphs.

    Returns:
        List of dicts suitable for create_deep_agent(subagents=...):
        [{"name": ..., "description": ..., "runnable": <compiled_graph>}, ...]
    """
    if config_path is None:
        config_path = Path(__file__).parent / "subagents.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(
            f"[google_workspace_subagent_loader] Registry not found at {config_path}"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        docs = list(yaml.safe_load_all(f))

    subagents: list[dict[str, Any]] = []

    for doc in docs:
        if not doc or not isinstance(doc, dict):
            continue

        name = doc.get("name")
        description = doc.get("description", "").strip()
        module_entry = doc.get("module")

        if not name or not description or not module_entry:
            _log.warning(
                "[google_workspace_subagent_loader] Skipping malformed entry: %s", doc
            )
            continue

        factory = _import_factory(module_entry)
        runnable = factory()

        subagent_spec: dict[str, Any] = {
            "name": name,
            "description": description,
            "runnable": runnable,
        }

        subagents.append(subagent_spec)
        _log.info(
            "[google_workspace_subagent_loader] Compiled subagent '%s' from %s",
            name,
            module_entry,
        )

    return subagents


__all__ = ["load_google_workspace_subagents"]
