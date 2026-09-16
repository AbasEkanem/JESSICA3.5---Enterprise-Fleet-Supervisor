"""
agents/project_mgmt/confluence.py
===================================
Complete Confluence tools for Jessica 3.5.

Covers: create page, get page, update page, search (CQL), add comment.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from langchain.tools import tool
from atlassian import Confluence

from agents.project_mgmt.jira import MissingConfigError, _require_env

load_dotenv()

log = logging.getLogger(__name__)


# ── Client ────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _confluence() -> Confluence:
    _require_env("CONFLUENCE_URL", "CONFLUENCE_USERNAME", "CONFLUENCE_API_TOKEN")
    return Confluence(
        url=os.getenv("CONFLUENCE_URL", ""),
        username=os.getenv("CONFLUENCE_USERNAME", ""),
        password=os.getenv("CONFLUENCE_API_TOKEN", ""),
        cloud=True,
        timeout=int(os.getenv("CONFLUENCE_REQUEST_TIMEOUT_S", "30")),
    )


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def create_confluence_page(
    title: str,
    space_key: str,
    body: str,
    parent_id: Optional[str] = None,
) -> str:
    """Create a new Confluence page.

    `body` must be Confluence storage-format XHTML.
    `parent_id` is optional — omit to create at the space root.
    """
    try:
        cf = _confluence()
        page = cf.create_page(space=space_key, title=title, body=body, parent_id=parent_id)
        url = f"{os.getenv('CONFLUENCE_URL', '')}{page.get('_links', {}).get('webui', '')}"
        return f"✅ Created '{title}' in {space_key}: {url}"
    except MissingConfigError as e:
        return f"⚠️ Config error: {e}"
    except Exception as e:
        return f"⚠️ Failed to create page: {e}"


@tool
def get_confluence_page(page_id: str) -> str:
    """Get Confluence page details (title, space, first 700 chars of body, and URL)."""
    try:
        cf = _confluence()
        page = cf.get_page_by_id(page_id, expand="body.storage,space,version")
        url = f"{os.getenv('CONFLUENCE_URL', '')}{page.get('_links', {}).get('webui', '')}"
        return (
            f"*{page['title']}* (Space: {page['space']['key']})\n\n"
            f"{page['body']['storage']['value'][:700]}\n\n"
            f"🔗 {url}"
        )
    except MissingConfigError as e:
        return f"⚠️ Config error: {e}"
    except Exception as e:
        return f"⚠️ Could not fetch page: {e}"


@tool
def update_confluence_page(
    page_id: str,
    title: Optional[str] = None,
    body: Optional[str] = None,
) -> str:
    """Update a Confluence page title and/or body.

    At least one of `title` or `body` must be provided.
    If only `body` is updated, the existing title is preserved.
    """
    if title is None and body is None:
        return "Nothing to update."
    try:
        cf = _confluence()
        if title is None:
            title = cf.get_page_by_id(page_id)["title"]
        cf.update_page(page_id=page_id, title=title, body=body)
        return f"✅ Updated page {page_id}"
    except MissingConfigError as e:
        return f"⚠️ Config error: {e}"
    except Exception as e:
        return f"⚠️ Update failed: {e}"


@tool
def search_confluence(cql: str, limit: int = 10) -> str:
    """Search Confluence using CQL (Confluence Query Language).

    Example: `type = page AND space = "ENG" AND text ~ "sprint"`
    """
    try:
        results = _confluence().cql(cql, limit=limit).get("results", [])
        if not results:
            return "No results found."
        return "\n".join(
            ["Confluence Search:"] +
            [f"• *{r['title']}* ({r['space']['key']})" for r in results]
        )
    except MissingConfigError as e:
        return f"⚠️ Config error: {e}"
    except Exception as e:
        return f"⚠️ Search failed: {e}"


@tool
def add_confluence_comment(page_id: str, comment: str) -> str:
    """Add a comment to a Confluence page."""
    try:
        _confluence().add_comment(page_id, comment)
        return f"✅ Comment added to page {page_id}"
    except MissingConfigError as e:
        return f"⚠️ Config error: {e}"
    except Exception as e:
        return f"⚠️ Comment failed: {e}"


# ── Export ───────────────────────────────────────────────────────────────────
CONFLUENCE_TOOLS = [
    create_confluence_page,
    get_confluence_page,
    update_confluence_page,
    search_confluence,
    add_confluence_comment,
]

__all__ = [
    "CONFLUENCE_TOOLS",
    "create_confluence_page",
    "get_confluence_page",
    "update_confluence_page",
    "search_confluence",
    "add_confluence_comment",
]
