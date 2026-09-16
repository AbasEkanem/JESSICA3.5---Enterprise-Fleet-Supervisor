---
name: drive-lifecycle-and-sharing
description: File and folder management, hierarchical storage, search query construction, export conversions, permission controls, and HITL safety gates in Google Drive.
---

# Drive Lifecycle & Sharing Skill

Operating guide for file storage, search, folder structure, sharing, and safety protocols in Google Drive.

## When to Use
- Managing files, folders, or permissions in Google Drive.
- Searching for existing files across the connected Google Workspace.
- Exporting Google Docs, Sheets, or Slides to external formats (PDF, CSV, XLSX, etc.).
- Sharing files with individuals or managing access permissions.
- Deleting or trashing files (HITL approval required).

## Technical Capabilities & Rules

### 1. Drive Search Query Construction
The `search_drive_files` tool uses Google Drive API `q` syntax. Always construct specific queries to avoid timeouts on large corporate corpora:
- Search by name: `name contains 'Project Delta'`
- Restrict to active files: `trashed = false`
- Filter by MIME type:
  - Folders: `mimeType = 'application/vnd.google-apps.folder'`
  - Docs: `mimeType = 'application/vnd.google-apps.document'`
  - Sheets: `mimeType = 'application/vnd.google-apps.spreadsheet'`
  - Slides: `mimeType = 'application/vnd.google-apps.presentation'`
- Filter by parent directory: `'<folder_id>' in parents`
- Combine with boolean operators: `name contains 'Q3' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false`

### 2. Folder Organization & File Moves
- When creating a folder hierarchy, create the parent folder first, capture `parent_id`, then create subfolders with `parent_id`.
- Use `move_drive_file(file_id, folder_id)` to organize assets cleanly. Do not leave project deliverables in the Drive root.

### 3. File Exports
Native Google Workspace files cannot be downloaded as raw binaries directly; they must be exported via `export_drive_file`:
- Google Doc ➔ PDF (`application/pdf`) or Word (`application/vnd.openxmlformats-officedocument.wordprocessingml.document`)
- Google Sheet ➔ PDF (`application/pdf`) or Excel (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`) or CSV (`text/csv`)
- Google Slides ➔ PDF (`application/pdf`) or PowerPoint (`application/vnd.openxmlformats-officedocument.presentationml.presentation`)

### 4. Permission Levels & Sharing
- `role`: `'reader'`, `'commenter'`, `'writer'`.
- `share_drive_file(file_id, email, role, notify=True)`: Use for individual, targeted sharing.
- Verify recipient email address format before calling.

### 5. HITL Safety Gates (Non-Negotiable)
The following operations trigger a safety pause before execution:
- `delete_drive_file`: Permanent removal. Never execute routinely.
- `trash_drive_file`: Soft delete into trash bin.
- `share_drive_file_with_anyone`: Makes file accessible to anyone on the internet with the link.
- `bulk_share_drive_files`: Sharing multiple files simultaneously.

**Protocol:** When these tools are requested, pause and formulate an explicit confirmation warning for Jessica stating:
1. Exact file name and ID.
2. The irreversible consequence or privacy exposure.
3. Explicit request for human authorization.
