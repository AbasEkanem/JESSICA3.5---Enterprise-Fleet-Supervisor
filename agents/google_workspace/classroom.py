"""
google_classroom_tools.py
============================
Full Classroom CRUD for Jessica: courses, rosters, coursework,
submissions, grading, announcements, and topics.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from langchain_core.tools import tool

from .auth import get_service

_log = logging.getLogger(__name__)


def _svc():
    return get_service("classroom")


# ── Course Management ──────────────────────────────────────────────────

@tool
def create_course(
    name: str,
    section: Optional[str] = None,
    description: Optional[str] = None,
    room: Optional[str] = None,
    owner_id: str = "me"
) -> str:
    """Create a new Google Classroom course.

    Args:
        name: Name of the course (e.g. 'Python 101').
        section: Optional section string (e.g. 'Spring 2026').
        description: Optional course description.
        room: Optional room identifier.
        owner_id: Owner user ID or 'me' (default 'me').
    """
    try:
        body: dict = {"name": name, "ownerId": owner_id}
        if section:
            body["section"] = section
        if description:
            body["descriptionHeading"] = description
        if room:
            body["room"] = room

        course = _svc().courses().create(body=body).execute()
        course_id = course["id"]
        enrollment_code = course.get("enrollmentCode", "N/A")
        return f"✅ Created Course: **{name}** (ID: `{course_id}` | Enrollment Code: `{enrollment_code}`)"
    except Exception as e:
        return f"⚠️ Create course failed: {e}"


@tool
def list_courses(
    teacher_id: Optional[str] = None,
    student_id: Optional[str] = None,
    course_states_json: Optional[str] = None
) -> str:
    """List Google Classroom courses.

    Args:
        teacher_id: Optional teacher email/ID or 'me'.
        student_id: Optional student email/ID or 'me'.
        course_states_json: Optional JSON array of states, e.g. '["ACTIVE"]' or '["ARCHIVED"]'.
    """
    try:
        kwargs: dict = {"pageSize": 30}
        if teacher_id:
            kwargs["teacherId"] = teacher_id
        if student_id:
            kwargs["studentId"] = student_id
        if course_states_json:
            kwargs["courseStates"] = json.loads(course_states_json)

        res = _svc().courses().list(**kwargs).execute()
        courses = res.get("courses", [])
        if not courses:
            return "No Google Classroom courses found."

        out = [f"🏫 **Google Classroom Courses** ({len(courses)}):"]
        for c in courses:
            state = c.get("courseState", "ACTIVE")
            out.append(f"- **{c['name']}** (ID: `{c['id']}` | Section: `{c.get('section', 'N/A')}` | State: `{state}`)")
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ List courses failed: {e}"


@tool
def get_course_details(course_id: str) -> str:
    """Get full metadata and configuration of a Google Classroom course.

    Args:
        course_id: The ID of the course.
    """
    try:
        c = _svc().courses().get(id=course_id).execute()
        out = [
            f"🏫 **{c.get('name')}** (`{course_id}`):",
            f"  Section: {c.get('section', 'N/A')}",
            f"  Room: {c.get('room', 'N/A')}",
            f"  State: {c.get('courseState', 'N/A')}",
            f"  Enrollment Code: `{c.get('enrollmentCode', 'N/A')}`",
            f"  Link: {c.get('alternateLink', 'N/A')}"
        ]
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ Get course details failed: {e}"


@tool
def update_course(course_id: str, fields_json: str) -> str:
    """Patch/Update fields of a Google Classroom course (e.g. description, courseState='ARCHIVED').

    Args:
        course_id: The ID of the course.
        fields_json: JSON dictionary of fields to update, e.g. '{"section": "Fall 2026", "courseState": "ARCHIVED"}'.
    """
    try:
        fields = json.loads(fields_json)
        update_mask = ",".join(fields.keys())
        updated = _svc().courses().patch(id=course_id, updateMask=update_mask, body=fields).execute()
        return f"✅ Updated course `{course_id}`. Current State: `{updated.get('courseState')}`"
    except Exception as e:
        return f"⚠️ Update course failed: {e}"


@tool
def delete_course(course_id: str) -> str:
    """Permanently remove an archived Google Classroom course.

    Args:
        course_id: The ID of the archived course to delete.
    """
    try:
        _svc().courses().delete(id=course_id).execute()
        return f"✅ Permanently deleted course `{course_id}`"
    except Exception as e:
        return f"⚠️ Delete course failed: {e}"


# ── Roster & Enrolment ──────────────────────────────────────────────────

@tool
def list_students(course_id: str) -> str:
    """List enrolled students in a Google Classroom course.

    Args:
        course_id: The ID of the course.
    """
    try:
        res = _svc().courses().students().list(courseId=course_id).execute()
        students = res.get("students", [])
        if not students:
            return f"No students enrolled in course `{course_id}`."

        out = [f"👥 Enrolled Students for Course `{course_id}` ({len(students)}):"]
        for s in students:
            profile = s.get("profile", {})
            name = profile.get("name", {}).get("fullName", "Unknown Name")
            email = profile.get("emailAddress", "N/A")
            out.append(f"- **{name}** (`{email}` | User ID: `{s['userId']}`)")
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ List students failed: {e}"


@tool
def list_teachers(course_id: str) -> str:
    """List teachers and co-teachers in a Google Classroom course.

    Args:
        course_id: The ID of the course.
    """
    try:
        res = _svc().courses().teachers().list(courseId=course_id).execute()
        teachers = res.get("teachers", [])
        if not teachers:
            return f"No teachers found for course `{course_id}`."

        out = [f"👨‍🏫 Teachers for Course `{course_id}` ({len(teachers)}):"]
        for t in teachers:
            profile = t.get("profile", {})
            name = profile.get("name", {}).get("fullName", "Unknown Name")
            email = profile.get("emailAddress", "N/A")
            out.append(f"- **{name}** (`{email}` | User ID: `{t['userId']}`)")
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ List teachers failed: {e}"


@tool
def add_student_to_course(course_id: str, user_id_or_email: str, enrollment_code: Optional[str] = None) -> str:
    """Directly enroll a student into a Google Classroom course.

    Args:
        course_id: The ID of the course.
        user_id_or_email: Student email address or user ID.
        enrollment_code: Optional course enrollment code.
    """
    try:
        body: dict = {"userId": user_id_or_email}
        if enrollment_code:
            body["enrollmentCode"] = enrollment_code
        student = _svc().courses().students().create(courseId=course_id, body=body).execute()
        return f"✅ Enrolled student `{user_id_or_email}` in course `{course_id}` (Student ID: `{student.get('userId')}`)"
    except Exception as e:
        return f"⚠️ Add student failed: {e}"


@tool
def remove_student_from_course(course_id: str, user_id_or_email: str) -> str:
    """Remove a student from a Google Classroom course roster.

    Args:
        course_id: The ID of the course.
        user_id_or_email: Student email address or user ID.
    """
    try:
        _svc().courses().students().delete(courseId=course_id, userId=user_id_or_email).execute()
        return f"✅ Removed student `{user_id_or_email}` from course `{course_id}`"
    except Exception as e:
        return f"⚠️ Remove student failed: {e}"


@tool
def invite_user_to_course(course_id: str, email: str, role: str = "STUDENT") -> str:
    """Send an email invitation to join a course as a student or co-teacher.

    Args:
        course_id: The ID of the course.
        email: Email address of the invited user.
        role: 'STUDENT' or 'TEACHER' (default 'STUDENT').
    """
    try:
        body = {"courseId": course_id, "userId": email, "role": role.upper()}
        inv = _svc().invitations().create(body=body).execute()
        return f"✅ Invited `{email}` as `{role.upper()}` to course `{course_id}` (Invitation ID: `{inv['id']}`)"
    except Exception as e:
        return f"⚠️ Invite user failed: {e}"


# ── Coursework ─────────────────────────────────────────────────────────────

@tool
def create_assignment(
    course_id: str,
    title: str,
    description: Optional[str] = None,
    max_points: Optional[float] = 100.0,
    due_date_json: Optional[str] = None,
    due_time_json: Optional[str] = None,
    materials_json: Optional[str] = None,
    work_type: str = "ASSIGNMENT",
    state: str = "PUBLISHED"
) -> str:
    """Create a new assignment, quiz, or short-answer question in Google Classroom.

    Args:
        course_id: The ID of the course.
        title: Title of the assignment.
        description: Instructions for students.
        max_points: Maximum points possible (default 100.0).
        due_date_json: Optional JSON object for due date, e.g. '{"year": 2026, "month": 8, "day": 15}'.
        due_time_json: Optional JSON object for due time, e.g. '{"hours": 23, "minutes": 59}'.
        materials_json: Optional JSON array of Drive files/links/videos, e.g. '[{"driveFile": {"driveFile": {"id": "<ID>"}, "shareMode": "STUDENT_COPY"}}]'.
        work_type: 'ASSIGNMENT', 'SHORT_ANSWER_QUESTION', or 'MULTIPLE_CHOICE_QUESTION'.
        state: 'PUBLISHED' or 'DRAFT' (default 'PUBLISHED').
    """
    try:
        cw_body: dict = {
            "title": title,
            "workType": work_type,
            "state": state,
        }
        if description:
            cw_body["description"] = description
        if max_points is not None:
            cw_body["maxPoints"] = max_points
        if due_date_json:
            cw_body["dueDate"] = json.loads(due_date_json)
        if due_time_json:
            cw_body["dueTime"] = json.loads(due_time_json)
        if materials_json:
            cw_body["materials"] = json.loads(materials_json)

        cw = _svc().courses().courseWork().create(courseId=course_id, body=cw_body).execute()
        cw_id = cw["id"]
        link = cw.get("alternateLink", "N/A")
        return f"✅ Created Assignment: **{title}** (ID: `{cw_id}` in course `{course_id}`)\nLink: {link}"
    except Exception as e:
        return f"⚠️ Create assignment failed: {e}"


@tool
def list_coursework(course_id: str) -> str:
    """List all coursework/assignments in a Google Classroom course.

    Args:
        course_id: The ID of the course.
    """
    try:
        res = _svc().courses().courseWork().list(courseId=course_id).execute()
        items = res.get("courseWork", [])
        if not items:
            return f"No coursework found for course `{course_id}`."

        out = [f"📚 **Coursework / Assignments** for Course `{course_id}` ({len(items)}):"]
        for cw in items:
            out.append(f"- **{cw['title']}** (ID: `{cw['id']}` | Type: `{cw.get('workType')}` | Points: `{cw.get('maxPoints', 0)}`)  Link: {cw.get('alternateLink', 'N/A')}")
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ List coursework failed: {e}"


@tool
def update_coursework(course_id: str, coursework_id: str, fields_json: str) -> str:
    """Patch/Update coursework properties (e.g. title, description, maxPoints, state='PUBLISHED').

    Args:
        course_id: The ID of the course.
        coursework_id: The ID of the assignment.
        fields_json: JSON dictionary of fields to update, e.g. '{"title": "Updated Title", "maxPoints": 50}'.
    """
    try:
        fields = json.loads(fields_json)
        update_mask = ",".join(fields.keys())
        updated = (
            _svc()
            .courses()
            .courseWork()
            .patch(courseId=course_id, id=coursework_id, updateMask=update_mask, body=fields)
            .execute()
        )
        return f"✅ Updated coursework `{coursework_id}` in course `{course_id}` (Title: **{updated.get('title')}**)"
    except Exception as e:
        return f"⚠️ Update coursework failed: {e}"


@tool
def delete_coursework(course_id: str, coursework_id: str) -> str:
    """Delete an assignment or coursework item from a course.

    Args:
        course_id: The ID of the course.
        coursework_id: The ID of the assignment to delete.
    """
    try:
        _svc().courses().courseWork().delete(courseId=course_id, id=coursework_id).execute()
        return f"✅ Deleted coursework `{coursework_id}` from course `{course_id}`"
    except Exception as e:
        return f"⚠️ Delete coursework failed: {e}"


# ── Submissions & Grading ──────────────────────────────────────────────────

@tool
def list_student_submissions(course_id: str, coursework_id: str) -> str:
    """List student submissions for a specific assignment in Google Classroom.

    Args:
        course_id: The ID of the course.
        coursework_id: The ID of the assignment/coursework item.
    """
    try:
        res = (
            _svc()
            .courses()
            .courseWork()
            .studentSubmissions()
            .list(courseId=course_id, courseWorkId=coursework_id)
            .execute()
        )
        subs = res.get("studentSubmissions", [])
        if not subs:
            return f"No submissions found for coursework `{coursework_id}`."

        out = [f"📥 **Student Submissions** ({len(subs)}):"]
        for sub in subs:
            state = sub.get("state", "NEW")
            assigned_grade = sub.get("assignedGrade", "Not Graded")
            user_id = sub.get("userId")
            out.append(f"- Submission ID: `{sub['id']}` | Student User ID: `{user_id}` | State: `{state}` | Grade: `{assigned_grade}`")
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ List submissions failed: {e}"


@tool
def get_student_submission(course_id: str, coursework_id: str, submission_id: str) -> str:
    """Get full details and submitted attachments of a specific student submission.

    Args:
        course_id: The ID of the course.
        coursework_id: The ID of the assignment.
        submission_id: The ID of the student submission.
    """
    try:
        sub = (
            _svc()
            .courses()
            .courseWork()
            .studentSubmissions()
            .get(courseId=course_id, courseWorkId=coursework_id, id=submission_id)
            .execute()
        )
        out = [
            f"📥 **Submission Details** (`{submission_id}`):",
            f"  Student User ID: `{sub.get('userId')}`",
            f"  State: `{sub.get('state')}`",
            f"  Draft Grade: `{sub.get('draftGrade', 'N/A')}`",
            f"  Assigned Grade: `{sub.get('assignedGrade', 'N/A')}`",
            f"  Link: {sub.get('alternateLink', 'N/A')}"
        ]
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ Get submission details failed: {e}"


@tool
def grade_submission(
    course_id: str,
    coursework_id: str,
    submission_id: str,
    draft_grade: Optional[float] = None,
    assigned_grade: Optional[float] = None
) -> str:
    """Assign or update draftGrade (teacher view) and/or assignedGrade (published to student).

    Args:
        course_id: The ID of the course.
        coursework_id: The ID of the assignment.
        submission_id: The ID of the student's submission.
        draft_grade: Optional draft grade score.
        assigned_grade: Optional published assigned grade score.
    """
    try:
        body = {}
        fields = []
        if draft_grade is not None:
            body["draftGrade"] = draft_grade
            fields.append("draftGrade")
        if assigned_grade is not None:
            body["assignedGrade"] = assigned_grade
            fields.append("assignedGrade")

        if not fields:
            return "⚠️ Neither draft_grade nor assigned_grade was provided."

        _svc().courses().courseWork().studentSubmissions().patch(
            courseId=course_id,
            courseWorkId=coursework_id,
            id=submission_id,
            updateMask=",".join(fields),
            body=body,
        ).execute()
        return f"✅ Graded submission `{submission_id}`: draft={draft_grade}, assigned={assigned_grade}"
    except Exception as e:
        return f"⚠️ Grade submission failed: {e}"


@tool
def return_submission(course_id: str, coursework_id: str, submission_id: str) -> str:
    """Return a graded submission to a student, publishing their assigned grade.

    Args:
        course_id: The ID of the course.
        coursework_id: The ID of the assignment.
        submission_id: The ID of the student's submission.
    """
    try:
        _svc().courses().courseWork().studentSubmissions().return_(
            courseId=course_id, courseWorkId=coursework_id, id=submission_id, body={}
        ).execute()
        return f"✅ Returned submission `{submission_id}` to student."
    except Exception as e:
        return f"⚠️ Return submission failed: {e}"


# ── Announcements & Topics ────────────────────────────────────────────────

@tool
def create_announcement(
    course_id: str,
    text: str,
    materials_json: Optional[str] = None,
    state: str = "PUBLISHED"
) -> str:
    """Post an announcement message to a Google Classroom course stream.

    Args:
        course_id: The ID of the course.
        text: Announcement message text.
        materials_json: Optional JSON array of Drive files/links/videos attached to the post.
        state: 'PUBLISHED' or 'DRAFT' (default 'PUBLISHED').
    """
    try:
        body: dict = {"text": text, "state": state}
        if materials_json:
            body["materials"] = json.loads(materials_json)

        announcement = _svc().courses().announcements().create(courseId=course_id, body=body).execute()
        ann_id = announcement["id"]
        return f"✅ Posted announcement (ID: `{ann_id}`) to course `{course_id}`"
    except Exception as e:
        return f"⚠️ Create announcement failed: {e}"


@tool
def list_announcements(course_id: str) -> str:
    """List stream announcements posted in a Google Classroom course.

    Args:
        course_id: The ID of the course.
    """
    try:
        res = _svc().courses().announcements().list(courseId=course_id).execute()
        anns = res.get("announcements", [])
        if not anns:
            return f"No announcements posted in course `{course_id}`."

        out = [f"📢 **Announcements** for Course `{course_id}` ({len(anns)}):"]
        for a in anns:
            out.append(f"- ID: `{a['id']}` | Text: **{a.get('text', '')[:60]}...** | State: `{a.get('state')}`")
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ List announcements failed: {e}"


@tool
def create_course_topic(course_id: str, name: str) -> str:
    """Create a new topic heading in a course to group assignments and materials.

    Args:
        course_id: The ID of the course.
        name: Name of the topic (e.g. 'Module 1: Introduction').
    """
    try:
        topic = _svc().courses().topics().create(courseId=course_id, body={"name": name}).execute()
        topic_id = topic["topicId"]
        return f"✅ Created Topic: **{name}** (Topic ID: `{topic_id}`) in course `{course_id}`"
    except Exception as e:
        return f"⚠️ Create topic failed: {e}"


@tool
def list_course_topics(course_id: str) -> str:
    """List all topics created in a Google Classroom course.

    Args:
        course_id: The ID of the course.
    """
    try:
        res = _svc().courses().topics().list(courseId=course_id).execute()
        topics = res.get("topic", [])
        if not topics:
            return f"No topics created in course `{course_id}`."

        out = [f"🏷️ **Topics** for Course `{course_id}` ({len(topics)}):"]
        for t in topics:
            out.append(f"- **{t['name']}** (Topic ID: `{t['topicId']}`)")
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ List topics failed: {e}"
