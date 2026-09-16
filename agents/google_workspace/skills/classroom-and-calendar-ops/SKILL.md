---
name: classroom-and-calendar-ops
description: Course structure management, student coursework and grading governance in Google Classroom, combined with event scheduling, free/busy resolution, and invite management in Google Calendar.
---

# Classroom & Calendar Operations Skill

Operating guide for educational lifecycle management in Google Classroom and executive scheduling in Google Calendar.

## When to Use
- Creating courses, managing student and teacher rosters, or course invitations.
- Creating assignments, evaluating student submissions, recording grades, and posting announcements.
- Scheduling meetings, checking attendee availability, sending calendar invites, and cancelling events.

## Technical Execution Process

### 1. Classroom Fleet Separation (CRIT-03 Rule)
Never conflate course infrastructure with student-facing coursework:

- **Structure & Rosters (Sam — `classroom_service`):**
  - Course CRUD: `create_course`, `list_courses`, `get_course_details`, `update_course`, `delete_course`.
  - Rosters: `list_students`, `list_teachers`, `add_student_to_course`, `remove_student_from_course`, `invite_user_to_course`.
  - *Safety:* `delete_course` destroys all enrolled students and submitted work — permanently HITL-gated.
- **Coursework & Student Work (Juliet — `coursework_service`):**
  - Assignments: `create_assignment(course_id, title, description, max_points, due_date, due_time, topic_id)`.
  - Student Submissions: `list_student_submissions(course_id, coursework_id)`, `get_student_submission`.
  - Grading & Feedback: `grade_submission(course_id, coursework_id, submission_id, assigned_grade, draft_grade)`.
  - Returns: `return_submission(course_id, coursework_id, submission_id)`.
  - Communication: `create_announcement`, `list_announcements`.

### 2. Classroom Grading Discipline & Audit Trail
- **Real-World Impact:** Modifying grades touches live academic records and affects student standing.
- **Draft vs Assigned:**
  - Setting `draft_grade` allows review without student notification.
  - Setting `assigned_grade` commits the grade to the student record.
- **Returning Work:** Calling `return_submission` officially publishes the grade and triggers an automated email to the student. Only call `return_submission` when the user explicitly commands that work be returned.

### 3. Calendar Scheduling (Casey — `calendar_service`)
- **Absolute Datetime Resolution:** Never pass vague relative dates ("tomorrow", "next Tuesday at 2pm") to calendar tools.
  - Query current time via `get_current_datetime` first.
  - Compute exact RFC 3339 / ISO 8601 strings: e.g. `'2026-09-16T15:00:00+01:00'`.
- **Availability Pre-Check:** Before scheduling group events, call `check_calendar_freebusy(time_min, time_max, calendar_ids)` to identify conflicts.
- **Event Creation:** Include clear `summary`, `description`, `start_time`, `end_time`, `time_zone`, and `attendee_emails`.
- **Soft Cancel vs Hard Delete:**
  - `cancel_calendar_event(calendar_id, event_id)`: Marks event status as `'cancelled'`, retains event history, and notifies attendees cleanly. **Always prefer this.**
  - `delete_calendar_event(calendar_id, event_id)`: Completely purges event from Google Calendar servers without trace. **HITL-gated.**

## Quality Standards
- Course IDs, Coursework IDs, and Submission IDs must be passed verbatim without truncation.
- Calendar event times must include timezone offsets.
- Always report attendee notification status back to Jessica.
