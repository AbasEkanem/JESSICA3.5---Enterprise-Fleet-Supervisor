---
name: cross-service-orchestration
description: End-to-end pipeline coordination across multiple Google Workspace services — sequences Drive, Docs, Sheets, Slides, Forms, and Classroom with stateful ID chaining and todo tracking.
---

# Cross-Service Orchestration Skill

Master workflow guide for Gemma when executing multi-service Google Workspace directives delegated by Jessica 3.5.

## When to Use
- Any user request that spans 2 or more Google services (e.g. "Create a spreadsheet of data, build a slide presentation with the charts, save both into a Drive folder, and share with team").
- Chained workflows where output IDs from Service A (e.g. `spreadsheet_id`, `doc_id`, `form_id`) are required as inputs to Service B.
- Comprehensive workspace audits or migrations.

## Technical Execution Process

### 1. Todo Scratchpad Decomposition (`write_todos`)
Decompose the request into ordered, atomic steps tagged by service.
```markdown
- [ ] Step 1 [sheets_service]: Generate data table and calculate KPI summary formulas.
- [ ] Step 2 [slides_service]: Generate presentation deck linking the KPI chart from Step 1.
- [ ] Step 3 [drive_service]: Create dedicated project folder and move Sheet + Slides inside.
- [ ] Step 4 [drive_service]: Share folder with requested stakeholders.
- [ ] Step 5 [gemma_audit]: Verify all URLs and permissions, then synthesize report for Jessica.
```

### 2. ID Extraction & Parameter Chaining
Every service returns structured outputs containing resource IDs and URLs:
- Capture `spreadsheet_id` from `sheets_service` ➔ pass to `slides_service` (`embed_sheets_chart_on_slide`).
- Capture `file_id` from `docs_service` / `sheets_service` / `slides_service` ➔ pass to `drive_service` (`move_drive_file`, `share_drive_file`).
- Capture `folder_id` from `drive_service` (`create_drive_folder`) ➔ pass to subsequent file creations as destination.
- Capture `form_id` from `forms_service` ➔ pass to `publish_google_form`.

### 3. Sequential Execution Discipline
- Complete Phase 1 fully before starting Phase 2.
- Never delegate Phase 2 with placeholder IDs (e.g. `"SHEET_ID_HERE"`). Always inject the verified runtime ID.
- Update the scratchpad immediately upon completing each phase (`status: completed`).

### 4. Error Isolation & Recovery
- If a downstream step fails (e.g. sharing fails after deck creation):
  - Do NOT roll back or delete created assets unless explicitly instructed.
  - Record the created resource IDs so they are never lost.
  - Retry the failed step with adjusted parameters.
  - If still failing, mark `blocked` and report all successfully created assets to Jessica.

## Quality Gates
- Every created asset has its URL (`webViewLink`) and ID verified before reporting.
- All scratchpad todos must be checked off (`completed`).
- Standard telemetry lines (`EXPERIENCE:` and `RESULT:`) returned for each service engaged.
