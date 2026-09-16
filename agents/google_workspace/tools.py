"""
agents/google_workspace/tools.py
=================================
Consolidated tool suite for the Google Workspace Agent.
Unifies all 7 Google service domains into logical toolsets:
  1. Google Drive (file storage, permissions, uploads, exports)
  2. Google Docs (document creation, editing, styling)
  3. Google Sheets (spreadsheets, cells, tabs, formulas)
  4. Google Slides (presentations, layouts, shapes, charts)
  5. Google Forms (surveys, questions, responses)
  6. Google Calendar (events, scheduling, availability)
  7. Google Classroom (courses, rosters, coursework, grading / Juliet)
"""

from __future__ import annotations

from typing import Any

# ── 1. Google Drive Tools
from .drive import (
    bulk_share_drive_files,
    create_drive_folder,
    delete_drive_file,
    download_file_from_drive,
    export_drive_file,
    list_drive_file_permissions,
    move_drive_file,
    rename_drive_file,
    revoke_drive_file_permission,
    search_drive_files,
    share_drive_file,
    share_drive_file_with_anyone,
    trash_drive_file,
    upload_file_to_drive,
)

# ── 2. Google Docs Tools
from .docs import (
    append_text_to_doc,
    create_google_doc,
    delete_doc_text_range,
    insert_doc_page_break,
    insert_text_at_index,
    read_google_doc,
    replace_text_in_doc,
    style_doc_text_range,
)

# ── 3. Google Sheets Tools
from .sheets import (
    add_sheet_tab,
    append_sheet_row,
    batch_read_sheet_ranges,
    clear_sheet_range,
    create_google_sheet,
    delete_sheet_tab,
    format_sheet_cells,
    read_sheet_range,
    update_sheet_range,
)

# ── 4. Google Slides Tools
from .slides import (
    add_slide,
    add_slide_with_content,
    create_presentation,
    create_slide_table,
    create_slides_deck,
    delete_slide,
    duplicate_slide,
    embed_sheets_chart_on_slide,
    get_presentation_details,
    insert_image_onto_slide,
    insert_text_into_slide,
    refresh_slide_sheets_chart,
    reorder_slides,
    replace_all_text_in_slides,
    update_slide_background_color,
)

# ── 5. Google Forms Tools
from .forms import (
    add_choice_question_to_form,
    add_section_header_to_form,
    add_text_question_to_form,
    create_google_form,
    delete_form_item,
    get_form_responses,
    get_google_form_details,
    get_single_form_response,
    publish_google_form,
)

# ── 6. Google Calendar Tools
from .calendar import (
    cancel_calendar_event,
    check_calendar_freebusy,
    create_calendar_event,
    delete_calendar_event,
    get_calendar_event_details,
    list_calendar_events,
    respond_to_calendar_invitation,
    update_calendar_event,
)

# ── 7. Google Classroom & Juliet Tools
from .classroom import (
    add_student_to_course,
    create_announcement,
    create_assignment,
    create_course,
    create_course_topic,
    delete_course,
    delete_coursework,
    get_course_details,
    get_student_submission,
    grade_submission,
    invite_user_to_course,
    list_announcements,
    list_courses,
    list_course_topics,
    list_coursework,
    list_student_submissions,
    list_students,
    list_teachers,
    remove_student_from_course,
    return_submission,
    update_course,
    update_coursework,
)

# ── Grouped Categorical Tool Lists

DRIVE_TOOLS = [
    search_drive_files,
    upload_file_to_drive,
    download_file_from_drive,
    export_drive_file,
    create_drive_folder,
    move_drive_file,
    rename_drive_file,
    share_drive_file,
    bulk_share_drive_files,
    share_drive_file_with_anyone,
    list_drive_file_permissions,
    revoke_drive_file_permission,
    trash_drive_file,
    delete_drive_file,
]

DOCS_TOOLS = [
    create_google_doc,
    read_google_doc,
    append_text_to_doc,
    insert_text_at_index,
    replace_text_in_doc,
    delete_doc_text_range,
    style_doc_text_range,
    insert_doc_page_break,
]

SHEETS_TOOLS = [
    create_google_sheet,
    read_sheet_range,
    batch_read_sheet_ranges,
    update_sheet_range,
    append_sheet_row,
    clear_sheet_range,
    add_sheet_tab,
    delete_sheet_tab,
    format_sheet_cells,
]

SLIDES_TOOLS = [
    create_slides_deck,
    add_slide_with_content,
    create_presentation,
    get_presentation_details,
    add_slide,
    duplicate_slide,
    delete_slide,
    reorder_slides,
    replace_all_text_in_slides,
    insert_text_into_slide,
    insert_image_onto_slide,
    create_slide_table,
    embed_sheets_chart_on_slide,
    refresh_slide_sheets_chart,
    update_slide_background_color,
]

FORMS_TOOLS = [
    create_google_form,
    get_google_form_details,
    publish_google_form,
    add_text_question_to_form,
    add_choice_question_to_form,
    add_section_header_to_form,
    delete_form_item,
    get_form_responses,
    get_single_form_response,
]

