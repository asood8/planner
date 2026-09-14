"""Ask AI events and accepted suggestions, saved locally in data/ask_ai_events.json so they survive reloads.

Stored events look like {"id", "batch", "date": "YYYY-MM-DD", "start": "HH:MM", "end": "HH:MM", "title"}.
All-day items have "all_day": true and empty start/end. An optional "ref" names the suggestion an event
was accepted from. Every event created by one request shares a batch id so they can be deleted together.
A timed accepted suggestion (a work session) can also carry "status": "done" or "skipped" once the user
checks in on it (core/checkins.py); moving it clears that, since it's a new plan.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any

from core import timeutil
from core.local_store import data_path, locked, read_json, write_json_atomic

FILE_NAME = "ask_ai_events.json"
KEEP_DAYS = 30
MAX_TITLE_LENGTH = 100
MAX_REF_LENGTH = 200
STATUSES = ("done", "skipped")
CLOCK_FORMATS = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p", "%I %p")


def parse_clock(value: Any) -> time | None:
    """Parse "14:00" (what the prompts ask for) and tolerate "2:00 PM" style slips."""
    text = str(value).strip().upper()
    for fmt in CLOCK_FORMATS:
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _clean(raw: Any) -> dict[str, Any] | None:
    """Validate one event; None if it can't be placed on the calendar."""
    if not isinstance(raw, dict):
        return None
    try:
        day = date.fromisoformat(str(raw.get("date", "")).strip())
    except ValueError:
        return None
    title = " ".join(str(raw.get("title") or "").split())[:MAX_TITLE_LENGTH]
    if not title:
        return None

    if raw.get("all_day") is True:
        event = {"date": day.isoformat(), "start": "", "end": "", "title": title, "all_day": True}
    else:
        start = parse_clock(raw.get("start"))
        end = parse_clock(raw.get("end"))
        if start is None or end is None or end <= start:
            return None
        event = {"date": day.isoformat(), "start": start.strftime("%H:%M"), "end": end.strftime("%H:%M"), "title": title}

    ref = str(raw.get("ref") or "").strip()[:MAX_REF_LENGTH]
    if ref:
        event["ref"] = ref
        if raw.get("status") in STATUSES and not event.get("all_day"):
            event["status"] = raw["status"]
    return event


def _key(event: dict[str, Any]) -> tuple[str, str, str, str]:
    return (event.get("date", ""), event.get("start", ""), event.get("end", ""), str(event.get("title", "")).lower())


def _read() -> list[dict[str, Any]]:
    data = read_json(data_path(FILE_NAME), [])
    return [event for event in data if isinstance(event, dict)] if isinstance(data, list) else []


def _write(events: list[dict[str, Any]]) -> None:
    write_json_atomic(data_path(FILE_NAME), events)


def load_saved_events() -> list[dict[str, Any]]:
    return _read()


def add_saved_events(raw_events: list[Any]) -> list[dict[str, Any]]:
    """Validate, dedupe, and save events from one request. Returns only the newly saved ones."""
    batch = uuid.uuid4().hex[:12]
    cutoff = (timeutil.today() - timedelta(days=KEEP_DAYS)).isoformat()
    with locked(FILE_NAME):
        # Pruning old events here keeps the file from growing forever.
        existing = [event for event in _read() if event.get("date", "") >= cutoff]
        seen = {_key(event) for event in existing}
        added = []
        for raw in raw_events:
            event = _clean(raw)
            if event is None or _key(event) in seen:
                continue
            seen.add(_key(event))
            added.append({"id": uuid.uuid4().hex[:12], "batch": batch, **event})
        if added:
            _write(existing + added)
        return added


def update_saved_event(event_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Move or resize a saved event (date/start/end/all_day). Title, ref, id, and batch are kept; a check-in
    status is cleared, because a moved session is a new plan.

    Raises KeyError if there's no such event and ValueError if the new timing is invalid.
    """
    with locked(FILE_NAME):
        events = _read()
        index = next((i for i, event in enumerate(events) if event.get("id") == event_id), None)
        if index is None:
            raise KeyError(event_id)
        allowed = {key: value for key, value in changes.items() if key in ("date", "start", "end", "all_day")}
        current = {key: value for key, value in events[index].items() if key != "status"}
        cleaned = _clean({**current, **allowed})
        if cleaned is None:
            raise ValueError("The event needs a date, and an end time after its start on the same day.")
        updated = {"id": events[index]["id"], "batch": events[index].get("batch"), **cleaned}
        events[index] = updated
        _write(events)
        return updated


def set_session_status(event_id: str, status: str | None) -> dict[str, Any]:
    """Check in on a work session: "done", "skipped", or None to clear it.

    Raises KeyError if there's no such event, and ValueError for another status or an event that isn't a
    timed accepted suggestion.
    """
    if status is not None and status not in STATUSES:
        raise ValueError("status must be done, skipped, or null")
    with locked(FILE_NAME):
        events = _read()
        index = next((i for i, event in enumerate(events) if event.get("id") == event_id), None)
        if index is None:
            raise KeyError(event_id)
        event = {key: value for key, value in events[index].items() if key != "status"}
        if not event.get("ref") or event.get("all_day"):
            raise ValueError("Only work sessions added from suggestions can be checked in.")
        if status:
            event["status"] = status
        events[index] = event
        _write(events)
        return event


def delete_saved_event(event_id: str, include_batch: bool = False) -> int:
    """Delete one saved event (or its whole batch). Returns how many were removed."""
    with locked(FILE_NAME):
        events = _read()
        target = next((event for event in events if event.get("id") == event_id), None)
        if target is None:
            return 0
        if include_batch and target.get("batch"):
            kept = [event for event in events if event.get("batch") != target["batch"]]
        else:
            kept = [event for event in events if event.get("id") != event_id]
        _write(kept)
        return len(events) - len(kept)


def delete_upcoming(ref: str, after: datetime) -> int:
    """Delete saved events carrying `ref` that start after `after` (e.g. sessions for a task just finished)."""
    with locked(FILE_NAME):
        events = _read()

        def upcoming(event: dict[str, Any]) -> bool:
            cleaned = _clean(event)
            if cleaned is None or cleaned.get("ref") != ref or cleaned.get("all_day"):
                return False
            return timeutil.at(date.fromisoformat(cleaned["date"]), parse_clock(cleaned["start"])) > after

        kept = [event for event in events if not upcoming(event)]
        if len(kept) != len(events):
            _write(kept)
        return len(events) - len(kept)


def to_calendar_events(saved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Saved events in the shape fetch/calendar.py returns (aware local datetimes, or dates for all-day)."""
    events = []
    for event in saved:
        cleaned = _clean(event)
        if cleaned is None:
            continue
        day = date.fromisoformat(cleaned["date"])
        if cleaned.get("all_day"):
            start, end = day, day + timedelta(days=1)
        else:
            start = timeutil.at(day, parse_clock(cleaned["start"]))
            end = timeutil.at(day, parse_clock(cleaned["end"]))
        events.append(
            {
                "title": cleaned["title"],
                "start": start,
                "end": end,
                "description": "Accepted suggestion" if cleaned.get("ref") else "Added by Ask AI",
                "location": "",
                "all_day": bool(cleaned.get("all_day")),
                "recurring": False,
                "source": "ask_ai",
                "id": event.get("id"),
                "batch": event.get("batch"),
                "ref": cleaned.get("ref"),
                "status": cleaned.get("status"),
            }
        )
    return events
