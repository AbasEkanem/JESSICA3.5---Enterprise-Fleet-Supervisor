---
name: jira-issue-lifecycle
description: >
  Step-by-step workflow for creating, searching, updating, transitioning, assigning,
  and commenting on Jira issues. Covers plain-English JQL building, subtask creation
  rules, and the accountId resolution requirement for assignees on Jira Cloud.
---

# Jira Issue Lifecycle Skill

## When to use this skill
Use this skill for any multi-step Jira operation: sprint planning, bulk updates,
status transition sequences, creating issues with subtasks, or any task that
requires more than one Jira API call in a coordinated sequence.

---

## Step 1 — Identify the project

If `project_key` is not provided by the caller:
1. Ask the caller for the project key OR check `JIRA_DEFAULT_PROJECT` in env.
2. Default: `BSE`.

---

## Step 2 — Resolve users before assigning

**Jira Cloud does NOT support `assignee = "Full Name"` in JQL.**
Always resolve user names / email addresses to `accountId` via `search_jira_users`
before calling `assign_jira_issue` or building JQL with an assignee clause.

```python
# Correct flow
users = search_jira_users(query="jane.doe@example.com")
# Extract accountId from the result, then:
assign_jira_issue(issue_key="BSE-123", assignee="jane.doe@example.com")
```

---

## Step 3 — Create issue or subtask

**Top-level issue**:
```python
create_jira_issue(
    summary="Implement OAuth token refresh",
    description="...",
    issue_type="Story",          # or "Bug", "Task", "Epic"
    project_key="BSE",
    priority="High",
    assignee_email="dev@example.com",
    labels=["auth", "security"],
)
```

**Subtask** (must be same project as parent):
```python
create_jira_issue(
    summary="Write unit tests for token refresh",
    description="...",
    parent_key="BSE-123",        # triggers subtask mode
)
```

---

## Step 4 — Search issues

| Input type | Call |
|---|---|
| Plain English ("all open bugs assigned to Jane") | `search_jira_issues(query="...")` — auto-builds JQL |
| Direct JQL | `search_jira_issues(query="project = BSE AND status = 'In Progress' ORDER BY updated DESC")` |
| My issues | `list_my_jira_issues()` |
| Project issues | `get_jira_project_issues(project_key="BSE", status_filter="To Do")` |

---

## Step 5 — Transition status

Available status names depend on the Jira workflow. Common values:
`"To Do"`, `"In Progress"`, `"In Review"`, `"Done"`, `"Closed"`.

```python
transition_jira_issue(issue_key="BSE-456", status="In Progress")
```

If transition fails, surface the error — do NOT guess alternate status names.

---

## Step 6 — Comment

```python
add_jira_comment(issue_key="BSE-456", comment="Sprint review complete. Moved to Done.")
get_jira_comments(issue_key="BSE-456", max_comments=10)
```

---

## Output contract

End with:
```
EXPERIENCE: <action + outcome in ≤20 words>
RESULT: key=<ISSUE_KEY|->; status=<done|failed>
```
