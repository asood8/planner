from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from core import timeutil
from core.normalizer import task_key

# Saved Ask AI events and accepted suggestions (click to delete, drag to move).
ASK_AI_COLOR = "#C026D3"
# Suggestions are drawn as white boxes with a dashed border in their kind's color.
SUGGESTION_COLORS = {"study": "#0D9488", "exam": "#0D9488", "deadline": "#DC2626", "reply": "#D97706"}
SESSION_KINDS = ("study", "exam")
STATUS_DETAILS = {
    "done": "You did this session.",
    "skipped": "Skipped. Its time went back into the suggestions.",
}


def _coerce_date(value: Any) -> date | None:
    """A date as stored, without converting to local time (tasks keep their UTC due date)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        parsed = timeutil.parse_iso(value)
        return parsed.date() if parsed else None
    return None


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

        # The UTC here is only a label: these are wall-clock times, formatted without an offset below.
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
        start_value = timeutil.wall_clock(start)
        end_value = timeutil.wall_clock(end)
        if start_value is None or end_value is None:
            return None

    if event.get("source") == "ask_ai":
        category, color = "ask_ai", ASK_AI_COLOR
        status = event.get("status")
        extended_props = {
            "details": STATUS_DETAILS.get(status) or f"{event.get('description') or 'Added by Ask AI'}. Click to delete, or drag to move.",
            "source": "ask_ai",
            "id": event.get("id"),
            "batch": event.get("batch"),
            "ref": event.get("ref"),
            "status": status,
        }
    else:
        category, color = _categorize_event(event)
        extended_props = {"details": event.get("description") or event.get("location") or ""}
    entry = {
        "title": str(event.get("title", "Untitled event")),
        "start": start_value,
        "end": end_value,
        "color": color,
        "category": category,
        "extendedProps": extended_props,
    }
    if event.get("all_day"):
        entry["allDay"] = True
    if event.get("source") == "ask_ai":
        # Saved events can be dragged to a new time; all-day ones only to another day.
        entry["editable"] = True
        if event.get("all_day"):
            entry["durationEditable"] = False
    return entry


def _suggestion_entry(item: dict[str, Any]) -> dict[str, Any]:
    """A suggestion from core/suggestions.py; the whole item rides along so the page can accept it."""
    entry = {
        "title": item["title"],
        "backgroundColor": "#FFFFFF",
        "borderColor": SUGGESTION_COLORS.get(item.get("kind"), "#6B7280"),
        "textColor": "#111827",
        # Dragging a timed suggestion accepts it at the new time; deadline dates come from the email.
        "editable": not item.get("all_day"),
        "classNames": ["suggestion"],
        "category": "suggestion",
        "extendedProps": {
            "source": "suggestion",
            "details": f"{item.get('details') or ''}\nSuggested. Click to add it or dismiss it.".strip(),
            "suggestion": item,
        },
    }
    if item.get("all_day"):
        day = date.fromisoformat(item["date"])
        entry.update(start=day.isoformat(), end=(day + timedelta(days=1)).isoformat(), allDay=True)
    else:
        entry.update(start=f"{item['date']}T{item['start']}:00", end=f"{item['date']}T{item['end']}:00")
    return entry


def _mark_conflicts(entries: list[dict[str, Any]]) -> None:
    """Flag timed calendar entries that overlap another one (drawn with a red outline)."""
    # Local "YYYY-MM-DDTHH:MM:SS" strings sort chronologically.
    timed = sorted((entry for entry in entries if not entry.get("allDay")), key=lambda entry: entry["start"])
    latest = None  # the entry with the latest end so far
    for entry in timed:
        if latest is not None and entry["start"] < latest["end"]:
            for flagged in (entry, latest):
                flagged["classNames"] = ["has-conflict"]
                flagged["extendedProps"]["conflict"] = True
        if latest is None or entry["end"] > latest["end"]:
            latest = entry


def to_fullcalendar_events(
    day_context: dict[str, Any],
    week_context: dict[str, Any],
    ai_text: str | None = None,
    calendar_events: list[dict[str, Any]] | None = None,
    suggestions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build FullCalendar events. `calendar_events` is every fetched event (defaults to this week's);
    `suggestions` is build_suggestions()["items"]."""
    events: list[dict[str, Any]] = []

    day_date = day_context.get("date") or timeutil.today()
    plan_events = _parse_ai_plan_events(ai_text, day_date)

    if calendar_events is None:
        calendar_events = [event for day_events in week_context.get("events_by_day", {}).values() for event in day_events]
    # Today's events come from day_context because they carry matched_task tags.
    other_day_events = [event for event in calendar_events if timeutil.local_day(event.get("start")) != day_date]

    calendar_entries = [
        entry
        for entry in map(_calendar_event_entry, day_context.get("events", []) + other_day_events)
        if entry is not None
    ]
    _mark_conflicts(calendar_entries)
    suggestion_entries = [_suggestion_entry(item) for item in suggestions or []]

    # The daily plan restates existing events and suggested work sessions so the sidebar reads as a full
    # schedule; draw each once. A short reply reminder doesn't stand in for a different plan block.
    taken_starts = {entry["start"] for entry in calendar_entries if not entry.get("allDay")}
    taken_starts |= {
        entry["start"]
        for entry in suggestion_entries
        if not entry.get("allDay") and entry["extendedProps"]["suggestion"].get("kind") in SESSION_KINDS
    }
    events.extend(event for event in plan_events if event["start"] not in taken_starts)
    events.extend(calendar_entries)
    events.extend(suggestion_entries)

    for task in (
        day_context.get("tasks_overdue", [])
        + day_context.get("tasks_due_today", [])
        + week_context.get("tasks_this_week", [])
    ):
        due_date = _coerce_date(task.get("due"))
        if due_date is None:
            continue
        title = str(task.get("title", "Untitled task"))
        due_time = f" (due {timeutil.twelve_hour(task['due_time'])})" if task.get("due_time") else ""
        details = task.get("notes") or ""
        if task.get("source") == "ical":
            details = f"From {task.get('list') or 'a calendar feed'}" + (f"\n{details}" if details else "")
        events.append(
            {
                "title": f"Task: {title}{due_time}",
                "start": due_date.strftime("%Y-%m-%d"),
                "end": (due_date + timedelta(days=1)).strftime("%Y-%m-%d"),
                "allDay": True,
                "color": "#E67E22",
                "category": "task",
                "extendedProps": {
                    "details": details,
                    "source": "task",
                    "key": task_key(task),
                    "task_title": title,
                },
            }
        )

    for free_block in day_context.get("free_blocks", []):
        start, end = free_block
        start_value = timeutil.wall_clock(start)
        end_value = timeutil.wall_clock(end)
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
