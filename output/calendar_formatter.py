from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any


def _coerce_datetime(value: Any) -> datetime | None:
    """Aware UTC datetime. Naive datetimes and plain dates are treated as local time."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, datetime):
        # astimezone() on a naive datetime interprets it as local time.
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min).astimezone(timezone.utc)
    return None


def _event_day(value: Any) -> date | None:
    """Local calendar day an event starts on (unlike _coerce_date, which keeps a task's UTC date)."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    parsed = _coerce_datetime(value)
    return parsed.astimezone().date() if parsed else None


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.date()
        except ValueError:
            return None
    return None


def _format_datetime(value: Any) -> str | None:
    parsed = _coerce_datetime(value)
    if parsed is None:
        return None
    return parsed.astimezone().strftime("%Y-%m-%dT%H:%M:%S")


def _format_date(value: Any) -> str | None:
    parsed = _coerce_date(value)
    if parsed is None:
        return None
    return parsed.strftime("%Y-%m-%d")


def _parse_ai_plan_events(ai_text: str | None, day_date: date) -> list[dict[str, Any]]:
    if not ai_text:
        return []

    events: list[dict[str, Any]] = []

    # Match BOTH formats:
    # 1. Full: [YYYY-MM-DD] [HH:MM AM/PM] - [HH:MM AM/PM] Title
    # 2. Short: [YYYY-MM-DD] [HH:MM AM/PM] - Title (end time omitted, default to +1 hour)
    pattern = re.compile(
        r"^\s*"
        r"(?:\[?(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\]?\s+)?"
        r"(?:\[?(?P<start_h>\d{1,2}):(?P<start_m>\d{2})\s*(?P<start_ampm>[Aa][Mm]|[Pp][Mm])\]?)"
        r"\s*(?:-|–|to|—)\s*"
        r"(?:\[?(?P<end_h>\d{1,2}):(?P<end_m>\d{2})\s*(?P<end_ampm>[Aa][Mm]|[Pp][Mm])\]?)?"
        r"\s*(?P<title>.+?)\s*$"
    )

    for raw_line in ai_text.splitlines():
        # Drop a markdown bullet and bold markers so "- **9:00 AM - 10:00 AM** Study" still parses.
        line = re.sub(r"^\s*[-*+•]\s+", "", raw_line).replace("**", "").replace("__", "").strip()
        if not line:
            continue

        # Ignore explanatory narrative headers
        if re.match(r"^(Plan Response|Priority List|Long-term items|Note:|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|[A-Z].*Schedule|\d+[.)])", line, re.I):
            continue

        match = pattern.match(line)
        if not match:
            continue

        # Determine event date
        if match.group("year") and match.group("month") and match.group("day"):
            try:
                event_date = date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
            except ValueError:
                continue
        else:
            event_date = day_date

        # Parse start time
        start_hour = int(match.group("start_h"))
        start_minute = int(match.group("start_m"))
        start_ampm = match.group("start_ampm").upper()
        if start_ampm == "PM" and start_hour != 12:
            start_hour += 12
        if start_ampm == "AM" and start_hour == 12:
            start_hour = 0

        start_dt = datetime.combine(event_date, time(start_hour, start_minute), tzinfo=timezone.utc)

        # Parse end time (optional - default to +1 hour if missing)
        if match.group("end_h") and match.group("end_m"):
            end_hour = int(match.group("end_h"))
            end_minute = int(match.group("end_m"))
            end_ampm = match.group("end_ampm").upper() if match.group("end_ampm") else start_ampm
            if end_ampm == "PM" and end_hour != 12:
                end_hour += 12
            if end_ampm == "AM" and end_hour == 12:
                end_hour = 0
            end_dt = datetime.combine(event_date, time(end_hour, end_minute), tzinfo=timezone.utc)
        else:
            # Default to +1 hour if end time not specified
            end_dt = start_dt + timedelta(hours=1)

        # Extract and clean title
        title = match.group("title")
        if title:
            title = re.sub(r"[*_`\[\]]+", "", title).strip(" -:–—")
        
        if not title or len(title) < 2:
            continue

        events.append(
            {
                "title": title,
                "start": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "end": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "color": "#7C4DFF",
                "category": "plan",
                "extendedProps": {
                    "source": "ai_plan",
                },
            }
        )

    return events

def _categorize_event(event: dict[str, Any]) -> tuple[str, str]:
    title = str(event.get("title", "")).lower()
    if any(token in title for token in ["class", "lecture", "lab", "recitation", "seminar", "discussion"]):
        return "class", "#4A90D9"
    if event.get("matched_task") or any(token in title for token in ["task", "deadline", "due", "review", "interview"]):
        return "task", "#E67E22"
    if any(token in title for token in ["personal", "meal", "gym", "sleep", "hangout", "trip"]):
        return "personal", "#2E8B57"
    return "event", "#2E8B57"


def _calendar_event_entry(event: dict[str, Any]) -> dict[str, Any] | None:
    start = event.get("start")
    end = event.get("end")
    if event.get("all_day"):
        start_value = _format_date(start)
        if start_value is None:
            return None
        # All-day end dates are exclusive; default a missing one to the next day.
        end_value = _format_date(end) or (date.fromisoformat(start_value) + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        start_value = _format_datetime(start)
        end_value = _format_datetime(end)
        if start_value is None or end_value is None:
            return None

    category, color = _categorize_event(event)
    entry = {
        "title": str(event.get("title", "Untitled event")),
        "start": start_value,
        "end": end_value,
        "color": color,
        "category": category,
        "extendedProps": {
            "details": event.get("description") or event.get("location") or "",
        },
    }
    if event.get("all_day"):
        entry["allDay"] = True
    return entry


def to_fullcalendar_events(
    day_context: dict[str, Any],
    week_context: dict[str, Any],
    ai_text: str | None = None,
    calendar_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build FullCalendar events. `calendar_events` is every fetched event; defaults to this week's."""
    events: list[dict[str, Any]] = []

    day_date = day_context.get("date") or date.today()
    plan_events = _parse_ai_plan_events(ai_text, day_date)

    if calendar_events is None:
        calendar_events = [event for day_events in week_context.get("events_by_day", {}).values() for event in day_events]
    # Today's events come from day_context because they carry matched_task tags.
    other_day_events = [event for event in calendar_events if _event_day(event.get("start")) != day_date]

    calendar_entries = [
        entry
        for entry in map(_calendar_event_entry, day_context.get("events", []) + other_day_events)
        if entry is not None
    ]
    # The daily plan restates existing events so the sidebar reads as a full schedule; draw each once.
    calendar_starts = {entry["start"] for entry in calendar_entries if not entry.get("allDay")}
    events.extend(event for event in plan_events if event["start"] not in calendar_starts)
    events.extend(calendar_entries)

    for task in (
        day_context.get("tasks_overdue", [])
        + day_context.get("tasks_due_today", [])
        + week_context.get("tasks_this_week", [])
    ):
        due_date = _coerce_date(task.get("due"))
        if due_date is None:
            continue
        events.append(
            {
                "title": f"Task: {task.get('title', 'Untitled task')}",
                "start": due_date.strftime("%Y-%m-%d"),
                "end": (due_date + timedelta(days=1)).strftime("%Y-%m-%d"),
                "allDay": True,
                "color": "#E67E22",
                "category": "task",
                "extendedProps": {
                    "details": task.get("notes") or "",
                },
            }
        )

    for free_block in day_context.get("free_blocks", []):
        start, end = free_block
        start_value = _format_datetime(start)
        end_value = _format_datetime(end)
        if start_value and end_value:
            events.append(
                {
                    "title": "Free block",
                    "start": start_value,
                    "end": end_value,
                    "display": "background",
                    "backgroundColor": "#f2f2f2",
                    "category": "free_block",
                    "editable": False,
                }
            )

    return events
