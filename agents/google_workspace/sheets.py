"""
google_sheets_tools.py
========================
Full Sheets CRUD for Jessica: create spreadsheets, read/write ranges,
batch-read multiple ranges, append rows, clear ranges, add/delete worksheets,
and format cell ranges (bold, background color hex).
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from langchain_core.tools import tool

from .auth import get_service

_log = logging.getLogger(__name__)


def _svc():
    return get_service("sheets")


def _drive():
    return get_service("drive")


@tool
def create_google_sheet(title: str, sheet_titles_json: Optional[str] = None) -> str:
    """Create a new Google Spreadsheet, optionally with multiple named worksheets/tabs.

    Args:
        title: Title of the workbook.
        sheet_titles_json: Optional JSON array of tab titles, e.g. '["Overview", "Data", "Charts"]'.
    """
    try:
        body: dict = {"properties": {"title": title}}
        if sheet_titles_json:
            sheet_titles = json.loads(sheet_titles_json)
            body["sheets"] = [{"properties": {"title": t}} for t in sheet_titles]

        res = _svc().spreadsheets().create(body=body, fields="spreadsheetId,spreadsheetUrl,sheets").execute()
        sheet_id = res["spreadsheetId"]
        url = res.get("spreadsheetUrl", "")
        return f"✅ Created Google Sheet: **{title}** (ID: `{sheet_id}`)\nLink: {url}"
    except Exception as e:
        return f"⚠️ Sheet creation failed: {e}"


@tool
def read_sheet_range(spreadsheet_id: str, range_name: str = "Sheet1!A1:Z100") -> str:
    """Read cell values from a specified Google Sheet range.

    Args:
        spreadsheet_id: The ID of the Google Spreadsheet.
        range_name: Range in A1 notation (e.g. 'Sheet1!A1:D20').
    """
    try:
        res = _svc().spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
        rows = res.get("values", [])
        if not rows:
            return f"Range `{range_name}` is empty."

        output = [f"📊 Data from `{range_name}` ({len(rows)} rows):"]
        for row in rows:
            output.append(" | ".join([str(cell) for cell in row]))
        return "\n".join(output)
    except Exception as e:
        return f"⚠️ Read sheet failed: {e}"


@tool
def batch_read_sheet_ranges(spreadsheet_id: str, ranges_json: str) -> str:
    """Read multiple cell ranges from a Google Sheet in a single call.

    Args:
        spreadsheet_id: The ID of the Google Spreadsheet.
        ranges_json: JSON array of ranges, e.g. '["Sheet1!A1:B5", "Sheet2!C1:D10"]'.
    """
    try:
        ranges = json.loads(ranges_json)
        res = _svc().spreadsheets().values().batchGet(spreadsheetId=spreadsheet_id, ranges=ranges).execute()
        value_ranges = res.get("valueRanges", [])

        out = [f"📊 **Batch Read Results** ({len(value_ranges)} ranges):"]
        for vr in value_ranges:
            r_name = vr.get("range")
            rows = vr.get("values", [])
            out.append(f"\n--- Range `{r_name}` ({len(rows)} rows) ---")
            for row in rows:
                out.append(" | ".join([str(cell) for cell in row]))
        return "\n".join(out)
    except Exception as e:
        return f"⚠️ Batch read failed: {e}"


@tool
def update_sheet_range(
    spreadsheet_id: str,
    range_name: str,
    values_json: str,
    value_input_option: str = "USER_ENTERED"
) -> str:
    """Write cell values or formulas into a specific Google Sheet range.

    Args:
        spreadsheet_id: The ID of the Google Spreadsheet.
        range_name: Range in A1 notation (e.g. 'Sheet1!A1:B2').
        values_json: JSON string of a 2D matrix of values/formulas, e.g. '[["Header1", "Header2"], ["=SUM(A1:A5)", 42]]'.
        value_input_option: 'USER_ENTERED' (parses formulas/dates) or 'RAW' (literal strings/numbers). Default 'USER_ENTERED'.
    """
    try:
        data = json.loads(values_json)
        if not isinstance(data, list):
            return "⚠️ values_json must parse into a 2D list of lists."

        body = {"values": data}
        res = (
            _svc()
            .spreadsheets()
            .values()
            .update(spreadsheetId=spreadsheet_id, range=range_name, valueInputOption=value_input_option, body=body)
            .execute()
        )
        updated_cells = res.get("updatedCells", 0)
        return f"✅ Updated {updated_cells} cell(s) in range `{range_name}`"
    except Exception as e:
        return f"⚠️ Update sheet failed: {e}"


@tool
def append_sheet_row(
    spreadsheet_id: str,
    range_name: str,
    row_values_json: str,
    value_input_option: str = "USER_ENTERED"
) -> str:
    """Append one or more new rows of values/formulas to a table in Google Sheets.

    Args:
        spreadsheet_id: The ID of the Google Spreadsheet.
        range_name: Target sheet/table range (e.g. 'Sheet1!A1').
        row_values_json: JSON list of values for the new row(s), e.g. '["John Doe", "john@example.com", "=TODAY()"]'.
        value_input_option: 'USER_ENTERED' or 'RAW'. Default 'USER_ENTERED'.
    """
    try:
        row_data = json.loads(row_values_json)
        rows = [row_data] if not isinstance(row_data[0], list) else row_data

        body = {"values": rows}
        res = (
            _svc()
            .spreadsheets()
            .values()
            .append(spreadsheetId=spreadsheet_id, range=range_name, valueInputOption=value_input_option, insertDataOption="INSERT_ROWS", body=body)
            .execute()
        )
        updated_range = res.get("updates", {}).get("updatedRange")
        return f"✅ Appended row(s) to `{updated_range}`"
    except Exception as e:
        return f"⚠️ Append row failed: {e}"


@tool
def clear_sheet_range(spreadsheet_id: str, range_name: str) -> str:
    """Clear all cell values and content in a specified range.

    Args:
        spreadsheet_id: The ID of the Google Spreadsheet.
        range_name: Range in A1 notation to clear (e.g. 'Sheet1!B2:D10').
    """
    try:
        _svc().spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range=range_name, body={}).execute()
        return f"✅ Cleared cell values in range `{range_name}`"
    except Exception as e:
        return f"⚠️ Clear range failed: {e}"


@tool
def add_sheet_tab(spreadsheet_id: str, title: str) -> str:
    """Add a new worksheet tab to an existing Google Spreadsheet.

    Args:
        spreadsheet_id: The ID of the Google Spreadsheet.
        title: Title for the new worksheet tab.
    """
    try:
        requests = [{"addSheet": {"properties": {"title": title}}}]
        res = _svc().spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()
        reply = res.get("replies", [{}])[0].get("addSheet", {}).get("properties", {})
        tab_id = reply.get("sheetId")
        return f"✅ Added tab **{title}** (Sheet ID: `{tab_id}`) to spreadsheet `{spreadsheet_id}`"
    except Exception as e:
        return f"⚠️ Add tab failed: {e}"


@tool
def delete_sheet_tab(spreadsheet_id: str, sheet_id: int) -> str:
    """Delete a worksheet tab from a Google Spreadsheet by sheet ID.

    Args:
        spreadsheet_id: The ID of the Google Spreadsheet.
        sheet_id: The numeric ID of the worksheet tab to delete.
    """
    try:
        requests = [{"deleteSheet": {"sheetId": sheet_id}}]
        _svc().spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()
        return f"✅ Deleted sheet tab ID `{sheet_id}` from spreadsheet `{spreadsheet_id}`"
    except Exception as e:
        return f"⚠️ Delete tab failed: {e}"


@tool
def format_sheet_cells(
    spreadsheet_id: str,
    sheet_id: int,
    start_row: int,
    end_row: int,
    start_col: int,
    end_col: int,
    bold: Optional[bool] = None,
    background_hex: Optional[str] = None
) -> str:
    """Apply bold formatting and/or background hex color to a rectangular range of cells (0-indexed, end exclusive).

    Args:
        spreadsheet_id: The ID of the Google Spreadsheet.
        sheet_id: The numeric ID of the target sheet tab (0 for first sheet).
        start_row: Starting row index (0-indexed).
        end_row: Ending row index (exclusive).
        start_col: Starting column index (0-indexed, 0=A).
        end_col: Ending column index (exclusive).
        bold: Optional boolean to set bold text formatting.
        background_hex: Optional background color in Hex format (e.g. '#4A90E2' or '4A90E2').
    """
    try:
        cell_format: dict = {}
        fields = []
        if bold is not None:
            cell_format.setdefault("textFormat", {})["bold"] = bold
            fields.append("userEnteredFormat.textFormat.bold")
        if background_hex is not None:
            hex_clean = background_hex.lstrip("#")
            r, g, b = (int(hex_clean[i : i + 2], 16) / 255 for i in (0, 2, 4))
            cell_format["backgroundColor"] = {"red": r, "green": g, "blue": b}
            fields.append("userEnteredFormat.backgroundColor")

        if not fields:
            return "⚠️ No formatting properties provided."

        requests = [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": start_row,
                        "endRowIndex": end_row,
                        "startColumnIndex": start_col,
                        "endColumnIndex": end_col,
                    },
                    "cell": {"userEnteredFormat": cell_format},
                    "fields": ",".join(fields),
                }
            }
        ]
        _svc().spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()
        return f"✅ Formatted cells [{start_row}:{end_row}, {start_col}:{end_col}] on sheet `{sheet_id}`"
    except Exception as e:
        return f"⚠️ Format cells failed: {e}"
