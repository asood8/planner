from __future__ import annotations

from datetime import datetime, date
from typing import Any


def _format_time(value: datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        # Show local wall-clock time; astimezone() treats naive values as already local.
        return value.astimezone().strftime("%H:%M")
    return str(value)


def _format_event(event: dict[str, Any]) -> str:
    start = event.get("start")
    end = event.get("end")
    if isinstance(start, datetime) and isinstance(end, datetime):
        return f"[{_format_time(start)}–{_format_time(end)}] {event.get('title', 'Untitled event')}"
    if isinstance(start, date) and not isinstance(start, datetime):
        return f"[All day] {event.get('title', 'Untitled event')}"
    return f"{event.get('title', 'Untitled event')}"


def _format_free_blocks(free_blocks: list[tuple[datetime, datetime]]) -> str:
    if not free_blocks:
        return "Free blocks: none"
    formatted = []
    for start, end in free_blocks:
        formatted.append(f"{_format_time(start)}–{_format_time(end)}")
    return "Free blocks: " + ", ".join(formatted)


def _format_task(task: dict[str, Any]) -> str:
    title = task.get("title", "Untitled task")
    due = task.get("due")
    if isinstance(due, datetime):
        return f"- [{task.get('list', 'Tasks')}] {title} (due {due.strftime('%a %b %d')})"
    return f"- [{task.get('list', 'Tasks')}] {title}"


def _format_email(email: dict[str, Any]) -> str:
    sender = email.get("sender", "") or "Unknown sender"
    subject = email.get("subject", "") or "(no subject)"
    snippet = email.get("snippet", "") or ""
    snippet_text = snippet.replace("\n", " ").strip()
    if snippet_text:
        return f'- From: {sender} | "{subject}" | "{snippet_text}"'
    return f'- From: {sender} | "{subject}"'


def _append_task_section(lines: list[str], heading: str, tasks: list[dict[str, Any]]) -> None:
    lines.append("")
    lines.append(heading)
    if tasks:
        for task in tasks:
            lines.append(f"  {_format_task(task)}")
    else:
        lines.append("  - None")


def build_context(day_context: dict[str, Any], week_context: dict[str, Any], max_emails: int = 20) -> str:
    """Convert normalized day/week context into a readable text block for the model."""
    today = day_context["date"]
    today_label = today.strftime("%A, %B %d")
    lines = [f"TODAY — {today_label}"]

    for event in day_context.get("events", []):
        lines.append(f"  {_format_event(event)}")

    if day_context.get("free_blocks"):
        lines.append(f"  {_format_free_blocks(day_context['free_blocks'])}")
    else:
        lines.append("  Free blocks: none")

    if day_context.get("conflicts"):
        lines.append("  Conflicts:")
        for event_a, event_b in day_context["conflicts"]:
            lines.append(f"    - {event_a.get('title', 'Untitled')} overlaps {event_b.get('title', 'Untitled')}")

    lines.append("")
    lines.append("REST OF THE WEEK")
    upcoming_days = sorted(day for day in week_context.get("events_by_day", {}) if day > today)
    if upcoming_days:
        for day in upcoming_days:
            lines.append(f"  {day.strftime('%a %b %d')}")
            for event in week_context["events_by_day"][day]:
                lines.append(f"    {_format_event(event)}")
    else:
        lines.append("  - No events")

    _append_task_section(lines, "OVERDUE TASKS", day_context.get("tasks_overdue", []))
    _append_task_section(lines, "TASKS DUE TODAY", day_context.get("tasks_due_today", []))
    _append_task_section(lines, "TASKS DUE LATER THIS WEEK", week_context.get("tasks_this_week", []))
    _append_task_section(lines, "TASKS DUE AFTER THIS WEEK", week_context.get("tasks_later", []))
    _append_task_section(lines, "NO DUE DATE", week_context.get("tasks_no_due", []))

    emails_today = day_context.get("emails_today", [])[:max_emails]
    emails_week = week_context.get("emails_this_week", [])[:max_emails]

    lines.append("")
    lines.append(f"UNREAD EMAILS ({len(emails_today) + len(emails_week)})")
    lines.append("  TODAY")
    if emails_today:
        for email in emails_today:
            lines.append(f"    {_format_email(email)}")
    else:
        lines.append("    - None")

    lines.append("  THIS WEEK")
    if emails_week:
        for email in emails_week:
            lines.append(f"    {_format_email(email)}")
    else:
        lines.append("    - None")

    return "\n".join(lines)
