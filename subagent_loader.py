"""
subagent_loader.py — supervisor registry loader for Jessica 3.5.

Jessica is a SUPERVISOR OF SUPERVISORS (L0). She no longer holds the 13 flat
leaf agents directly — every domain leaf now lives INSIDE its compiled domain
supervisor (L1):

    research_agent         (Scout) ← agents/research/
    comms_agent            (Relay) ← agents/comms/
    google_workspace_agent (Gemma) ← agents/google_workspace/
    project_mgmt_agent     (Forge) ← agents/project_mgmt/

This module loads subagent.yaml. Every entry MUST be a ``runtime: deep_agent``
document pointing at a zero-arg factory (``pkg.module:factory``) that returns
an ALREADY-COMPILED graph whose state schema includes ``messages``. Each is
registered as a deepagents ``CompiledSubAgent`` — exactly
``{"name", "description", "runnable"}`` — which is what
``create_deep_agent(subagents=...)`` accepts.

Contract for each factory (mirrors agents/google_workspace/subagent_loader.py):
  * takes NO arguments;
  * builds its own model, tools, prompt, leaf subagents, skills, middleware;
  * returns a compiled runnable (create_agent / create_deep_agent /
    StateGraph(...).compile() all satisfy it);
  * the parent reads `structured_response` if set, otherwise the last
    non-empty AIMessage text, so the graph should END with the report it
    wants Jessica to see.

The old flat-tool-registry loader was retired with the 13-leaf topology: the
tool→agent mapping now lives inside each domain package
(agents/*/tools.py + agents/*/subagent_loader.py), which is where it belongs.

Usage
-----
    from subagent_loader import load_subagents
    subagents = load_subagents(Path(__file__).parent / "subagent.yaml")
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

import yaml

_log = logging.getLogger(__name__)

# Runtimes accepted for a supervisor entry.
_DEEP_AGENT_RUNTIMES = {"deep_agent", "compiled"}


def _import_factory(entry_point: str):
    """Import and return a callable from a ``package.module:factory`` string."""
    if ":" not in entry_point:
        raise ValueError(
            f"[subagent_loader] Invalid factory specification '{entry_point}'. "
            "Expected format 'module.submodule:callable_name'."
        )
    module_path, callable_name = entry_point.split(":", 1)
    module = importlib.import_module(module_path)
    factory = getattr(module, callable_name, None)
    if factory is None:
        raise AttributeError(
            f"[subagent_loader] Callable '{callable_name}' not found in '{module_path}'."
        )
    return factory


def load_subagents(config_path: Path | str) -> list[dict[str, Any]]:
    """Load the supervisor registry from subagent.yaml.

    Every document must be a ``runtime: deep_agent`` entry. A flat
    (``model``/``tools``-style) entry is a structural error now — the leaves
    belong inside their domain supervisor, not in Jessica's registry.

    Returns:
        List of CompiledSubAgent dicts: [{"name", "description", "runnable"}, ...]
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"[subagent_loader] Supervisor registry not found: {config_path}"
        )

    with config_path.open(encoding="utf-8") as f:
        documents = list(yaml.safe_load_all(f))

    subagents: list[dict[str, Any]] = []

    for doc in documents:
        if not doc or not isinstance(doc, dict):
            continue

        # ── Validate required fields ────────────────────────────────────────
        if "name" not in doc or "description" not in doc:
            raise ValueError(
                "[subagent_loader] A supervisor document is missing required "
                f"fields 'name' or 'description'. Document: {doc}"
            )
        name: str = doc["name"]

        runtime = str(doc.get("runtime", "")).strip().lower()
        if runtime not in _DEEP_AGENT_RUNTIMES:
            raise ValueError(
                f"[subagent_loader] Supervisor '{name}' must set "
                f"'runtime: deep_agent' (got {runtime or '<none>'!r}). Jessica "
                "is a supervisor of supervisors: only compiled domain-supervisor "
                "graphs belong in subagent.yaml — domain leaves live inside "
                "their agents/<domain>/ package."
            )

        module_entry = doc.get("module")
        if not module_entry:
            raise ValueError(
                f"[subagent_loader] Supervisor '{name}' sets runtime "
                f"{runtime!r} but has no 'module' entry point. "
                "Expected 'package.module:factory'."
            )

        # ── Build the compiled supervisor graph ─────────────────────────────
        factory = _import_factory(module_entry)
        try:
            runnable = factory()
        except Exception as exc:  # a build failure must name the entry
            raise ValueError(
                f"[subagent_loader] Supervisor '{name}' failed to build from "
                f"{module_entry}: {type(exc).__name__}: {exc}"
            ) from exc

        subagents.append(
            {"name": name, "description": doc["description"], "runnable": runnable}
        )
        _log.info(
            "[subagent_loader] Loaded DEEP-AGENT supervisor '%s' from %s",
            name,
            module_entry,
        )

    _log.info(
        "[subagent_loader] Loaded %d domain supervisor(s) from %s",
        len(subagents),
        config_path,
    )
    return subagents
