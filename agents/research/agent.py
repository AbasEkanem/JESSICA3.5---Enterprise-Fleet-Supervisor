"""
agents/research/agent.py
==========================
Research domain supervisor — Scout (carrying the Sophie research persona).

Metadata, system prompt, tools, model, and make_graph() factory for the research
domain member. The actual LangGraph StateGraph wiring lives in
agents/research/scout_graph.py.
"""

from __future__ import annotations

from pathlib import Path

from agents.research.tools import RESEARCH_TOOLS, RESEARCH_TOOL_MAP

# ── Model ─────────────────────────────────────────────────────────────────────
try:
    from loadenv import web_searcher_model as research_agent_model  # type: ignore
except Exception:
    research_agent_model = None  # pragma: no cover

# ── Identity ──────────────────────────────────────────────────────────────────
AGENT_NAME = "research_agent"
AGENT_PERSONA = "Scout"
AGENT_DESCRIPTION = (
    "Scout — Domain supervisor for ALL deep research work: multi-engine web search "
    "(Tavily for real-time news/data, Exa for academic/technical depth, Linkup for "
    "structured citations), temporal grounding via datetime tools, strategic reflection "
    "via think_tool, and persisting synthesized findings to disk."
)

# ── System prompt ─────────────────────────────────────────────────────────────
_prompt_file = Path(__file__).parent / "prompts.md"
if _prompt_file.exists():
    SYSTEM_PROMPT = _prompt_file.read_text(encoding="utf-8")
else:
    SYSTEM_PROMPT = (
        "You are Scout, the Deep Research specialist for Jessica 3.5. "
        "You own all deep-research, live data, academic search, and fact verification work. "
        "Always ground time-sensitive queries using get_current_datetime, query ≥2 distinct "
        "search engines, reflect with think_tool, cite sources, and persist findings to disk."
    )

RESEARCH_SKILLS_DIR = Path(__file__).parent / "skills"


# ── Graph factory ─────────────────────────────────────────────────────────────
def make_graph():
    """Compile and return the research CompiledStateGraph.

    Lazy import avoids circular imports at module load time.
    Returns a compiled LangGraph StateGraph satisfying the CompiledSubAgent
    contract (state schema contains `messages`).
    """
    from agents.research.scout_graph import create_research_graph
    return create_research_graph(
        model=research_agent_model,
        system_prompt=SYSTEM_PROMPT,
    )


__all__ = [
    "AGENT_NAME",
    "AGENT_PERSONA",
    "AGENT_DESCRIPTION",
    "SYSTEM_PROMPT",
    "RESEARCH_TOOLS",
    "RESEARCH_TOOL_MAP",
    "RESEARCH_SKILLS_DIR",
    "research_agent_model",
    "make_graph",
]
