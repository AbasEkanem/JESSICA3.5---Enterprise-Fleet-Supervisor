---
name: report-and-email-delivery
description: Final formatting and delivery of research insights — polished reports delivered via chat, email (email_agent), Google Docs (docs_agent), or Sheets (sheets_agent).
---

# Report & Delivery Skill

**Step 3 of 3:** `research-engine → analysis-synthesis → [report-and-email-delivery]` — runs LAST, after steps 1–2.

## When to Use
Analysed research needs to become a formatted report — in chat, as a Google Doc/Sheet, or emailed.

## Delivery Options

### 1. In-Chat Report (markdown)
Title (topic + date) → **Executive Summary** (2–3 sentences, stands alone) → **Key Findings** (numbered, each with source URL) → **Detailed Analysis** (by theme) → **Sources** (URL + engine) → **Gaps & Limitations**.

### 2. Google Doc (via `docs_agent`)
Format the report, then delegate: *"Create a Google Doc titled '[Title]' and add: [content]"*. Return the doc ID + link. If it must then be moved/renamed/shared, delegate that follow-up to `drive_agent`.

### 3. Google Sheet (via `sheets_agent`)
For tabular/numeric data: delegate *"Create a Sheet titled '[Title]', tab '[Name]', headers + rows: [data]"*. Return spreadsheet ID + link.

### 4. Email (via `email_agent` / `send_research_email`)
1. **Confirm recipient** (never send without it) — `search_memory` for saved addresses.
2. `get_current_datetime` for the report date.
3. Delegate: *"Send a research report email to [recipient] about [topic]: [content]"*.
4. Report the actual send status; `manage_memory` to save the recipient if new.

**Email subjects:** Research Report — `Research Report — [Topic] | [Date]`; Meeting Request — `Meeting Request — [Topic] | [Date]` (include date/time/duration/agenda); General — clear specific line. Use `send_at` for scheduled email.

## Pre-Delivery Checklist
✅ All findings sourced & cited · ✅ No placeholder/TBD text · ✅ Executive summary stands alone · ✅ Recipient confirmed (if emailing) · ✅ Dated via `get_current_datetime`.

## Post-Delivery
Save new recipient to memory; report final status, document URLs, or send confirmation.
