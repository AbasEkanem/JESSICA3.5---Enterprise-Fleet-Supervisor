---
name: sheets-and-slides-reporting
description: Structured financial and numerical modeling in Google Sheets coupled with presentation deck design, chart embedding, and visual reporting in Google Slides.
---

# Sheets & Slides Reporting Skill

Operating guide for generating data models, calculations, tables, and presentation slide decks.

## When to Use
- Creating financial models, tracking sheets, KPIs, or data tables.
- Building executive presentations, pitch decks, workshop slides, or lecture summaries.
- Embedding live charts from Google Sheets into Google Slides.
- Refreshing linked presentation charts when data changes.

## Technical Execution Process

### 1. Spreadsheet Design & A1 Notation (Chris — `sheets_service`)
- **Explicit Tab Qualification:** Always qualify ranges with sheet names (e.g. `'Revenue!A1:E20'`, not bare `'A1:E20'`).
- **Header Structure:** Reserve Row 1 for clean column titles (e.g. `["Month", "Gross Revenue", "Operating Expenses", "Net Margin", "YoY Growth"]`).
- **Formulas:** Use standard Google Sheets formula syntax (e.g. `"=SUM(B2:B13)"`, `"=B2-C2"`).
- **Batch Operations:** For more than 2 distinct ranges, use `batch_read_sheet_ranges` to minimize round-trips and API quota consumption.
- **Pre-Read Discipline:** Always call `read_sheet_range` before overwriting existing data to verify ranges and prevent accidental data obliteration.
- **Cell Formatting:** Apply bold to headers, format numbers as currency/percentages, and align numeric columns to the right.

### 2. Presentation Deck Construction (Riley — `slides_service`)
- **Atomic Slide Creation:** Use `create_slides_deck` for complete initial decks or `add_slide_with_content` for adding populated slides. Avoid piecemeal shape-ID chaining which can fail if IDs are mismatched.
- **Slide Layouts:** Organize slides logically:
  1. Title Slide (Deck Title, Subtitle, Date, Author)
  2. Executive Summary / Agenda
  3. Content / Data Slides (Bullet points, tables, embedded charts)
  4. Conclusion / Action Items Slide
- **Images:** Insert images using `insert_image_onto_slide` with verified public HTTPS URLs.
- **Tables:** Use `create_slide_table` with calculated row/column counts and supply data as a 2D matrix.

### 3. Chart Embedding & Synchronization
1. Create or identify the chart inside the Google Sheet (capture `spreadsheet_id` and `chart_id`).
2. Delegate to Riley: `embed_sheets_chart_on_slide(presentation_id, slide_id, spreadsheet_id, chart_id)`.
3. **Critical Sync Rule:** Embedding creates a linked chart, but Google does **NOT** auto-sync when Sheet data changes. Whenever numbers in the Sheet are updated, you MUST call `refresh_slide_sheets_chart(presentation_id, element_id)` to sync the newest data visually.

## Quality Standards
- No blank or unformatted slides.
- Financial formulas must be syntactically valid and verified.
- Return both the Sheet URL (`https://docs.google.com/spreadsheets/d/...`) and Slides presentation URL (`https://docs.google.com/presentation/d/...`) to Jessica.
