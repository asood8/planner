from datetime import date, datetime, time, timedelta

from googleapiclient.discovery import build

from auth.google_auth import get_credentials
from core import timeutil


def _sort_key(event):
    """Sort all-day events (plain dates) at local midnight alongside timed events."""
    start = event["start"]
    return start if isinstance(start, datetime) else timeutil.at(start, time.min)


def get_events(creds=None, days_ahead=14):
    """Return upcoming calendar events as clean dictionaries.

    Timed events are aware datetimes in local time (see core/timeutil.py); all-day events are plain dates.
    """
    if creds is None:
        creds = get_credentials()

    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    # Start at local midnight so events earlier today still count toward today's schedule.
    day_start = timeutil.at(timeutil.today(), time.min)
    time_min = day_start.isoformat()
    time_max = (day_start + timedelta(days=days_ahead)).isoformat()

    items = []
    page_token = None
    while True:
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                pageToken=page_token,
            )
            .execute()
        )
        items.extend(events_result.get("items", []))
        page_token = events_result.get("nextPageToken")
        if not page_token:
            break

    events = []
    for item in items:
        start_raw = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
        end_raw = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date")
        all_day = "date" in item.get("start", {})

        start_dt = None
        end_dt = None

        if start_raw:
            if all_day:
                start_dt = date.fromisoformat(start_raw)
                end_dt = date.fromisoformat(end_raw) if end_raw else None
            else:
                start_dt = timeutil.to_local(datetime.fromisoformat(start_raw.replace("Z", "+00:00")))
                end_dt = timeutil.to_local(datetime.fromisoformat(end_raw.replace("Z", "+00:00"))) if end_raw else None

        if start_dt is None:
            continue

        event = {
            "title": item.get("summary") or "Untitled event",
            "start": start_dt,
            "end": end_dt,
            "description": item.get("description", ""),
            "location": item.get("location", ""),
            "all_day": all_day,
            "recurring": bool(item.get("recurringEventId")),
        }
        events.append(event)

    return sorted(events, key=_sort_key)
