"""The end-of-day review: what got done, how today's work sessions went, what's still open, and how tomorrow
starts. The page shows it from user_profile.review_hour; `plan.py --review` sends it as a notification.

Nothing needs moving by hand: skipped sessions (core/checkins.py) and tasks still open get time suggested
again, and a task due today that's still open counts as overdue tomorrow, which also gets time.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from core import timeutil
from core.checkins import is_session
from core.normalizer import task_key
from core.saved_events import to_calendar_events

SESSION_KINDS = ("study", "exam")


def day_review(
    now: datetime,
    saved: list[dict[str, Any]],
    done_entries: list[dict[str, Any]],
    open_tasks: list[dict[str, Any]],
    events: list[dict[str, Any]],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """{finished: [titles], sessions: {done, skipped, unchecked}, open: [{key, title}], tomorrow: str}.

    `open_tasks` are tasks due today or overdue that aren't done; `events` are calendar events (saved ones
    included) and `items` are suggestions, for the look at tomorrow.
    """
    today = now.date()
    finished = [str(entry.get("title") or "Untitled task") for entry in done_entries if entry.get("done_at") == today.isoformat()]
    sessions = {"done": 0, "skipped": 0, "unchecked": 0}
    for event in to_calendar_events(saved):
        if is_session(event) and timeutil.local_day(event["start"]) == today and event["end"] <= now:
            sessions[event.get("status") or "unchecked"] += 1
    still_open = [{"key": task_key(task), "title": str(task.get("title") or "Untitled task")} for task in open_tasks]
    return {"finished": finished, "sessions": sessions, "open": still_open, "tomorrow": _tomorrow(events, items, today)}


def _tomorrow(events: list[dict[str, Any]], items: list[dict[str, Any]], today) -> str:
    tomorrow = today + timedelta(days=1)
    timed = sorted(
        (timeutil.to_local(event["start"]), str(event.get("title") or "Untitled event"))
        for event in events
        if isinstance(event.get("start"), datetime) and timeutil.local_day(event["start"]) == tomorrow
    )
    sessions = sorted(
        item["start"] for item in items if item.get("kind") in SESSION_KINDS and item.get("date") == tomorrow.isoformat()
    )
    parts = []
    if timed:
        start, title = timed[0]
        parts.append(f"Tomorrow starts with {title} at {timeutil.twelve_hour(start.strftime('%H:%M'))}.")
    if sessions:
        count = len(sessions)
        parts.append(f"{count} work session{'s' if count != 1 else ''} suggested, the first at {timeutil.twelve_hour(sessions[0])}.")
    return " ".join(parts) or "Nothing on the calendar for tomorrow yet."