CALENDAR_TOOLS = [
    create_calendar_event,
    list_calendar_events,
    get_calendar_event_details,
    update_calendar_event,
    delete_calendar_event,
    cancel_calendar_event,
    respond_to_calendar_invitation,
    check_calendar_freebusy,
]

CLASSROOM_COURSES_TOOLS = [
    create_course,
    list_courses,
    get_course_details,
    update_course,
    delete_course,
    list_students,
    list_teachers,
    add_student_to_course,
    remove_student_from_course,
    invite_user_to_course,
]

JULIET_COURSEWORK_TOOLS = [
    create_assignment,
    list_coursework,
    update_coursework,
    delete_coursework,
    list_student_submissions,
    get_student_submission,
    grade_submission,
    return_submission,
    create_announcement,
    list_announcements,
    create_course_topic,
    list_course_topics,
]

CLASSROOM_TOOLS = CLASSROOM_COURSES_TOOLS + JULIET_COURSEWORK_TOOLS

# ── Complete Suite of Google Workspace Tools
GOOGLE_WORKSPACE_TOOLS: list[Any] = (
    DRIVE_TOOLS
    + DOCS_TOOLS
    + SHEETS_TOOLS
    + SLIDES_TOOLS
    + FORMS_TOOLS
    + CALENDAR_TOOLS
    + CLASSROOM_TOOLS
)

# ── Service Lookup Map
GOOGLE_WORKSPACE_TOOL_MAP: dict[str, list[Any]] = {
    "drive": DRIVE_TOOLS,
    "docs": DOCS_TOOLS,
    "sheets": SHEETS_TOOLS,
    "slides": SLIDES_TOOLS,
    "forms": FORMS_TOOLS,
    "calendar": CALENDAR_TOOLS,
    "classroom_courses": CLASSROOM_COURSES_TOOLS,
    "classroom_coursework": JULIET_COURSEWORK_TOOLS,
    "classroom": CLASSROOM_TOOLS,
}

__all__ = [
    # Master collection
    "GOOGLE_WORKSPACE_TOOLS",
    "GOOGLE_WORKSPACE_TOOL_MAP",
    # Subsets
    "DRIVE_TOOLS",
    "DOCS_TOOLS",
    "SHEETS_TOOLS",
    "SLIDES_TOOLS",
    "FORMS_TOOLS",
    "CALENDAR_TOOLS",
    "CLASSROOM_TOOLS",
    "CLASSROOM_COURSES_TOOLS",
    "JULIET_COURSEWORK_TOOLS",
    # Drive tool callables
    "search_drive_files",
    "upload_file_to_drive",
    "download_file_from_drive",
    "export_drive_file",
    "create_drive_folder",
    "move_drive_file",
    "rename_drive_file",
    "share_drive_file",
    "bulk_share_drive_files",
    "share_drive_file_with_anyone",
    "list_drive_file_permissions",
    "revoke_drive_file_permission",
    "trash_drive_file",
    "delete_drive_file",
    # Docs tool callables
    "create_google_doc",
    "read_google_doc",
    "append_text_to_doc",
    "insert_text_at_index",
    "replace_text_in_doc",
    "delete_doc_text_range",
    "style_doc_text_range",
    "insert_doc_page_break",
    # Sheets tool callables
    "create_google_sheet",
    "read_sheet_range",
    "batch_read_sheet_ranges",
    "update_sheet_range",
    "append_sheet_row",
    "clear_sheet_range",
    "add_sheet_tab",
    "delete_sheet_tab",
    "format_sheet_cells",
    # Slides tool callables
    "create_slides_deck",
    "add_slide_with_content",
    "create_presentation",
    "get_presentation_details",
    "add_slide",
    "duplicate_slide",
    "delete_slide",
    "reorder_slides",
    "replace_all_text_in_slides",
    "insert_text_into_slide",
    "insert_image_onto_slide",
    "create_slide_table",
    "embed_sheets_chart_on_slide",
    "refresh_slide_sheets_chart",
    "update_slide_background_color",
    # Forms tool callables
    "create_google_form",
    "get_google_form_details",
    "publish_google_form",
    "add_text_question_to_form",
    "add_choice_question_to_form",
    "add_section_header_to_form",
    "delete_form_item",
    "get_form_responses",
    "get_single_form_response",
    # Calendar tool callables
    "create_calendar_event",
    "list_calendar_events",
    "get_calendar_event_details",
    "update_calendar_event",
    "delete_calendar_event",
    "cancel_calendar_event",
    "respond_to_calendar_invitation",
    "check_calendar_freebusy",
    # Classroom tool callables
    "create_course",
    "list_courses",
    "get_course_details",
    "update_course",
    "delete_course",
    "list_students",
    "list_teachers",
    "add_student_to_course",
    "remove_student_from_course",
    "invite_user_to_course",
    "create_assignment",
    "list_coursework",
    "update_coursework",
    "delete_coursework",
    "list_student_submissions",
    "get_student_submission",
    "grade_submission",
    "return_submission",
    "create_announcement",
    "list_announcements",
    "create_course_topic",
    "list_course_topics",
]
