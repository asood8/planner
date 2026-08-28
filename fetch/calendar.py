from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build

from auth.google_auth import get_credentials


def get_events(creds=None, days_ahead=14):
    """Return upcoming calendar events as clean dictionaries."""
    if creds is None:
        creds = get_credentials()

    service = build("calendar", "v3", credentials=creds)

    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=days_ahead)).isoformat()

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = []
    for item in events_result.get("items", []):
        start_raw = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
        end_raw = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date")
        all_day = "date" in item.get("start", {})

        start_dt = None
        end_dt = None

        if start_raw:
            if all_day:
                start_dt = datetime.fromisoformat(start_raw).date()
                end_dt = datetime.fromisoformat(end_raw).date() if end_raw else None
            else:
                start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00")) if end_raw else None

        if start_dt is None:
            continue

        if isinstance(start_dt, datetime):
            start_local = start_dt.astimezone().replace(tzinfo=None)
        else:
            start_local = start_dt

        if isinstance(end_dt, datetime):
            end_local = end_dt.astimezone().replace(tzinfo=None)
        else:
            end_local = end_dt

        event = {
            "title": item.get("summary") or "Untitled event",
            "start": start_local,
            "end": end_local,
            "description": item.get("description", ""),
            "location": item.get("location", ""),
            "all_day": all_day,
            "recurring": bool(item.get("recurringEventId")),
        }
        events.append(event)

    return sorted(events, key=lambda item: item["start"])
