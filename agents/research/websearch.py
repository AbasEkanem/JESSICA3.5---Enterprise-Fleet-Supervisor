"""
agents/research/websearch.py
==============================
Production-ready search tools using native LangChain integrations.
Engines:
  - Tavily   -> real-time web search with AI summaries + snippets
  - Exa      -> semantic / research-grade search
  - Linkup   -> structured knowledge & premium source search

Plus research utility tools:
  - think_tool  -> strategic reflection between searches
  - write_file  -> persist findings to disk
"""

from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from langchain_core.tools import BaseTool, ToolException, tool
from langchain_exa import ExaSearchResults
from langchain_linkup import LinkupSearchTool
from langchain_tavily import TavilySearch

logger = logging.getLogger(__name__)

load_dotenv()

EngineKey = Literal["tavily", "exa", "linkup"]

_REQUIRED_KEYS: dict[EngineKey, str] = {
    "tavily": "TAVILY_API_KEY",
    "exa": "EXA_API_KEY",
    "linkup": "LINKUP_API_KEY",
}


def _assert_key(engine: EngineKey) -> None:
    env_var = _REQUIRED_KEYS[engine]
    if not os.getenv(env_var):
        raise RuntimeError(
            f"[search_tools] '{engine}' requires the environment variable "
            f"'{env_var}' to be set."
        )


_GOVERNOR_WARNING = (
    "[SYSTEM_GOVERNOR_WARNING] Search returned no results. "
    "No data exists for this query. "
    "Do NOT fabricate, invent, or guess any information. "
    "You MUST state that no information was found and stop."
)


def _is_empty_result(result: Any) -> bool:
    """Detect if a search result is empty, sparse, or meaningless."""
    if result is None:
        return True
    if isinstance(result, str):
        stripped = result.strip()
        if not stripped:
            return True
    if isinstance(result, dict):
        results = result.get("results", result.get("answer", None))
        if not results:
            return True
        if isinstance(results, list) and len(results) == 0:
            return True
    if isinstance(result, list) and len(result) == 0:
        return True
    return False


def _normalize_or_raise(inner: BaseTool, result: Any) -> Any:
    if isinstance(result, dict) and isinstance(result.get("error"), BaseException):
        raise ToolException(f"{inner.name} failed: {result['error']}")

    if isinstance(inner, ExaSearchResults) and isinstance(result, str):
        raise ToolException(f"{inner.name} failed: {result}")

    # GOVERNOR INTERCEPT: Catch empty/sparse results before LLM sees them
    if _is_empty_result(result):
        logger.warning(
            "[search_tools] %s returned empty result — injecting governor warning.",
            inner.name,
        )
        return _GOVERNOR_WARNING

    return result


