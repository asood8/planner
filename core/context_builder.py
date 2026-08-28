from __future__ import annotations

from datetime import datetime, date
from typing import Any


def _format_time(value: datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
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
        formatted.append(f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}")
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


def build_context(day_context: dict[str, Any], week_context: dict[str, Any], max_emails: int = 20) -> str:
    """Convert normalized day/week context into a readable text block for the model."""
    today_label = day_context["date"].strftime("%A, %B %d")
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
    lines.append("TASKS DUE TODAY")
    today_tasks = day_context.get("tasks_due_today", [])
    if today_tasks:
        for task in today_tasks:
            lines.append(f"  {_format_task(task)}")
    else:
        lines.append("  - None")

    lines.append("")
    lines.append("TASKS DUE THIS WEEK")
    week_tasks = week_context.get("tasks_this_week", [])
    if week_tasks:
        for task in week_tasks:
            lines.append(f"  {_format_task(task)}")
    else:
        lines.append("  - None")

    lines.append("")
    lines.append("NO DUE DATE")
    no_due_tasks = week_context.get("tasks_no_due", [])
    if no_due_tasks:
        for task in no_due_tasks:
            lines.append(f"  {_format_task(task)}")
    else:
        lines.append("  - None")

    lines.append("")
    lines.append(f"UNREAD EMAILS ({max_emails})")
    lines.append("  TODAY")
    emails_today = day_context.get("emails_today", [])[:max_emails]
    if emails_today:
        for email in emails_today:
            lines.append(f"    {_format_email(email)}")
    else:
        lines.append("    - None")

    lines.append("  THIS WEEK")
    emails_week = week_context.get("emails_this_week", [])[:max_emails]
    if emails_week:
        for email in emails_week:
            lines.append(f"    {_format_email(email)}")
    else:
        lines.append("    - None")

    return "\n".join(lines)
