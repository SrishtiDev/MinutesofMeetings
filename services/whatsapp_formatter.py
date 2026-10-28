"""
services/whatsapp_formatter.py — Turn a Minutes object into a WhatsApp-ready message.

WhatsApp uses its own formatting: *bold*, _italic_ and "•" bullets.
We never use Markdown here (no **bold**, no #, no ---, no tables).
"""

from datetime import date

from models import Minutes


def _short_date(iso: str | None, with_year: bool) -> str:
    """'2026-10-28' -> '28 Oct 2026' (or '28 Oct'). Unreadable text is returned as-is."""
    if not iso:
        return ""
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    # d.day is a plain number, so there is no leading zero
    return f"{d.day} {d:%b} {d.year}" if with_year else f"{d.day} {d:%b}"


def format_whatsapp(minutes: Minutes, meeting_date: str | None = None) -> str:
    """Build the WhatsApp message. meeting_date is an ISO string like '2026-10-28'."""
    lines = [f"*MOM: {minutes.title}*"]
    if meeting_date:
        lines.append(f"📅 {_short_date(meeting_date, with_year=True)}")

    lines += ["", "*Summary*", minutes.summary]

    if minutes.key_points:
        lines += ["", "*Key Points*"]
        lines += [f"• {point}" for point in minutes.key_points]

    # Skip the whole section when there are no decisions
    if minutes.decisions:
        lines += ["", "*Decisions*"]
        lines += [f"• {decision}" for decision in minutes.decisions]

    if minutes.action_items:
        lines += ["", "*Action Items*"]
        for number, item in enumerate(minutes.action_items, start=1):
            if not item.owner:
                # Never drop a task just because nobody owns it yet
                lines.append(f"{number}. {item.task} — ⚠️ _Unassigned_")
                continue
            due = _short_date(item.deadline, with_year=False) if item.deadline else ""
            due_text = f"due {due}" if due else "no deadline"
            lines.append(f"{number}. {item.task} — *{item.owner}* ({due_text})")

    return "\n".join(lines)
