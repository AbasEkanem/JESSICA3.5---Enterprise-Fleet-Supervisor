"""
agents/project_mgmt/jira.py
============================
Complete Jira tools for Jessica 3.5.

Covers: create, get, search, list, update, transition, assign, comment.
Implements smart JQL building from plain English including name→accountId resolution.
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from langchain.tools import tool
from atlassian import Jira
from requests.exceptions import RequestException

load_dotenv()

log = logging.getLogger(__name__)


# ── Exceptions ───────────────────────────────────────────────────────────────

class SubtaskUnsupportedError(Exception):
    pass

class SubtaskVerificationError(Exception):
    pass

class MissingConfigError(Exception):
    pass


# ── Clients ───────────────────────────────────────────────────────────────────

def _require_env(*names: str) -> None:
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        raise MissingConfigError(f"Missing required environment variable(s): {', '.join(missing)}")


@lru_cache(maxsize=1)
def _jira() -> Jira:
    _require_env("JIRA_URL", "JIRA_USERNAME", "JIRA_API_TOKEN")
    return Jira(
        url=os.getenv("JIRA_URL", ""),
        username=os.getenv("JIRA_USERNAME", ""),
        password=os.getenv("JIRA_API_TOKEN", ""),
        cloud=True,
        timeout=int(os.getenv("JIRA_REQUEST_TIMEOUT_S", "30")),
    )


# ── Private helpers ──────────────────────────────────────────────────────────

def _default_project() -> str:
    return os.getenv("JIRA_DEFAULT_PROJECT", "BSE")

def _jql_escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')

def _extract_text(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts: list[str] = []
        def _walk(node):
            if isinstance(node, dict):
                if node.get("type") == "text" and "text" in node:
                    parts.append(node["text"])
                for child in node.get("content", []) or []:
                    _walk(child)
            elif isinstance(node, list):
                for child in node:
                    _walk(child)
        _walk(value)
        return " ".join(parts).strip()
    return str(value)

def _get_issue_project_key(jira: Jira, issue_key: str) -> str:
    issue = jira.issue(issue_key, fields="project")
    return issue["fields"]["project"]["key"]

def _get_project_issue_types(jira: Jira, project_key: str) -> list[dict]:
    meta = jira.issue_createmeta_issuetypes(project_key)
    values = meta.get("values", []) if isinstance(meta, dict) else (meta or [])
    return [{"id": t["id"], "name": t["name"], "subtask": bool(t.get("subtask"))} for t in values]

def _get_subtask_issue_types(jira: Jira, project_key: str) -> list[dict]:
    meta = jira.issue_createmeta_issuetypes(project_key)
    values = meta.get("values", []) if isinstance(meta, dict) else (meta or [])
    return [{"id": t["id"], "name": t["name"], "subtask": bool(t.get("subtask"))} for t in values if t.get("subtask")]

def _parent_field_supported(jira: Jira, project_key: str, issue_type_id: str) -> bool:
    try:
        fields_meta = jira.issue_createmeta_fieldtypes(project_key, issue_type_id)
        values = fields_meta.get("values", []) if isinstance(fields_meta, dict) else []
        return "parent" in {f.get("fieldId", "") for f in values}
    except Exception:
        return False

def _pick_subtask_issue_type(subtask_types: list[dict], hint: Optional[str]) -> dict:
    if not subtask_types:
        raise SubtaskUnsupportedError("No subtask types available in project.")
    if not hint or hint.strip().lower() in ("", "subtask", "sub-task"):
        for t in subtask_types:
            if t["name"].lower() in ("sub-task", "subtask"):
                return t
        return subtask_types[0]
    hint_lc = hint.strip().lower()
    for t in subtask_types:
        if hint_lc == t["name"].lower():
            return t
    for t in subtask_types:
        if hint_lc in t["name"].lower() or t["name"].lower() in hint_lc:
            return t
    return subtask_types[0]


_JQL_FIELDS = {
    "project", "status", "assignee", "reporter", "priority", "issuetype",
    "key", "text", "summary", "description", "labels", "fixversion",
    "affectedversion", "created", "updated", "resolution", "resolved",
    "sprint", "component", "duedate", "comment", "parent", "watcher",
    "worklogauthor", "issuekey",
}

def _looks_like_jql(query: str) -> bool:
    q = query.strip()
    if re.search(r"\border\s+by\b", q, re.IGNORECASE):
        return True
    m = re.match(r"^(\w+)\s*(=|!=|~|!~|>=|<=|>|<|\bin\b|\bnot\s+in\b|\bis\b|\bwas\b)\s", q, re.IGNORECASE)
    return bool(m) and m.group(1).lower() in _JQL_FIELDS

def _build_search_jql(jira: Jira, query: str) -> str:
    """Build JQL from plain English, resolving person names to accountIds when detected."""
    q_lower = query.lower()
    assignee_match = re.search(r'assigned?\s+to\s+([a-z\s]+?)(?:\s+and|\s+or|$)', q_lower, re.IGNORECASE)
    reporter_match = re.search(r'reported?\s+by\s+([a-z\s]+?)(?:\s+and|\s+or|$)', q_lower, re.IGNORECASE)
    type_match = re.search(r'\b(bug|task|story|epic|sub-task|subtask)s?\b', q_lower, re.IGNORECASE)
    jql_parts = []

    if type_match:
        issue_type = type_match.group(1)
        if issue_type.lower() in ('sub-task', 'subtask'):
            jql_parts.append('issuetype = Sub-task')
        else:
            jql_parts.append(f'issuetype = {issue_type.capitalize()}')

    if assignee_match:
        name = assignee_match.group(1).strip()
        try:
            users = jira.user_find_by_user_string(query=name, limit=3, include_inactive_users=False)
            if users:
                account_id = users[0]['accountId']
                jql_parts.append(f'assignee = "{_jql_escape(account_id)}"')
            else:
                jql_parts.append(f'text ~ "{_jql_escape(query)}"')
        except Exception:
            jql_parts.append(f'text ~ "{_jql_escape(query)}"')
    elif reporter_match:
        name = reporter_match.group(1).strip()
        try:
            users = jira.user_find_by_user_string(query=name, limit=3, include_inactive_users=False)
            if users:
                account_id = users[0]['accountId']
                jql_parts.append(f'reporter = "{_jql_escape(account_id)}"')
            else:
                jql_parts.append(f'text ~ "{_jql_escape(query)}"')
        except Exception:
            jql_parts.append(f'text ~ "{_jql_escape(query)}"')

    if not jql_parts or (not assignee_match and not reporter_match and type_match):
        jql_parts.append(f'text ~ "{_jql_escape(query)}"')

    return ' AND '.join(jql_parts) + ' ORDER BY updated DESC'


# ── JIRA COMMENT BUDGET ───────────────────────────────────────────────────────
# Raised from 300 to preserve full QA findings, security notes, etc.
_JIRA_COMMENT_CHAR_BUDGET = 4000


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def create_jira_issue(
    summary: str,
    description: str,
    issue_type: Optional[str] = None,
    project_key: Optional[str] = None,
    priority: Optional[str] = None,
    assignee_email: Optional[str] = None,
    labels: Optional[list[str]] = None,
    parent_key: Optional[str] = None,
) -> str:
    """Create a new Jira issue or subtask."""
    try:
        jira = _jira()
        if parent_key:
            parent_project = _get_issue_project_key(jira, parent_key)
            project = project_key or parent_project
            if project_key and project_key.upper() != parent_project.upper():
                return f"⚠️ Can't create subtask under {parent_key}: different project."
            subtask_types = _get_subtask_issue_types(jira, project)
            if not subtask_types:
                raise SubtaskUnsupportedError(f"Project '{project}' has no Sub-task type.")
            chosen = _pick_subtask_issue_type(subtask_types, issue_type)
            if not _parent_field_supported(jira, project, chosen["id"]):
                raise SubtaskUnsupportedError(f"Issue type '{chosen['name']}' does not support parent field.")
            type_note = f"\n\nOriginally requested type: {issue_type}" if issue_type and issue_type.strip().lower() not in chosen["name"].lower() else ""
            fields = {
                "project": {"key": project},
                "summary": summary,
                "description": description + type_note,
                "issuetype": {"id": chosen["id"]},
                "parent": {"key": parent_key},
            }
            type_label = chosen["name"]
        else:
            effective_type = issue_type or "Task"
            project = project_key or _default_project()
            available = _get_project_issue_types(jira, project)
            non_subtask = [t for t in available if not t["subtask"]]
            match = next((t for t in non_subtask if t["name"].lower() == effective_type.strip().lower()), None)
            if not match:
                names = ", ".join(t["name"] for t in non_subtask) or "none"
                return f"⚠️ Issue type '{effective_type}' not valid. Available: {names}."
            fields = {
                "project": {"key": project},
                "summary": summary,
                "description": description,
                "issuetype": {"id": match["id"]},
            }
            type_label = match["name"]

        if priority:
            fields["priority"] = {"name": priority}
        if labels:
            fields["labels"] = labels
        if assignee_email:
            users = jira.user_find_by_user_string(query=assignee_email, limit=1)
            if not users:
                return f"⚠️ User '{assignee_email}' not found."
            fields["assignee"] = {"accountId": users[0]["accountId"]}

        issue = jira.issue_create(fields=fields)
        key = issue.get("key", "?")
        url = f"{os.getenv('JIRA_URL', '')}/browse/{key}"

        if parent_key:
            created = jira.issue(key, fields="parent")
            if not (created.get("fields") or {}).get("parent"):
                raise SubtaskVerificationError(f"Parent link not attached for {key}.")

        parent_note = f" under {parent_key}" if parent_key else ""
        return f"✅ Created {key} ({type_label}{parent_note}): {url}"

    except (SubtaskUnsupportedError, SubtaskVerificationError) as e:
        return f"⚠️ {e}"
    except MissingConfigError as e:
        return f"⚠️ {e}"
    except RequestException as e:
        return f"⚠️ Network error: {e}"
    except Exception as e:
        return f"⚠️ Couldn't create issue: {e}"


@tool
def search_jira_users(query: str, max_results: int = 10, include_inactive: bool = False) -> str:
    """Search for Jira users by email, name, or username."""
    try:
        jira = _jira()
        users = jira.user_find_by_user_string(
            query=query, start=0, limit=max_results, include_inactive_users=include_inactive
        )
        if not users:
            return f"No users found matching '{query}'."
        lines = [f"Users matching '{query}':"]
        for u in users:
            active = "✅ Active" if u.get("active") else "⚠️ Inactive"
            lines.append(
                f"• {u.get('displayName')} ({u.get('emailAddress', 'no-email')}) "
                f"[{u.get('accountId')}] — {active}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ User search failed: {e}"


@tool
def assign_jira_issue(issue_key: str, assignee: str) -> str:
    """Assign a Jira issue to a user (or unassign if assignee is empty/null)."""
    try:
        jira = _jira()
        if not assignee or str(assignee).strip().lower() in ("", "none", "unassign", "null"):
            jira.update_issue_field(issue_key, {"assignee": None})
            return f"✅ {issue_key} unassigned."
        users = jira.user_find_by_user_string(
            query=str(assignee).strip(), start=0, limit=5, include_inactive_users=False
        )
        if not users:
            return f"⚠️ No active user found for '{assignee}'. Try search_jira_users first."
        if len(users) > 1:
            suggestions = "\n".join([
                f"  • {u['displayName']} ({u.get('emailAddress', 'N/A')})" for u in users[:3]
            ])
            return f"⚠️ Multiple users found for '{assignee}'. Be more specific:\n{suggestions}"
        jira.update_issue_field(issue_key, {"assignee": {"accountId": users[0]["accountId"]}})
        return f"✅ {issue_key} assigned to **{users[0]['displayName']}**"
    except Exception as e:
        return f"⚠️ Assign failed: {e}"


@tool
def get_jira_issue(issue_key: str) -> str:
    """Get full details of a Jira issue."""
    try:
        jira = _jira()
        issue = jira.issue(issue_key)
        f = issue["fields"]
        return (
            f"*{issue_key}* — {f.get('summary', 'N/A')}\n"
            f"Type: {f['issuetype']['name']} | Status: {f['status']['name']} | "
            f"Priority: {(f.get('priority') or {}).get('name', 'None')}\n"
            f"Assignee: {(f.get('assignee') or {}).get('displayName', 'Unassigned')} | "
            f"Reporter: {(f.get('reporter') or {}).get('displayName', 'Unknown')}\n"
            f"Description: {_extract_text(f.get('description'))[:600]}\n"
            f"Link: {os.getenv('JIRA_URL', '')}/browse/{issue_key}"
        )
    except Exception as e:
        return f"⚠️ Couldn't fetch {issue_key}: {e}"


@tool
def search_jira_issues(query: str, max_results: int = 10) -> str:
    """Search Jira issues using plain English or JQL.

    Plain-English queries are matched against issue text AND against assignee /
    reporter display names. Jira Cloud does NOT allow assignee = "Full Name"
    directly — we resolve names to accountIds via the user search API.
    """
    try:
        jira = _jira()
        if _looks_like_jql(query):
            jql = query
        else:
            jql = _build_search_jql(jira, query)
        issues = jira.jql(jql, limit=max_results).get("issues", [])
        if not issues:
            return "No issues found."
        return "\n".join([
            f"• *{i['key']}* [{i['fields']['status']['name']}] "
            f"{i['fields'].get('summary', '')} — "
            f"_{(i['fields'].get('assignee') or {}).get('displayName', 'Unassigned')}_"
            for i in issues
        ])
    except Exception as e:
        return f"⚠️ Search error: {e}"


@tool
def list_my_jira_issues(max_results: int = 10) -> str:
    """List open issues assigned to the configured user."""
    try:
        jira = _jira()
        jql = (
            f'assignee = "{_jql_escape(os.getenv("JIRA_USERNAME", ""))}" '
            f'AND resolution = Unresolved ORDER BY updated DESC'
        )
        issues = jira.jql(jql, limit=max_results).get("issues", [])
        if not issues:
            return "No open issues assigned to you."
        lines = [f"Your {len(issues)} open issue(s):"]
        for i in issues:
            lines.append(f"• *{i['key']}* [{i['fields']['status']['name']}] {i['fields'].get('summary', '')}")
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Error: {e}"


@tool
def get_jira_project_issues(
    project_key: Optional[str] = None,
    status_filter: Optional[str] = None,
    max_results: int = 15,
) -> str:
    """List issues in a Jira project, optionally filtered by status."""
    try:
        jira = _jira()
        project = project_key or _default_project()
        jql = f'project = "{_jql_escape(project)}"'
        if status_filter:
            jql += f' AND status = "{_jql_escape(status_filter)}"'
        jql += " ORDER BY updated DESC"
        issues = jira.jql(jql, limit=max_results).get("issues", [])
        if not issues:
            return f"No issues in {project}."
        return "\n".join(
            [f"Issues in *{project}*:"] +
            [f"• *{i['key']}* [{i['fields']['status']['name']}] {i['fields'].get('summary', '')}" for i in issues]
        )
    except Exception as e:
        return f"⚠️ Error: {e}"


@tool
def update_jira_issue(
    issue_key: str,
    summary: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[str] = None,
    labels: Optional[list[str]] = None,
) -> str:
    """Update Jira issue fields (summary, description, priority, labels)."""
    updates = {}
    if summary:
        updates["summary"] = summary
    if description:
        updates["description"] = description
    if priority:
        updates["priority"] = {"name": priority}
    if labels is not None:
        updates["labels"] = labels
    if not updates:
        return "Nothing to update."
    try:
        _jira().update_issue_field(issue_key, updates)
        return f"✅ Updated {issue_key}"
    except Exception as e:
        return f"⚠️ Update failed: {e}"


@tool
def transition_jira_issue(issue_key: str, status: str) -> str:
    """Transition a Jira issue to a new workflow status."""
    try:
        _jira().set_issue_status(issue_key, status)
        return f"✅ Moved {issue_key} to *{status}*"
    except Exception as e:
        return f"⚠️ Transition failed: {e}"


@tool
def add_jira_comment(issue_key: str, comment: str) -> str:
    """Add a comment to a Jira issue."""
    try:
        _jira().issue_add_comment(issue_key, comment)
        return f"✅ Comment added to {issue_key}"
    except Exception as e:
        return f"⚠️ Comment failed: {e}"


@tool
def get_jira_comments(issue_key: str, max_comments: int = 20) -> str:
    """Get recent comments on a Jira issue.

    Returns up to `max_comments` most-recent comments in full. Individual
    comments are only truncated if they exceed a large safety budget,
    and any such truncation is made explicit so data is never silently lost.
    """
    try:
        comments = _jira().issue_get_comments(issue_key).get("comments", [])
        recent = comments[-max_comments:]
        lines = [f"Last {len(recent)} comment(s) on *{issue_key}*:"]
        for c in recent:
            author = c.get("author", {}).get("displayName", "Unknown")
            body = _extract_text(c.get("body")) or ""
            if len(body) > _JIRA_COMMENT_CHAR_BUDGET:
                body = (
                    body[:_JIRA_COMMENT_CHAR_BUDGET]
                    + f" …[truncated: showing {_JIRA_COMMENT_CHAR_BUDGET} of {len(body)} chars]"
                )
            lines.append(f"_{author}_: {body}")
        return "\n".join(lines) if recent else f"No comments on {issue_key}."
    except Exception as e:
        return f"⚠️ Comments error: {e}"


# ── Export 
JIRA_TOOLS = [
    create_jira_issue,
    search_jira_users,
    assign_jira_issue,
    get_jira_issue,
    search_jira_issues,
    list_my_jira_issues,
    get_jira_project_issues,
    update_jira_issue,
    transition_jira_issue,
    add_jira_comment,
    get_jira_comments,
]

__all__ = [
    "JIRA_TOOLS",
    "create_jira_issue",
    "search_jira_users",
    "assign_jira_issue",
    "get_jira_issue",
    "search_jira_issues",
    "list_my_jira_issues",
    "get_jira_project_issues",
    "update_jira_issue",
    "transition_jira_issue",
    "add_jira_comment",
    "get_jira_comments",
    # Shared helpers exported for confluence.py
    "MissingConfigError",
    "_require_env",
    "_extract_text",
]