def _with_retry(max_attempts: int = 2, backoff_seconds: float = 0.5):
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    result = await fn(*args, **kwargs)
                    if result is not None:
                        return result
                    last_exc = ToolException(
                        f"{fn.__qualname__}: engine returned None"
                    )
                except ToolException as e:
                    last_exc = e
                except Exception as e:
                    last_exc = ToolException(f"{fn.__qualname__} failed: {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(backoff_seconds * (attempt + 1))
                    logger.warning(
                        "[search_tools] %s attempt %d/%d failed (%s), retrying...",
                        fn.__qualname__,
                        attempt + 1,
                        max_attempts,
                        last_exc,
                    )
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator


@lru_cache(maxsize=1)
def _tavily_engine() -> TavilySearch:
    _assert_key("tavily")
    t = TavilySearch(
        max_results=5,
        search_depth="advanced",
        include_answer=True,
        include_raw_content=False,
        include_images=False,
        description=(
            "Search the web for current, real-time information. "
            "Use for breaking news, live data, recent events, and factual lookups. "
            "Returns an AI summary plus the top source URLs."
        ),
    )
    t.name = "tavily_search_engine"
    logger.debug("[search_tools] Tavily engine initialised")
    return t


@lru_cache(maxsize=1)
def _exa_engine() -> ExaSearchResults:
    _assert_key("exa")
    t = ExaSearchResults(
        exa_api_key=os.environ["EXA_API_KEY"],
        description=(
            "Deep semantic search for research, technical content, and authoritative sources. "
            "Use for academic papers, technical documentation, and in-depth topic exploration. "
            "Returns semantically ranked results with optional full-page content."
        ),
    )
    t.name = "exa_search_engine"
    logger.debug("[search_tools] Exa engine initialised")
    return t


@lru_cache(maxsize=1)
def _linkup_engine() -> LinkupSearchTool:
    _assert_key("linkup")
    t = LinkupSearchTool(
        depth="standard",
        output_type="searchResults",
        description=(
            "Search premium, structured knowledge sources via Linkup. "
            "Use for citation-grade answers, licensed content, and structured data retrieval."
        ),
    )
    t.name = "linkup_search_engine"
    logger.debug("[search_tools] Linkup engine initialised")
    return t


@tool
async def tavily_search(query: str) -> str:
    """
    Real-time web search via Tavily.

    Best for: breaking news, live prices, current statistics, factual lookups.
    Returns an AI-generated answer plus ranked source URLs.
    """
    try:
        engine = _tavily_engine()
    except Exception as exc:
        logger.warning("[tavily_search] Engine unavailable: %s", exc)
        return f"[tavily_search] Unavailable: {exc}"

    @_with_retry(max_attempts=2, backoff_seconds=0.5)
    async def _call():
        result = await engine._arun(query)
        return _normalize_or_raise(engine, result)

    try:
        result = str(await _call())
        if not result or result.strip() == "None":
            logger.warning("[tavily_search] returned empty — injecting governor warning.")
            return _GOVERNOR_WARNING
        return result
    except ToolException as e:
        logger.error("[tavily_search] failed: %s", e)
        return _GOVERNOR_WARNING


@tool
async def exa_search(query: str) -> str:
    """
    Semantic research search via Exa.

    Best for: research papers, technical documentation, academic sources,
    in-depth articles, and finding authoritative content on complex topics.
    """
    try:
        engine = _exa_engine()
    except Exception as exc:
        logger.warning("[exa_search] Engine unavailable: %s", exc)
        return f"[exa_search] Unavailable: {exc}"

    @_with_retry(max_attempts=2, backoff_seconds=0.5)
    async def _call():
        result = await engine._arun(
            query,
            num_results=5,
            use_autoprompt=True,
            type="auto",
        )
        return _normalize_or_raise(engine, result)

    try:
        result = str(await _call())
        if not result or result.strip() == "None":
            logger.warning("[exa_search] returned empty — injecting governor warning.")
            return _GOVERNOR_WARNING
        return result
    except ToolException as e:
        logger.error("[exa_search] failed: %s", e)
        return _GOVERNOR_WARNING


@tool
async def linkup_search(query: str) -> str:
    """
    Structured knowledge search via Linkup.

    Best for: premium news sources, structured answers, licensed content,
    and queries that require citation-grade sourcing.
    """
    try:
        engine = _linkup_engine()
    except Exception as exc:
        logger.warning("[linkup_search] Engine unavailable: %s", exc)
        return f"[linkup_search] Unavailable: {exc}"

    @_with_retry(max_attempts=2, backoff_seconds=0.5)
    async def _call():
        return await engine._arun(query)

    try:
        result = str(await _call())
        if not result or result.strip() == "None":
            logger.warning("[linkup_search] returned empty — injecting governor warning.")
            return _GOVERNOR_WARNING
        return result
    except ToolException as e:
        logger.error("[linkup_search] failed: %s", e)
        return _GOVERNOR_WARNING


@tool(description="Strategic reflection tool for research planning")
def think_tool(reflection: str) -> str:
    """Tool for strategic reflection on research progress and decision-making.

    Use this tool after each search to analyze results and plan next steps systematically.
    This creates a deliberate pause in the research workflow for quality decision-making.

    When to use:
    - After receiving search results: What key information did I find?
    - Before deciding next steps: Do I have enough to answer comprehensively?
    - When assessing research gaps: What specific information am I still missing?
    - Before concluding research: Can I provide a complete answer now?

    Reflection should address:
    1. Analysis of current findings - What concrete information have I gathered?
    2. Gap assessment - What crucial information is still missing?
    3. Quality evaluation - Do I have sufficient evidence/examples for a good answer?
    4. Strategic decision - Should I continue searching or provide my answer?

    Args:
        reflection: Your detailed reflection on research progress, findings, gaps, and next steps

    Returns:
        Confirmation that reflection was recorded for decision-making
    """
    return f"Reflection recorded: {reflection}"


@tool
def write_file(file_path: str, content: str) -> str:
    """
    Write *content* to *file_path*, creating parent directories as needed.
    Returns a confirmation message with the absolute path that was written.
    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info("[write_file] Saved %d chars -> %s", len(content), path.resolve())
    return f"Saved to {path.resolve()} ({len(content)} chars)"


SEARCH_TOOLS: list[BaseTool] = [
    tavily_search,
    exa_search,
    linkup_search,
    think_tool,
    write_file,
]

__all__ = [
    "tavily_search",
    "exa_search",
    "linkup_search",
    "think_tool",
    "write_file",
    "SEARCH_TOOLS",
]
