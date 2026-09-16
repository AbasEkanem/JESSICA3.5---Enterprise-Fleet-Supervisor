"""
google_slides_tools.py
========================
Full Slides CRUD for Jessica: create presentations, add/duplicate/reorder
slides, global find & replace across a deck (filling templates), insert
images/tables, embed & refresh Google Sheets charts, format slide backgrounds.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from langchain_core.tools import tool

from .auth import get_service

_log = logging.getLogger(__name__)


def _svc():
    return get_service("slides")


def _drive():
    return get_service("drive")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _hex_to_rgb(color_hex: str) -> dict:
    """Convert a Hex color string (e.g. '#0F172A' or '0F172A') to a Slides
    API rgbColor dict with red/green/blue floats in the 0..1 range."""
    hex_clean = str(color_hex).lstrip("#").strip()
    if len(hex_clean) == 3:  # shorthand like #FFF
        hex_clean = "".join(c * 2 for c in hex_clean)
    r, g, b = (int(hex_clean[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return {"red": r, "green": g, "blue": b}


@tool
def create_slides_deck(title: str, slides_json: str) -> str:
    """Build an ENTIRE Google Slides deck (title + content slides with bullets,
    optional background colors, and optional per-slide images) in ONE call.

    This is the PREFERRED tool for any "make me a presentation/deck about X"
    request. It creates the presentation and populates every slide in a single
    server-side operation, so you do NOT need to chain create_presentation →
    get_presentation_details → add_slide → insert_text yourself (that pattern
    fails when the model reuses placeholder IDs instead of real returned IDs).

    Styling & images are applied server-side in the same batch, so a fully
    themed dark-mode deck with diagrams needs no extra tool calls.

    Args:
        title: The presentation title (also used for the first/title slide).
        slides_json: A JSON payload describing the deck. Two shapes are accepted:

            (A) A plain JSON array of slide objects (classic form):
              [
                {"title": "Types of Agent Loops"},
                {"title": "ReAct Loop", "bullets": ["Reason", "Act"]}
              ]

            (B) A JSON object with an optional deck-wide "theme_bg_color" and a
                "slides" array (recommended for styled/dark-mode decks):
              {
                "theme_bg_color": "#0F172A",
                "slides": [
                  {"title": "Executive Summary", "bullets": ["Point 1"]},
                  {
                    "title": "4-Loop Agent Architecture",
                    "bullets": ["Loop 1: LangGraph", "Loop 2: Verification"],
                    "image_url": "https://quickchart.io/graphviz?graph=digraph{A->B}"
                  }
                ]
              }

            Each slide object supports:
              - "title":     the slide heading (string)
              - "bullets":   list of bullet-point strings (optional; omit or
                             empty for a title-only slide)
              - "bg_color":  per-slide Hex background (optional; overrides the
                             deck-wide theme_bg_color for that slide)
              - "image_url": public HTTP(S) image URL (optional). When present,
                             bullets are laid out on the left half and the image
                             on the right half, auto-aligned. Use a dynamic
                             renderer like Mermaid.ink or QuickChart Graphviz to
                             turn a diagram definition into a public PNG URL.

            The first entry becomes the title slide; the rest are content slides.
    """
    try:
        try:
            parsed_payload = json.loads(slides_json)
        except json.JSONDecodeError as e:
            return f"⚠️ create_slides_deck: slides_json is not valid JSON: {e}"

        # Accept either a bare array (classic) or an object with a "slides" key
        # plus an optional deck-wide "theme_bg_color".
        theme_bg_color: Optional[str] = None
        if isinstance(parsed_payload, dict):
            theme_bg_color = parsed_payload.get("theme_bg_color") or parsed_payload.get("bg_color")
            slides = parsed_payload.get("slides")
        else:
            slides = parsed_payload

        if not isinstance(slides, list) or not slides:
            return "⚠️ create_slides_deck: slides_json must be a non-empty JSON array of slide objects (or an object with a non-empty 'slides' array)."

        svc = _svc()

        # 1. Create the empty presentation (ships with one default title slide).
        pres = svc.presentations().create(body={"title": title}).execute()
        pres_id = pres["presentationId"]
        default_slide_ids = [s["objectId"] for s in pres.get("slides", [])]

        # 2. Create the slides FIRST (no placeholderIdMappings). We deliberately
        #    do NOT pre-declare placeholder object IDs: the default template's
        #    "Title slide" layout exposes a CENTERED_TITLE placeholder (not
        #    TITLE), so a hard-coded {type: TITLE} mapping silently produces no
        #    shape and the inserted text lands nowhere → empty slide. Instead we
        #    let the API create each slide with its layout's native
        #    placeholders, then read those real placeholder objectIds back and
        #    insert text into them by matching the placeholder TYPE.
        # (slide_id, title, bullets, bg_color, image_url)
        slide_specs: list[tuple[str, str, list[str], Optional[str], Optional[str]]] = []
        create_requests: list[dict] = []
        for i, slide in enumerate(slides):
            if not isinstance(slide, dict):
                continue
            s_title = str(slide.get("title", "") or "")
            bullets = slide.get("bullets") or []
            if not isinstance(bullets, list):
                bullets = [str(bullets)]

            # Per-slide background overrides the deck-wide theme; fall back to it.
            bg_color = slide.get("bg_color") or theme_bg_color
            image_url = slide.get("image_url") or None

            slide_id = _new_id("slide")
            # First slide (or any slide with no bullets) → title-style layout.
            is_title_only = (i == 0) or not bullets
            layout = "TITLE" if is_title_only else "TITLE_AND_BODY"

            create_requests.append(
                {
                    "createSlide": {
                        "objectId": slide_id,
                        "insertionIndex": i,
                        "slideLayoutReference": {"predefinedLayout": layout},
                    }
                }
            )
            slide_specs.append(
                (slide_id, s_title, [str(b) for b in bullets], bg_color, image_url)
            )

        # Delete the auto-created default slide(s) in the same batch.
        for sid in default_slide_ids:
            create_requests.append({"deleteObject": {"objectId": sid}})

        svc.presentations().batchUpdate(
            presentationId=pres_id, body={"requests": create_requests}
        ).execute()

        # 3. Read the deck back to discover each slide's REAL placeholder IDs.
        full = svc.presentations().get(presentationId=pres_id).execute()
        # Map slide objectId → {placeholder_type: placeholder_object_id}
        placeholder_map: dict[str, dict[str, str]] = {}
        for sl in full.get("slides", []):
            sid = sl["objectId"]
            ph_by_type: dict[str, str] = {}
            for el in sl.get("pageElements", []):
                ph = el.get("shape", {}).get("placeholder")
                if ph and "type" in ph:
                    # Keep the first placeholder of each type.
                    ph_by_type.setdefault(ph["type"], el["objectId"])
            placeholder_map[sid] = ph_by_type

        # 4. Insert text into the real placeholder shapes, matching by type,
        #    and collect background-color + image requests for one final batch.
        _TITLE_TYPES = ("CENTERED_TITLE", "TITLE")
        _BODY_TYPES = ("BODY", "SUBTITLE")
        text_requests: list[dict] = []
        style_requests: list[dict] = []
        n_bg = 0
        n_img = 0
        for slide_id, s_title, bullets, bg_color, image_url in slide_specs:
            ph_by_type = placeholder_map.get(slide_id, {})

            if s_title:
                title_obj = next(
                    (ph_by_type[t] for t in _TITLE_TYPES if t in ph_by_type), None
                )
                if title_obj:
                    text_requests.append(
                        {"insertText": {"objectId": title_obj, "text": s_title, "insertionIndex": 0}}
                    )

            if bullets:
                body_obj = next(
                    (ph_by_type[t] for t in _BODY_TYPES if t in ph_by_type), None
                )
                if body_obj:
                    body_text = "\n".join(bullets)
                    text_requests.append(
                        {"insertText": {"objectId": body_obj, "text": body_text, "insertionIndex": 0}}
                    )
                    # When an image accompanies bullets, nudge the body text box
                    # to the left half so the image can sit on the right half.
                    if image_url:
                        style_requests.append(
                            {
                                "updatePageElementTransform": {
                                    "objectId": body_obj,
                                    "applyMode": "ABSOLUTE",
                                    "transform": {
                                        "scaleX": 1,
                                        "scaleY": 1,
                                        "translateX": 30,
                                        "translateY": 130,
                                        "unit": "PT",
                                    },
                                }
                            }
                        )

            # Per-slide / theme background color.
            if bg_color:
                try:
                    rgb = _hex_to_rgb(bg_color)
                    style_requests.append(
                        {
                            "updatePageProperties": {
                                "objectId": slide_id,
                                "pageProperties": {
                                    "pageBackgroundFill": {
                                        "solidFill": {"color": {"rgbColor": rgb}}
                                    }
                                },
                                "fields": "pageBackgroundFill.solidFill.color",
                            }
                        }
                    )
                    n_bg += 1
                except Exception:
                    pass  # Ignore malformed color, keep building the deck.

            # Contextual image on the right half of the slide.
            if image_url:
                image_id = _new_id("img")
                style_requests.append(
                    {
                        "createImage": {
                            "objectId": image_id,
                            "url": image_url,
                            "elementProperties": {
                                "pageObjectId": slide_id,
                                "size": {
                                    "height": {"magnitude": 250, "unit": "PT"},
                                    "width": {"magnitude": 300, "unit": "PT"},
                                },
                                "transform": {
                                    "scaleX": 1,
                                    "scaleY": 1,
                                    "translateX": 380,
                                    "translateY": 130,
                                    "unit": "PT",
                                },
                            },
                        }
                    }
                )
                n_img += 1

        if text_requests:
            svc.presentations().batchUpdate(
                presentationId=pres_id, body={"requests": text_requests}
            ).execute()

        # Apply backgrounds + images in one final batch (isolated so a single bad
        # image URL never blocks the whole deck's styling).
        if style_requests:
            try:
                svc.presentations().batchUpdate(
                    presentationId=pres_id, body={"requests": style_requests}
                ).execute()
            except Exception as se:
                _log.warning("create_slides_deck styling batch failed: %s", se)

        file_meta = _drive().files().get(fileId=pres_id, fields="webViewLink").execute()
        link = file_meta.get("webViewLink")
        extras = []
        if n_bg:
            extras.append(f"{n_bg} colored background(s)")
        if n_img:
            extras.append(f"{n_img} image(s)")
        extra_note = f" + {', '.join(extras)}" if extras else ""
        return (
            f"✅ Created Google Slides deck **{title}** with {len(slide_specs)} slide(s)"
            f"{extra_note} (ID: `{pres_id}`)\nLink: {link}"
        )

    except Exception as e:
        return f"⚠️ create_slides_deck failed: {e}"




@tool
def add_slide_with_content(presentation_id: str, title: str, bullets_json: str = "") -> str:
    """Add ONE fully-populated slide (title + bullets) to an EXISTING deck in a single call.

    Use this to grow a deck you already created — it is the SAFE way to add a
    content slide. It creates the slide, then reads back the slide's REAL
    placeholder object IDs and inserts the text into them itself, so you never
    have to guess or reuse placeholder IDs (the #1 cause of empty slides).

    Do NOT chain add_slide → insert_text_into_slide yourself: that pattern makes
    you pass a made-up shape_object_id, the text lands nowhere, and you get a
    blank slide.

    Args:
        presentation_id: The REAL ID of an existing presentation (from a tool result).
        title: The slide heading text.
        bullets_json: Optional JSON array of bullet strings, e.g. '["point one","point two"]'.
                      Omit or pass "" for a title-only slide.
    """
    try:
        bullets: list[str] = []
        if bullets_json and bullets_json.strip():
            try:
                parsed = json.loads(bullets_json)
                bullets = [str(b) for b in parsed] if isinstance(parsed, list) else [str(parsed)]
            except json.JSONDecodeError:
                # Tolerate a plain newline/comma separated string.
                bullets = [b.strip() for b in bullets_json.replace("\n", ",").split(",") if b.strip()]

        svc = _svc()
        slide_id = _new_id("slide")
        layout = "TITLE_AND_BODY" if bullets else "TITLE"
        svc.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": [{"createSlide": {"objectId": slide_id, "slideLayoutReference": {"predefinedLayout": layout}}}]},
        ).execute()

        # Read back the REAL placeholder IDs for the slide we just created.
        full = svc.presentations().get(presentationId=presentation_id).execute()
        ph_by_type: dict[str, str] = {}
        for sl in full.get("slides", []):
            if sl["objectId"] != slide_id:
                continue
            for el in sl.get("pageElements", []):
                ph = el.get("shape", {}).get("placeholder")
                if ph and "type" in ph:
                    ph_by_type.setdefault(ph["type"], el["objectId"])
            break

        _TITLE_TYPES = ("CENTERED_TITLE", "TITLE")
        _BODY_TYPES = ("BODY", "SUBTITLE")
        text_requests: list[dict] = []
        if title:
            title_obj = next((ph_by_type[t] for t in _TITLE_TYPES if t in ph_by_type), None)
            if title_obj:
                text_requests.append({"insertText": {"objectId": title_obj, "text": title, "insertionIndex": 0}})
        if bullets:
            body_obj = next((ph_by_type[t] for t in _BODY_TYPES if t in ph_by_type), None)
            if body_obj:
                text_requests.append({"insertText": {"objectId": body_obj, "text": "\n".join(bullets), "insertionIndex": 0}})

        if not text_requests:
            return (
                f"⚠️ add_slide_with_content: slide `{slide_id}` was created but no title/body "
                f"placeholder was found on layout `{layout}` (found: {sorted(ph_by_type)}). "
                f"Nothing was inserted."
            )

        svc.presentations().batchUpdate(presentationId=presentation_id, body={"requests": text_requests}).execute()
        return (
            f"✅ Added populated slide `{slide_id}` to `{presentation_id}` "
            f"(title + {len(bullets)} bullet(s))."
        )
    except Exception as e:
        return f"⚠️ add_slide_with_content failed: {e}"


@tool
def create_presentation(title: str) -> str:

    """Create a new Google Slides presentation deck.

    Args:
        title: Title of the presentation.
    """
    try:
        pres = _svc().presentations().create(body={"title": title}).execute()
        pres_id = pres["presentationId"]
        file_meta = _drive().files().get(fileId=pres_id, fields="webViewLink").execute()
        return f"✅ Created Google Slides Presentation: **{title}** (ID: `{pres_id}`)\nLink: {file_meta.get('webViewLink')}"
    except Exception as e:
        return f"⚠️ Presentation creation failed: {e}"


@tool
def get_presentation_details(presentation_id: str) -> str:
    """Get full metadata and structure of a presentation deck (all slides, elements, text, speaker notes).

    Args:
        presentation_id: The ID of the presentation.
    """
    try:
        pres = _svc().presentations().get(presentationId=presentation_id).execute()
        title = pres.get("title", "Untitled Presentation")
        slides = pres.get("slides", [])

        out = [f"🖥️ **{title}** (`{presentation_id}`) - Total Slides: {len(slides)}:"]
        for idx, slide in enumerate(slides, start=1):
            slide_id = slide["objectId"]
            elements_count = len(slide.get("pageElements", []))
            out.append(f"- Slide #{idx} (ID: `{slide_id}` | Elements: {elements_count})")
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ Get presentation failed: {e}"


@tool
def add_slide(presentation_id: str, layout: str = "TITLE_AND_BODY", insertion_index: Optional[int] = None) -> str:
    """Add a new slide to a presentation deck.

    Args:
        presentation_id: The ID of the presentation.
        layout: Predefined layout type ('TITLE', 'TITLE_AND_BODY', 'TITLE_AND_TWO_COLUMNS', 'SECTION_HEADER', 'MAIN_POINT', 'BLANK'). Default 'TITLE_AND_BODY'.
        insertion_index: Optional 0-indexed slide position to insert at.
    """
    try:
        slide_id = _new_id("slide")
        create_slide: dict = {
            "objectId": slide_id,
            "slideLayoutReference": {"predefinedLayout": layout},
        }
        if insertion_index is not None:
            create_slide["insertionIndex"] = insertion_index

        requests = [{"createSlide": create_slide}]
        res = _svc().presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()
        created_id = res.get("replies", [{}])[0].get("createSlide", {}).get("objectId", slide_id)
        return f"✅ Added new slide (`{layout}`) with ID: `{created_id}` to presentation `{presentation_id}`"
    except Exception as e:
        return f"⚠️ Add slide failed: {e}"


@tool
def duplicate_slide(presentation_id: str, slide_object_id: str) -> str:
    """Duplicate an existing slide (handy for stamping out multiple slides from a template).

    Args:
        presentation_id: The ID of the presentation.
        slide_object_id: Object ID of the slide to duplicate.
    """
    try:
        requests = [{"duplicateObject": {"objectId": slide_object_id}}]
        res = _svc().presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()
        dup_id = res.get("replies", [{}])[0].get("duplicateObject", {}).get("objectId", "N/A")
        return f"✅ Duplicated slide `{slide_object_id}` -> New Slide ID: `{dup_id}`"
    except Exception as e:
        return f"⚠️ Duplicate slide failed: {e}"


@tool
def delete_slide(presentation_id: str, slide_object_id: str) -> str:
    """Delete a specific slide or element from a presentation deck.

    Args:
        presentation_id: The ID of the presentation.
        slide_object_id: The object ID of the slide or shape to delete.
    """
    try:
        requests = [{"deleteObject": {"objectId": slide_object_id}}]
        _svc().presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()
        return f"✅ Deleted slide/object `{slide_object_id}` from presentation `{presentation_id}`"
    except Exception as e:
        return f"⚠️ Delete slide failed: {e}"


@tool
def reorder_slides(presentation_id: str, slide_object_ids_json: str, insertion_index: int) -> str:
    """Reorder a set of slides within a presentation deck.

    Args:
        presentation_id: The ID of the presentation.
        slide_object_ids_json: JSON list of slide object IDs to move, e.g. '["slide_1", "slide_2"]'.
        insertion_index: Target 0-indexed insertion position.
    """
    import json
    try:
        slide_ids = json.loads(slide_object_ids_json)
        requests = [
            {
                "updateSlidesPosition": {
                    "slideObjectIds": slide_ids,
                    "insertionIndex": insertion_index,
                }
            }
        ]
        _svc().presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()
        return f"✅ Reordered {len(slide_ids)} slide(s) to position index {insertion_index}"
    except Exception as e:
        return f"⚠️ Reorder slides failed: {e}"


@tool
def replace_all_text_in_slides(presentation_id: str, target_text: str, replacement_text: str, match_case: bool = True) -> str:
    """Global find & replace across all slides in a deck (great for filling template placeholders like {{CLIENT}}).

    Args:
        presentation_id: The ID of the presentation.
        target_text: Target search string (e.g. '{{PROJECT_NAME}}').
        replacement_text: Replacement string.
        match_case: Case sensitivity (default True).
    """
    try:
        requests = [
            {
                "replaceAllText": {
                    "containsText": {"text": target_text, "matchCase": match_case},
                    "replaceText": replacement_text,
                }
            }
        ]
        res = _svc().presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()
        occurrences = res.get("replies", [{}])[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
        return f"✅ Replaced {occurrences} occurrence(s) of '{target_text}' with '{replacement_text}' in deck `{presentation_id}`"
    except Exception as e:
        return f"⚠️ Replace text failed: {e}"


@tool
def insert_text_into_slide(presentation_id: str, shape_object_id: str, text: str, insertion_index: int = 0) -> str:
    """Insert text into a shape, placeholder, or text box on a slide.

    Args:
        presentation_id: The ID of the presentation.
        shape_object_id: The ID of the text box/shape on the slide.
        text: The text string to insert.
        insertion_index: Character insertion index (default 0).
    """
    try:
        requests = [{"insertText": {"objectId": shape_object_id, "text": text, "insertionIndex": insertion_index}}]
        _svc().presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()
        return f"✅ Inserted text into shape `{shape_object_id}` on presentation `{presentation_id}`"
    except Exception as e:
        return f"⚠️ Insert text failed: {e}"


@tool
def insert_image_onto_slide(
    presentation_id: str,
    slide_object_id: str,
    image_url: str,
    x_pt: float = 100,
    y_pt: float = 100,
    width_pt: float = 300,
    height_pt: float = 200
) -> str:
    """Insert an image (from a public URL or Drive image link) onto a slide at a given position and size in points (PT).

    Args:
        presentation_id: The ID of the presentation.
        slide_object_id: Target slide object ID.
        image_url: Public URL to the image asset.
        x_pt: Horizontal X coordinate position in points (default 100).
        y_pt: Vertical Y coordinate position in points (default 100).
        width_pt: Image width in points (default 300).
        height_pt: Image height in points (default 200).
    """
    try:
        image_id = _new_id("img")
        requests = [
            {
                "createImage": {
                    "objectId": image_id,
                    "url": image_url,
                    "elementProperties": {
                        "pageObjectId": slide_object_id,
                        "size": {
                            "height": {"magnitude": height_pt, "unit": "PT"},
                            "width": {"magnitude": width_pt, "unit": "PT"},
                        },
                        "transform": {
                            "scaleX": 1,
                            "scaleY": 1,
                            "translateX": x_pt,
                            "translateY": y_pt,
                            "unit": "PT",
                        },
                    },
                }
            }
        ]
        _svc().presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()
        return f"✅ Inserted image `{image_id}` onto slide `{slide_object_id}`"
    except Exception as e:
        return f"⚠️ Insert image failed: {e}"


@tool
def create_slide_table(presentation_id: str, slide_object_id: str, rows: int, columns: int) -> str:
    """Create a table with specified rows and columns on a slide.

    Args:
        presentation_id: The ID of the presentation.
        slide_object_id: Target slide object ID.
        rows: Number of rows.
        columns: Number of columns.
    """
    try:
        table_id = _new_id("table")
        requests = [
            {
                "createTable": {
                    "objectId": table_id,
                    "elementProperties": {"pageObjectId": slide_object_id},
                    "rows": rows,
                    "columns": columns,
                }
            }
        ]
        _svc().presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()
        return f"✅ Created {rows}x{columns} table (ID: `{table_id}`) on slide `{slide_object_id}`"
    except Exception as e:
        return f"⚠️ Create table failed: {e}"


@tool
def embed_sheets_chart_on_slide(
    presentation_id: str,
    slide_object_id: str,
    spreadsheet_id: str,
    chart_id: int,
    x_pt: float = 100,
    y_pt: float = 100,
    width_pt: float = 400,
    height_pt: float = 250
) -> str:
    """Embed a chart from a Google Sheet directly onto a slide as a linked visual element.

    Args:
        presentation_id: Target presentation ID.
        slide_object_id: Target slide object ID.
        spreadsheet_id: Source Google Spreadsheet ID.
        chart_id: Numeric chart ID within the Google Sheet.
        x_pt: Horizontal X coordinate position in points.
        y_pt: Vertical Y coordinate position in points.
        width_pt: Chart width in points.
        height_pt: Chart height in points.
    """
    try:
        object_id = _new_id("chart")
        requests = [
            {
                "createSheetsChart": {
                    "objectId": object_id,
                    "spreadsheetId": spreadsheet_id,
                    "chartId": chart_id,
                    "linkingMode": "LINKED",
                    "elementProperties": {
                        "pageObjectId": slide_object_id,
                        "size": {
                            "height": {"magnitude": height_pt, "unit": "PT"},
                            "width": {"magnitude": width_pt, "unit": "PT"},
                        },
                        "transform": {
                            "scaleX": 1,
                            "scaleY": 1,
                            "translateX": x_pt,
                            "translateY": y_pt,
                            "unit": "PT",
                        },
                    },
                }
            }
        ]
        _svc().presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()
        return f"✅ Embedded Sheets chart (Chart ID: `{chart_id}`) as element `{object_id}` on slide `{slide_object_id}`"
    except Exception as e:
        return f"⚠️ Embed Sheets chart failed: {e}"


@tool
def refresh_slide_sheets_chart(presentation_id: str, chart_object_id: str) -> str:
    """Refresh an embedded Google Sheets chart element on a slide to sync with latest sheet data.

    Args:
        presentation_id: Target presentation ID.
        chart_object_id: Object ID of the linked chart element on the slide.
    """
    try:
        requests = [{"refreshSheetsChart": {"objectId": chart_object_id}}]
        _svc().presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()
        return f"✅ Refreshed linked Sheets chart element `{chart_object_id}` in presentation `{presentation_id}`"
    except Exception as e:
        return f"⚠️ Refresh Sheets chart failed: {e}"


@tool
def update_slide_background_color(presentation_id: str, slide_object_id: str, color_hex: str) -> str:
    """Change the solid background color of a slide using a Hex color code (e.g. '#1E1E1E' or '4A90E2').

    Args:
        presentation_id: Target presentation ID.
        slide_object_id: Target slide object ID.
        color_hex: Background color in Hex format (e.g. '#1E1E1E').
    """
    try:
        hex_clean = color_hex.lstrip("#")
        r, g, b = (int(hex_clean[i : i + 2], 16) / 255 for i in (0, 2, 4))
        requests = [
            {
                "updatePageProperties": {
                    "objectId": slide_object_id,
                    "pageProperties": {
                        "pageBackgroundFill": {"solidFill": {"color": {"rgbColor": {"red": r, "green": g, "blue": b}}}}
                    },
                    "fields": "pageBackgroundFill.solidFill.color",
                }
            }
        ]
        _svc().presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()
        return f"✅ Set slide `{slide_object_id}` background color to Hex `{color_hex}`"
    except Exception as e:
        return f"⚠️ Update slide background failed: {e}"
