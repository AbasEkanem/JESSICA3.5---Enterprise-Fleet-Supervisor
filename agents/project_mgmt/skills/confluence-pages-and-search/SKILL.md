---
name: confluence-pages-and-search
description: >
  Step-by-step workflow for creating, reading, updating, and searching Confluence
  pages, and adding page comments. Covers the CQL syntax rules and the storage-format
  XHTML body requirement.
---

# Confluence Pages and Search Skill

## When to use this skill
Use this skill for any multi-step Confluence operation: creating documentation from
Jira sprint output, updating release notes, searching spaces for existing pages, or
adding review comments to a page.

---

## Step 1 — Confirm space key

Always confirm the Confluence space key before creating a page.
Common spaces: `ENG` (Engineering), `PM` (Product Management), `OPS` (Operations).

---

## Step 2 — Create a page

`body` must be **Confluence storage-format XHTML** — NOT Markdown.

Minimal example:
```python
create_confluence_page(
    title="Sprint 42 Release Notes",
    space_key="ENG",
    body="<p>Features shipped in Sprint 42:</p><ul><li>OAuth token refresh</li></ul>",
    parent_id="123456",  # optional — omit for space-root page
)
```

**Converting Markdown → Storage format** (do this before calling the tool):
| Markdown | Storage-format XHTML |
|---|---|
| `# Heading` | `<h1>Heading</h1>` |
| `**bold**` | `<strong>bold</strong>` |
| `- item` | `<ul><li>item</li></ul>` |
| `` `code` `` | `<code>code</code>` |

---

## Step 3 — Read a page

```python
get_confluence_page(page_id="123456")
```

Returns: title, space key, first 700 chars of body, and the web URL.

---

## Step 4 — Update a page

```python
update_confluence_page(
    page_id="123456",
    title="Sprint 42 Release Notes (Final)",   # optional — keep existing if omitted
    body="<p>Updated content in storage format.</p>",
)
```

If only updating body: the tool fetches the existing title automatically.
If only updating title: pass `body=None`.

---

## Step 5 — Search with CQL

```python
search_confluence(
    cql='type = page AND space = "ENG" AND text ~ "OAuth"',
    limit=10,
)
```

Common CQL patterns:
| Goal | CQL |
|---|---|
| Pages in space | `type = page AND space = "ENG"` |
| Text contains keyword | `text ~ "keyword"` |
| Created this month | `created >= startOfMonth()` |
| Pages with label | `label = "release-notes"` |

---

## Step 6 — Add a comment

```python
add_confluence_comment(page_id="123456", comment="Reviewed and approved for publication.")
```

---

## Output contract

End with:
```
EXPERIENCE: <action + outcome in ≤20 words>
RESULT: page_id=<ID|->; url=<URL|->; status=<done|failed>
```
