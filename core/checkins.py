"""Check-ins on work sessions that have passed: did they happen?

An accepted study or exam-review session counts toward its task as soon as it's on the calendar. If it was
skipped, saying so (saved_events.set_session_status) takes it back out, so its time is suggested again.
Sessions nobody has checked in on still count, and are listed here for a week so they can be.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from core import timeutil
from core.saved_events import to_calendar_events

CHECKIN_DAYS = 7
STUDY_PREFIX = "study:"
SESSION_PREFIXES = (STUDY_PREFIX, "exam:")


def is_session(event: dict[str, Any]) -> bool:
    """A timed saved event accepted from a study or exam-review suggestion."""
    return str(event.get("ref") or "").startswith(SESSION_PREFIXES) and not event.get("all_day")


def pending_checkins(saved: list[dict[str, Any]], done_keys: set[str], now: datetime) -> list[dict[str, Any]]:
    """Sessions from the last CHECKIN_DAYS days that have ended without a check-in, oldest first, as
    {id, title, date, start, end} with HH:MM times. Sessions for tasks already marked done are left out."""
    earliest = now.date() - timedelta(days=CHECKIN_DAYS)
    pending = []
    for event in to_calendar_events(saved):
        if not is_session(event) or event.get("status") or event["end"] > now:
            continue
        ref = str(event["ref"])
        if ref.startswith(STUDY_PREFIX) and ref[len(STUDY_PREFIX):] in done_keys:
            continue
        start, end = timeutil.to_local(event["start"]), timeutil.to_local(event["end"])
        if start.date() < earliest:
            continue
        pending.append({
            "id": event["id"],
            "title": event["title"],
            "date": start.date().isoformat(),
            "start": start.strftime("%H:%M"),
            "end": end.strftime("%H:%M"),
        })
    return sorted(pending, key=lambda item: (item["date"], item["start"]))
