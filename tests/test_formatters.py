"""
Quick check of the WhatsApp and tracker formatters.

Run from the repo root:  python -m tests.test_formatters
(also works with pytest)
"""

from models import ActionItem, Minutes
from services.tracker_formatter import format_tracker_rows, tracker_table_rows
from services.whatsapp_formatter import format_whatsapp

MEETING_DATE = "2026-10-28"

# One task with owner + deadline, one unassigned task with no deadline, no decisions
SAMPLE = Minutes(
    title="Weekly sync",
    detected_language="en",
    summary="The team reviewed the launch plan.",
    key_points=["Launch is on track", "Docs are behind"],
    decisions=[],
    action_items=[
        ActionItem(task="Send the invoice", owner="Priya", deadline="2026-10-30"),
        ActionItem(task="Update the README", owner=None, deadline=None),
    ],
)


def test_formatters() -> None:
    whatsapp = format_whatsapp(SAMPLE, MEETING_DATE)
    rows = tracker_table_rows(SAMPLE)
    tracker = format_tracker_rows(rows, "Srishti", MEETING_DATE)

    print(whatsapp)
    print("\n--- tracker (tabs shown as →) ---")
    print(tracker.replace("\t", "→"))

    # Tracker: exactly 7 tabs per line, one line per action item
    lines = tracker.split("\n")
    assert len(lines) == 2
    for line in lines:
        assert line.count("\t") == 7, f"expected 7 tabs, got {line.count(chr(9))}: {line!r}"
    assert lines[0] == "28 October\tSrishti\t\tSend the invoice\tOpen\tPriya\t30 October\t"
    assert lines[1] == "28 October\tSrishti\t\tUpdate the README\tOpen\t\t\t"

    # Editing a row's Account/Status changes the text
    rows[0]["Account"] = "Teacher"
    rows[0]["Status"] = "In progress"
    edited = format_tracker_rows(rows, "Srishti", MEETING_DATE).split("\n")[0]
    assert edited == "28 October\tSrishti\tTeacher\tSend the invoice\tIn progress\tPriya\t30 October\t"
    assert edited.count("\t") == 7

    # WhatsApp: no Markdown, decisions section skipped, unassigned task kept
    assert "**" not in whatsapp
    assert "#" not in whatsapp
    assert "*Decisions*" not in whatsapp
    assert "📅 28 Oct 2026" in whatsapp
    assert "1. Send the invoice — *Priya* (due 30 Oct)" in whatsapp
    assert "2. Update the README — ⚠️ _Unassigned_" in whatsapp

    print("\nAll checks passed.")


if __name__ == "__main__":
    test_formatters()
