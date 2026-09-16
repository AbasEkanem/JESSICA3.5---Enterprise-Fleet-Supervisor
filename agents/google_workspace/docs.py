"""
google_docs_tools.py
=====================
Full Docs CRUD for Jessica: create, read, append/insert text, find &
replace, delete ranges, text styling (bold/italic/font size), and page breaks.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from langchain_core.tools import tool

from .auth import get_service

_log = logging.getLogger(__name__)

# ── Idempotency guard for create_google_doc ──────────────────────────────────
# A weak/looping subagent model can call create_google_doc many times in a row
# with the same title (observed: 8+ duplicate docs in a single task when the
# model never received the real body and kept retrying with placeholder text).
# We cache the most recent (title → doc_id, link) result for a short window so
# repeat calls with the SAME title return the already-created doc instead of
# spawning duplicates. This bounds the blast radius of a runaway loop to exactly
# one document per title.
_RECENT_DOC_TTL_S = 120.0
_recent_docs: dict[str, tuple[float, str, str]] = {}  # title → (ts, doc_id, link)


def _svc():
    return get_service("docs")


def _drive():
    return get_service("drive")


@tool
def create_google_doc(title: str, initial_content: Optional[str] = None) -> str:
    """Create a new Google Document.

    Args:
        title: Title of the document.
        initial_content: Optional initial text content to insert.
    """
    try:
        # ── Idempotency: if a doc with this exact title was created moments
        #    ago, return it instead of creating a duplicate. Stops runaway
        #    loops from a weak subagent model spawning many identical docs.
        now = time.monotonic()
        cached = _recent_docs.get(title)
        if cached is not None:
            ts, cached_id, cached_link = cached
            if now - ts < _RECENT_DOC_TTL_S:
                _log.warning(
                    "create_google_doc.idempotent_hit title=%r doc_id=%s "
                    "(returning existing doc instead of creating a duplicate)",
                    title, cached_id,
                )
                return (
                    f"✅ Google Doc **{title}** already exists (ID: `{cached_id}`)\n"
                    f"Link: {cached_link}\n"
                    f"(Reused the doc created moments ago — did NOT create a duplicate. "
                    f"To add content, call append_text_to_doc with this document ID.)"
                )
            _recent_docs.pop(title, None)

        doc = _svc().documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]

        if initial_content:
            requests = [{
                "insertText": {
                    "location": {"index": 1},
                    "text": initial_content
                }
            }]
            _svc().documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

        file_meta = _drive().files().get(fileId=doc_id, fields="webViewLink").execute()
        link = file_meta.get("webViewLink")

        # Remember this creation so immediate repeat calls are deduplicated.
        _recent_docs[title] = (now, doc_id, link)
        for _t, (_ts, _id, _l) in list(_recent_docs.items()):
            if now - _ts >= _RECENT_DOC_TTL_S:
                _recent_docs.pop(_t, None)

        return f"✅ Created Google Doc: **{title}** (ID: `{doc_id}`)\nLink: {link}"
    except Exception as e:
        return f"⚠️ Doc creation failed: {e}"



@tool
def read_google_doc(doc_id: str) -> str:
    """Read the full text content of a Google Document.

    Args:
        doc_id: The Google Document ID.
    """
    try:
        doc = _svc().documents().get(documentId=doc_id).execute()
        title = doc.get("title", "Untitled Document")
        body = doc.get("body", {}).get("content", [])

        text_runs = []
        for element in body:
            paragraph = element.get("paragraph")
            if not paragraph:
                continue
            for run in paragraph.get("elements", []):
                text_run = run.get("textRun")
                if text_run:
                    text_runs.append(text_run.get("content", ""))

        full_text = "".join(text_runs).strip()
        return f"📄 **{title}** (`{doc_id}`):\n\n{full_text}"
    except Exception as e:
        return f"⚠️ Read doc failed: {e}"


@tool
def append_text_to_doc(doc_id: str, text: str) -> str:
    """Append text to the very end of a Google Document.

    Args:
        doc_id: The Google Document ID.
        text: The text string to append.
    """
    try:
        doc = _svc().documents().get(documentId=doc_id).execute()
        content = doc.get("body", {}).get("content", [])
        end_index = content[-1]["endIndex"] - 1 if content else 1

        requests = [{"insertText": {"location": {"index": end_index}, "text": f"\n{text}"}}]
        _svc().documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
        return f"✅ Appended text to document `{doc_id}`"
    except Exception as e:
        return f"⚠️ Append text failed: {e}"


@tool
def insert_text_at_index(doc_id: str, index: int, text: str) -> str:
    """Insert text at a specific character index within a Google Document.

    Args:
        doc_id: The Google Document ID.
        index: Character index location (1-based start index).
        text: Text string to insert.
    """
    try:
        requests = [{"insertText": {"location": {"index": index}, "text": text}}]
        _svc().documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
        return f"✅ Inserted text at index {index} in document `{doc_id}`"
    except Exception as e:
        return f"⚠️ Insert text failed: {e}"


@tool
def replace_text_in_doc(doc_id: str, find: str, replace: str, match_case: bool = True) -> str:
    """Global find & replace across a Google Document (e.g. swapping {{CLIENT_NAME}} placeholders).

    Args:
        doc_id: The Google Document ID.
        find: Target search string.
        replace: Replacement text string.
        match_case: Case sensitivity boolean (default True).
    """
    try:
        requests = [{
            "replaceAllText": {
                "containsText": {"text": find, "matchCase": match_case},
                "replaceText": replace,
            }
        }]
        res = _svc().documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
        occurrences = res.get("replies", [{}])[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
        return f"✅ Replaced {occurrences} occurrence(s) of '{find}' with '{replace}' in doc `{doc_id}`"
    except Exception as e:
        return f"⚠️ Replace text failed: {e}"


@tool
def delete_doc_text_range(doc_id: str, start_index: int, end_index: int) -> str:
    """Delete a range of text characters from a Google Document.

    Args:
        doc_id: The Google Document ID.
        start_index: Starting character index.
        end_index: Ending character index.
    """
    try:
        requests = [{"deleteContentRange": {"range": {"startIndex": start_index, "endIndex": end_index}}}]
        _svc().documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
        return f"✅ Deleted text range [{start_index}:{end_index}] from document `{doc_id}`"
    except Exception as e:
        return f"⚠️ Delete text range failed: {e}"


@tool
def style_doc_text_range(
    doc_id: str,
    start_index: int,
    end_index: int,
    bold: Optional[bool] = None,
    italic: Optional[bool] = None,
    underline: Optional[bool] = None,
    font_size_pt: Optional[float] = None
) -> str:
    """Apply character-level formatting (bold, italic, underline, font size) to a range of text in a Google Doc.

    Args:
        doc_id: The Google Document ID.
        start_index: Starting character index.
        end_index: Ending character index.
        bold: Optional boolean for bold formatting.
        italic: Optional boolean for italic formatting.
        underline: Optional boolean for underline formatting.
        font_size_pt: Optional font size in points (e.g. 14.0).
    """
    try:
        text_style: dict = {}
        fields = []
        if bold is not None:
            text_style["bold"] = bold
            fields.append("bold")
        if italic is not None:
            text_style["italic"] = italic
            fields.append("italic")
        if underline is not None:
            text_style["underline"] = underline
            fields.append("underline")
        if font_size_pt is not None:
            text_style["fontSize"] = {"magnitude": font_size_pt, "unit": "PT"}
            fields.append("fontSize")

        if not fields:
            return "⚠️ No styling properties specified to apply."

        requests = [{
            "updateTextStyle": {
                "range": {"startIndex": start_index, "endIndex": end_index},
                "textStyle": text_style,
                "fields": ",".join(fields),
            }
        }]
        _svc().documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
        return f"✅ Applied styling ({', '.join(fields)}) to range [{start_index}:{end_index}] in doc `{doc_id}`"
    except Exception as e:
        return f"⚠️ Style text failed: {e}"


@tool
def insert_doc_page_break(doc_id: str, index: int) -> str:
    """Insert a page break at a specific character index in a Google Document.

    Args:
        doc_id: The Google Document ID.
        index: Character index location to insert the page break.
    """
    try:
        requests = [{"insertPageBreak": {"location": {"index": index}}}]
        _svc().documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
        return f"✅ Inserted page break at index {index} in document `{doc_id}`"
    except Exception as e:
        return f"⚠️ Insert page break failed: {e}"
