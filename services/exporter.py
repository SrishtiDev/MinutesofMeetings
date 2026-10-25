"""
services/exporter.py — Turn a Minutes object into a Markdown document.
"""

from models import Minutes

# Human-friendly names for the language codes stored in Minutes
_LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "mixed": "Hinglish (mixed)"}


def _cell(text: str) -> str:
    """Make text safe for a Markdown table cell (no pipes or line breaks)."""
    return text.replace("|", "\\|").replace("\n", " ")


def to_markdown(
    minutes: Minutes,
    transcript: str | None = None,
    meeting_date: str | None = None,
) -> str:
    """
    Build clean Markdown minutes.

    transcript:   if given, the original transcript is added at the end.
    meeting_date: optional "YYYY-MM-DD" shown under the title
                  (Minutes itself does not store the date).
    """
    lines = [f"# {minutes.title}", ""]

    if meeting_date:
        lines.append(f"**Date:** {meeting_date}  ")
    language = _LANGUAGE_NAMES.get(minutes.detected_language, minutes.detected_language)
    lines += [f"**Language:** {language}", ""]

    lines += ["## Summary", "", minutes.summary, ""]

    lines += ["## Key points", ""]
    lines += [f"- {p}" for p in minutes.key_points] or ["_None_"]
    lines.append("")

    lines += ["## Decisions", ""]
    lines += [f"- {d}" for d in minutes.decisions] or ["_None_"]
    lines.append("")

    lines += ["## Action items", ""]
    if minutes.action_items:
        lines += ["| Task | Owner | Deadline |", "| --- | --- | --- |"]
        for item in minutes.action_items:
            owner = item.owner or "Unassigned"
            deadline = item.deadline or "Not specified"
            lines.append(f"| {_cell(item.task)} | {_cell(owner)} | {_cell(deadline)} |")
    else:
        lines.append("_None_")
    lines.append("")

    if transcript:
        lines += ["## Original transcript", "", transcript.strip(), ""]

    return "\n".join(lines)
