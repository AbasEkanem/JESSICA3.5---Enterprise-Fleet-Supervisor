"""
google_forms_tools.py
========================
Full Forms CRUD for Jessica: create forms, publish forms, add text/choice questions,
add section headers, delete items, list responses, and fetch specific single responses.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from langchain_core.tools import tool

from .auth import get_service

_log = logging.getLogger(__name__)


def _svc():
    return get_service("forms")


def _drive():
    return get_service("drive")


@tool
def create_google_form(title: str, document_title: Optional[str] = None) -> str:
    """Create a new Google Form. Note: Forms default to UNPUBLISHED state; call publish_google_form() after adding questions so it accepts responses.

    Args:
        title: Title displayed on the form.
        document_title: Optional document title in Google Drive.
    """
    try:
        body = {
            "info": {
                "title": title,
                "documentTitle": document_title or title
            }
        }
        form = _svc().forms().create(body=body).execute()
        form_id = form["formId"]
        responder_uri = form.get("responderUri", "N/A")

        # Set public Drive permission so the responderUri is publicly viewable
        try:
            _drive().permissions().create(
                fileId=form_id,
                body={"type": "anyone", "role": "reader"},
                fields="id"
            ).execute()
        except Exception:
            pass

        return f"✅ Created Google Form: **{title}** (ID: `{form_id}`)\nPublic Responder Link: {responder_uri}\n⚠️ Remember to publish the form once questions are added!"
    except Exception as e:
        return f"⚠️ Form creation failed: {e}"


@tool
def get_google_form_details(form_id: str) -> str:
    """Read the questions, items, and settings of a Google Form.

    Args:
        form_id: The ID of the Google Form.
    """
    try:
        form = _svc().forms().get(formId=form_id).execute()
        title = form.get("info", {}).get("title", "Untitled Form")
        items = form.get("items", [])

        out = [f"📝 **{title}** (`{form_id}`) - Total Items: {len(items)}:"]
        for idx, item in enumerate(items, start=1):
            item_title = item.get("title", "Untitled Question / Item")
            item_id = item.get("itemId")
            out.append(f"- #{idx} **{item_title}** (ID: `{item_id}`)")
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ Get form details failed: {e}"


@tool
def publish_google_form(form_id: str) -> str:
    """Publish a Google Form so it starts accepting user responses and is accessible to anyone with the link.

    Args:
        form_id: The ID of the Google Form.
    """
    try:
        requests = [
            {
                "updateSettings": {
                    "settings": {"quizSettings": {"isQuiz": False}},
                    "updateMask": "quizSettings.isQuiz",
                }
            }
        ]
        _svc().forms().batchUpdate(formId=form_id, body={"requests": requests}).execute()

        # Grant 'anyone' reader permission via Drive API so responders aren't blocked by 'Form closed' / 'Permission required'
        try:
            _drive().permissions().create(
                fileId=form_id,
                body={"type": "anyone", "role": "reader"},
                fields="id"
            ).execute()
        except Exception as pe:
            _log.warning(f"Could not set public Drive permission for form {form_id}: {pe}")

        return f"✅ Form `{form_id}` is now published and publicly accessible to accept responses!"
    except Exception as e:
        return f"⚠️ Publish form failed: {e}"


@tool
def add_text_question_to_form(
    form_id: str,
    title: str,
    required: bool = False,
    paragraph: bool = False,
    index: int = 0
) -> str:
    """Add a short answer text or long paragraph question to a Google Form.

    Args:
        form_id: The ID of the Google Form.
        title: The question prompt/title text.
        required: Whether the question is required (default False).
        paragraph: True for multi-line paragraph text, False for short answer text (default False).
        index: 0-indexed position to place the item (default 0).
    """
    try:
        item = {
            "item": {
                "title": title,
                "questionItem": {"question": {"required": required, "textQuestion": {"paragraph": paragraph}}},
            },
            "location": {"index": index},
        }
        requests = [{"createItem": item}]
        _svc().forms().batchUpdate(formId=form_id, body={"requests": requests}).execute()
        q_type = "Paragraph" if paragraph else "Short Text"
        return f"✅ Added {q_type} question '{title}' at position {index} in form `{form_id}`"
    except Exception as e:
        return f"⚠️ Add text question failed: {e}"


@tool
def add_choice_question_to_form(
    form_id: str,
    title: str,
    options_json: str,
    choice_type: str = "RADIO",
    required: bool = False,
    index: int = 0
) -> str:
    """Add a multiple-choice question (RADIO, CHECKBOX, or DROP_DOWN) to a Google Form.

    Args:
        form_id: The ID of the Google Form.
        title: The question prompt/title text.
        options_json: JSON string of choice options, e.g. '["Option A", "Option B", "Option C"]'.
        choice_type: One of 'RADIO', 'CHECKBOX', or 'DROP_DOWN' (default 'RADIO').
        required: Whether the question is required (default False).
        index: 0-indexed position to place the item (default 0).
    """
    try:
        options = json.loads(options_json) if isinstance(options_json, str) else options_json
        item = {
            "item": {
                "title": title,
                "questionItem": {
                    "question": {
                        "required": required,
                        "choiceQuestion": {
                            "type": choice_type.upper(),
                            "options": [{"value": str(opt)} for opt in options],
                        },
                    }
                },
            },
            "location": {"index": index},
        }
        requests = [{"createItem": item}]
        _svc().forms().batchUpdate(formId=form_id, body={"requests": requests}).execute()
        return f"✅ Added {choice_type} question '{title}' with {len(options)} options to form `{form_id}`"
    except Exception as e:
        return f"⚠️ Add choice question failed: {e}"


@tool
def add_section_header_to_form(form_id: str, title: str, description: Optional[str] = None, index: int = 0) -> str:
    """Add a section page break header to organize a Google Form into multi-page sections.

    Args:
        form_id: The ID of the Google Form.
        title: Section header title text.
        description: Optional section description text.
        index: 0-indexed position to insert the section break.
    """
    try:
        item = {
            "item": {"title": title, "description": description, "pageBreakItem": {}},
            "location": {"index": index},
        }
        requests = [{"createItem": item}]
        _svc().forms().batchUpdate(formId=form_id, body={"requests": requests}).execute()
        return f"✅ Added section header '**{title}**' at position {index} in form `{form_id}`"
    except Exception as e:
        return f"⚠️ Add section header failed: {e}"


@tool
def delete_form_item(form_id: str, index: int) -> str:
    """Delete an item or question from a Google Form by location index.

    Args:
        form_id: The ID of the Google Form.
        index: 0-indexed position of the item to delete.
    """
    try:
        requests = [{"deleteItem": {"location": {"index": index}}}]
        _svc().forms().batchUpdate(formId=form_id, body={"requests": requests}).execute()
        return f"✅ Deleted form item at index position {index} in form `{form_id}`"
    except Exception as e:
        return f"⚠️ Delete form item failed: {e}"


@tool
def get_form_responses(form_id: str) -> str:
    """Retrieve submitted responses for a Google Form.

    Args:
        form_id: The ID of the Google Form.
    """
    try:
        res = _svc().forms().responses().list(formId=form_id).execute()
        responses = res.get("responses", [])
        if not responses:
            return f"No responses submitted yet for form `{form_id}`."

        out = [f"📊 **Form Responses** for `{form_id}` (Total: {len(responses)}):"]
        for idx, resp in enumerate(responses, start=1):
            sub_id = resp.get("responseId")
            sub_time = resp.get("createTime")
            answers = resp.get("answers", {})
            out.append(f"\n--- Submission #{idx} (`{sub_id}` at {sub_time}) ---")
            for q_id, ans in answers.items():
                text_answers = [a.get("value", "") for a in ans.get("textAnswers", {}).get("answers", [])]
                out.append(f"  Q({q_id}): {', '.join(text_answers)}")
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ Get responses failed: {e}"


@tool
def get_single_form_response(form_id: str, response_id: str) -> str:
    """Retrieve a specific single submitted response from a Google Form by response ID.

    Args:
        form_id: The ID of the Google Form.
        response_id: The ID of the specific response submission.
    """
    try:
        resp = _svc().forms().responses().get(formId=form_id, responseId=response_id).execute()
        sub_time = resp.get("createTime")
        answers = resp.get("answers", {})

        out = [f"📥 **Single Submission** (`{response_id}` submitted at {sub_time}):"]
        for q_id, ans in answers.items():
            text_answers = [a.get("value", "") for a in ans.get("textAnswers", {}).get("answers", [])]
            out.append(f"  Question `{q_id}`: {', '.join(text_answers)}")
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ Get single response failed: {e}"
