"""
services/tracker_formatter.py — Rows for the "AI AGENT" tracker sheet.

Two steps:
  1. tracker_table_rows()  -> starting rows for the editable table in the app
  2. format_tracker_rows() -> tab-separated text built from the (edited) rows

Pasted text has NO header row, so Google Sheets appends the rows directly.
Column order must match the sheet:

    Date | Submitted by | Account | Area | Status | Owner | Due Date | Comment
"""

from datetime import date

from models import Minutes

__all__ = ["tracker_table_rows", "format_tracker_rows"]

# English month names, written out so the result never depends on the computer's locale
_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def _day_month(iso: str | None) -> str:
    """'2026-11-02' -> '2 November' (full month, no year, no leading zero). Empty if missing."""
    if not iso:
        return ""
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso  # not a date: keep the text as it is
    return f"{d.day} {_MONTHS[d.month - 1]}"


def _clean(value) -> str:
    """Make any table cell a single-line string (None/NaN -> empty, tabs/newlines -> spaces)."""
    # A missing cell can arrive as None or as NaN (NaN is the only value not equal to itself)
    if value is None or value != value:
        return ""
    return " ".join(str(value).split())


def tracker_table_rows(minutes: Minutes) -> list[dict]:
    """One starting row per action item, ready to show in st.data_editor."""
    return [
        {
            "Area": item.task,
            "Account": None,               # picked by hand from the dropdown
            "Status": "Open",
            "Owner": item.owner or None,   # None = unassigned
            "Due Date": _day_month(item.deadline),
        }
        for item in minutes.action_items
    ]


def format_tracker_rows(rows: list[dict], submitted_by: str, meeting_date: str | None = None) -> str:
    """Build the tab-separated text from table rows (a list of dicts, one per row)."""
    meeting_day = _day_month(meeting_date)
    lines = []
    for row in rows:
        cells = [
            meeting_day,                  # Date
            _clean(submitted_by),         # Submitted by
            _clean(row.get("Account")),   # Account
            _clean(row.get("Area")),      # Area
            _clean(row.get("Status")),    # Status
            _clean(row.get("Owner")),     # Owner
            _clean(row.get("Due Date")),  # Due Date
            "",                           # Comment
        ]
        # 8 cells joined by tabs = 7 tab characters per line
        lines.append("\t".join(cells))
    return "\n".join(lines)
