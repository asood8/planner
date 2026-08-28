from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


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
        line = raw_line.strip()
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


def to_fullcalendar_events(day_context: dict[str, Any], week_context: dict[str, Any], ai_text: str | None = None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    day_date = day_context.get("date") or date.today()
    events.extend(_parse_ai_plan_events(ai_text, day_date))

    for event in day_context.get("events", []):
        start = event.get("start")
        end = event.get("end")
        all_day = bool(event.get("all_day"))
        category, color = _categorize_event(event)
        if all_day:
            start_date = _format_date(start)
            end_date = _format_date(end) or (date.fromisoformat(start_date) + timedelta(days=1)).strftime("%Y-%m-%d") if start_date else None
            if start_date and end_date:
                events.append(
                    {
                        "title": str(event.get("title", "Untitled event")),
                        "start": start_date,
                        "end": end_date,
                        "allDay": True,
                        "color": color,
                        "category": category,
                        "extendedProps": {
                            "details": event.get("description") or event.get("location") or "",
                        },
                    }
                )
        else:
            start_value = _format_datetime(start)
            end_value = _format_datetime(end)
            if start_value and end_value:
                events.append(
                    {
                        "title": str(event.get("title", "Untitled event")),
                        "start": start_value,
                        "end": end_value,
                        "color": color,
                        "category": category,
                        "extendedProps": {
                            "details": event.get("description") or event.get("location") or "",
                        },
                    }
                )

    for task in day_context.get("tasks_overdue", []) + day_context.get("tasks_due_today", []):
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

    for task in week_context.get("tasks_this_week", []):
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
