---
name: docs-and-forms-automation
description: Index-accurate text editing, structural formatting, and styling in Google Docs, paired with question design, section layout, response collection, and mandatory publishing in Google Forms.
---

# Docs & Forms Automation Skill

Operating guide for generating structured textual documentation and interactive survey forms.

## When to Use
- Writing or updating memos, research briefs, agendas, policy documents, or meeting notes in Google Docs.
- Styling documents with headers, bold text, colored highlights, or page breaks.
- Creating surveys, quizzes, feedback questionnaires, or registration forms in Google Forms.
- Publishing forms for respondent submissions and extracting response data.

## Technical Execution Process

### 1. Index-Safe Document Editing (Taylor — `docs_service`)
Google Docs API positions are 1-based character offsets across document structural elements. Inserting or deleting characters shifts all downstream offsets.

- **Pre-Read Mandatory:** Before calling `insert_text_at_index` or `delete_doc_text_range`, you MUST call `read_google_doc(document_id)` to inspect the document structure and verify exact current start/end indices.
- **Append for Simple Growth:** For linear documents (reports, memos), prefer `append_text_to_doc` which automatically appends to the document end without requiring index arithmetic.
- **Styling Text Ranges:** Use `style_doc_text_range(document_id, start_index, end_index, bold=True, italic=False, font_size=12, color_rgb=(0,0,0))` to format headers and emphasized callouts.
- **Page Breaks:** Use `insert_doc_page_break(document_id, index)` to demarcate major chapters or executive summaries.

### 2. Form Construction & Mandatory Publishing (Francis — `forms_service`)
- **Initialization:** Create the form with `create_google_form(title, description)` and immediately capture the returned `form_id` and edit URL.
- **Question Layout:**
  - Short/Long Text: `add_text_question_to_form(form_id, title, paragraph=False/True, required=True/False)`.
  - Multiple Choice / Checkbox: `add_choice_question_to_form(form_id, title, options=["Option A", "Option B"], choice_type="RADIO"|"CHECKBOX"|"DROP_DOWN", required=True)`.
  - Sections: Use `add_section_header_to_form` to split multi-part surveys across pages.
- **Critical June 2026 API Mandate — Form Publishing:**
  - By default, newly created forms created via the Google Forms API are **UNPUBLISHED**.
  - Any external respondent attempting to access an unpublished form will receive an HTTP 403 or "Form not accepting responses" error.
  - **Rule:** Always call `publish_google_form(form_id)` immediately after adding all initial questions unless the user explicitly requests an unpublished draft.
- **Reading Responses:**
  - Call `get_form_responses(form_id)` to extract structured submissions.
  - Parse answers by question ID to synthesize response summaries for Jessica.

## Quality Standards
- Documents must have clear heading hierarchies (Title, Subtitle, Section Headers).
- Forms must have descriptive question titles and at least 2 choices for choice questions.
- Every form link provided to the user must be the published respondent URL (`https://docs.google.com/forms/d/e/.../viewform`), not just the private edit URL.
