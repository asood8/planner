"""Read-only calendar feeds: Canvas, school calendars, or a Google Calendar's secret iCal address.

No sign-in is involved: each feed is a private URL in config.json ("ical_feeds", validated in
core/settings.py). Timed and all-day events become calendar events (busy time). Assignment-style
entries (Canvas assignments, or zero-length events that mark a due time) become task-like deadlines,
so they show up with the tasks and get study-block suggestions.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import icalendar
import recurring_ical_events
import requests

from core import timeutil
from core.settings import Settings

FEED_TIMEOUT = 15
DEADLINE_LOOKBACK_DAYS = 3
DEADLINE_LOOKAHEAD_DAYS = 21
MAX_DESCRIPTION_LENGTH = 300

logger = logging.getLogger(__name__)


def _text(component, key: str) -> str:
    return " ".join(str(component.get(key) or "").split())


def parse_feed(
    content: bytes | str, name: str, today: date, days_ahead: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(events, deadlines) from one feed's iCal text, with recurring events expanded."""
    calendar = icalendar.Calendar.from_ical(content)
    first_day = today - timedelta(days=DEADLINE_LOOKBACK_DAYS)
    last_day = today + timedelta(days=max(days_ahead, DEADLINE_LOOKAHEAD_DAYS))
    events_end = today + timedelta(days=days_ahead)

    events: list[dict[str, Any]] = []
    deadlines: list[dict[str, Any]] = []
    for component in recurring_ical_events.of(calendar).between(first_day, last_day + timedelta(days=1)):
        start = component.decoded("DTSTART")
        if "DTEND" in component:
            end = component.decoded("DTEND")
        elif "DURATION" in component:
            end = start + component.decoded("DURATION")
        else:
            end = None
        uid = str(component.get("UID") or "")
        title = _text(component, "SUMMARY") or "Untitled event"
        description = _text(component, "DESCRIPTION")[:MAX_DESCRIPTION_LENGTH]

        # Canvas assignment UIDs look like "event-assignment-123"; other feeds mark due times with zero-length events.
        is_deadline = "assignment" in uid.lower() or (isinstance(start, datetime) and (end is None or end == start))
        if is_deadline:
            due_day = timeutil.local_day(start)
            if not first_day <= due_day <= last_day:
                continue
            deadlines.append(
                {
                    "id": f"ical:{uid or title}",
                    "title": title,
                    "notes": description,
                    # Same convention as Google Tasks: a date-only due value at midnight UTC.
                    "due": datetime.combine(due_day, time.min, tzinfo=timezone.utc),
                    "due_time": timeutil.to_local(start).strftime("%H:%M") if isinstance(start, datetime) else None,
                    "list": name,
                    "source": "ical",
                }
            )
            continue

        if isinstance(start, datetime):
            start_value = timeutil.to_local(start)
            end_value = timeutil.to_local(end) if isinstance(end, datetime) else start_value + timedelta(hours=1)
            if not today <= start_value.date() <= events_end:
                continue
            all_day = False
        else:
            start_value = start
            has_end = isinstance(end, date) and not isinstance(end, datetime) and end > start
            end_value = end if has_end else start + timedelta(days=1)
            if end_value <= today or start_value > events_end:
                continue
            all_day = True

        events.append(
            {
                "title": title,
                "start": start_value,
                "end": end_value,
                "description": description,
                "location": _text(component, "LOCATION"),
                "all_day": all_day,
                "recurring": "RRULE" in component or "RECURRENCE-ID" in component,
                "feed": name,
            }
        )
    return events, deadlines


def _reason(exc: Exception) -> str:
    """Why a feed failed, without the exception text: request errors often quote the private URL."""
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        return f"the server answered HTTP {exc.response.status_code}"
    if isinstance(exc, requests.exceptions.Timeout):
        return "the request timed out"
    if isinstance(exc, requests.exceptions.RequestException):
        return f"couldn't connect ({type(exc).__name__})"
    return f"couldn't read the feed ({type(exc).__name__})"


def fetch_feeds(settings: Settings, today: date | None = None) -> tuple[list, list, bool | None]:
    """Fetch every configured feed. Returns (events, deadlines, ok); ok is None when no feeds are configured."""
    if not settings.ical_feeds:
        return [], [], None
    today = today or timeutil.today()

    events, deadlines, ok = [], [], True
    for feed in settings.ical_feeds:
        try:
            response = requests.get(feed.url, timeout=FEED_TIMEOUT)
            response.raise_for_status()
            feed_events, feed_deadlines = parse_feed(response.content, feed.name, today, settings.calendar_days_ahead)
        except Exception as exc:
            logger.warning("Calendar feed '%s' failed: %s", feed.name, _reason(exc))
            ok = False
            continue
        events.extend(feed_events)
        deadlines.extend(feed_deadlines)
    return events, deadlines, ok
