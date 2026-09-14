from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from core import timeutil

MIN_FREE_BLOCK_MINUTES = 30
DEFAULT_WORKDAY_START = 8
DEFAULT_WORKDAY_END = 22
_LATEST = datetime.max.replace(tzinfo=timezone.utc)


def _start_key(event: dict[str, Any]) -> datetime:
    return timeutil.to_utc(event.get("start")) or _LATEST


def _filter_today(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    today = timeutil.today()
    return sorted((event for event in events if timeutil.local_day(event.get("start")) == today), key=_start_key)


def _coerce_task_due(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def flatten_tasks(tasks: Any) -> list[dict[str, Any]]:
    """Task dicts from a plain list or Google's grouped {"overdue": [...], ...} dict."""
    if isinstance(tasks, dict):
        flattened = []
        for bucket in ("overdue", "has_due_date", "no_due_date"):
            items = tasks.get(bucket, [])
            if isinstance(items, list):
                flattened.extend([item for item in items if isinstance(item, dict)])
        return flattened
    if isinstance(tasks, list):
        return [task for task in tasks if isinstance(task, dict)]
    return []


def _filter_week(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    today = timeutil.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    filtered = []
    for event in events:
        event_day = timeutil.local_day(event.get("start"))
        if event_day is not None and week_start <= event_day <= week_end:
            filtered.append(event)
    return sorted(filtered, key=_start_key)


def _workday_bound(day: date, hour: int) -> datetime:
    """Local time at `hour` on `day`, with that day's own UTC offset; hour 24 means the next midnight."""
    return timeutil.at(day + timedelta(days=hour // 24), time(hour % 24))


def _find_free_blocks(
    today_events: list[dict[str, Any]],
    workday_start: int = DEFAULT_WORKDAY_START,
    workday_end: int = DEFAULT_WORKDAY_END,
    day: date | None = None,
) -> list[tuple[datetime, datetime]]:
    """Free blocks within the workday on `day` (default today) around the given events."""
    day = day or timeutil.today()
    timed_events = []
    for event in today_events:
        start = timeutil.to_utc(event.get("start"))
        end = timeutil.to_utc(event.get("end"))
        if not start or not end or event.get("all_day"):
            continue
        timed_events.append((timeutil.to_local(start), timeutil.to_local(end)))

    timed_events.sort(key=lambda item: item[0])

    workday_start_dt = _workday_bound(day, workday_start)
    workday_end_dt = _workday_bound(day, workday_end)
    min_block = timedelta(minutes=MIN_FREE_BLOCK_MINUTES)
    cursor = workday_start_dt
    free_blocks = []

    for start, end in timed_events:
        block_end = min(start, workday_end_dt)
        if cursor < block_end and block_end - cursor >= min_block:
            free_blocks.append((cursor, block_end))
        if end > cursor:
            cursor = end

    if cursor < workday_end_dt and workday_end_dt - cursor >= min_block:
        free_blocks.append((cursor, workday_end_dt))

    return free_blocks


def free_blocks_for_day(
    events: list[dict[str, Any]],
    day: date,
    workday_start: int = DEFAULT_WORKDAY_START,
    workday_end: int = DEFAULT_WORKDAY_END,
) -> list[tuple[datetime, datetime]]:
    """Free blocks on any day (not just today), picking that day's events out of the full list."""
    day_events = [event for event in events if timeutil.local_day(event.get("start")) == day]
    return _find_free_blocks(day_events, workday_start, workday_end, day=day)


def _find_conflicts(today_events: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    timed_events = []
    for event in today_events:
        start = timeutil.to_utc(event.get("start"))
        end = timeutil.to_utc(event.get("end"))
        if not start or not end or event.get("all_day"):
            continue
        timed_events.append((start, end, event))

    timed_events.sort(key=lambda item: item[0])
    conflicts = []
    for index in range(len(timed_events) - 1):
        current_end = timed_events[index][1]
        next_start = timed_events[index + 1][0]
        if current_end > next_start:
            conflicts.append((timed_events[index][2], timed_events[index + 1][2]))
    return conflicts


def _tag_events_with_tasks(today_events: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    today = timeutil.today()
    tagged_events = []
    for event in today_events:
        event_title = str(event.get("title", ""))
        matched_task = None
        for task in tasks:
            task_due = _coerce_task_due(task.get("due"))
            if task_due and task_due.date() == today:
                candidate_title = str(task.get("title", ""))
                if candidate_title.lower() in event_title.lower() or event_title.lower() in candidate_title.lower():
                    matched_task = task
                    break
        if matched_task is not None:
            event_copy = dict(event)
            event_copy["matched_task"] = matched_task
            tagged_events.append(event_copy)
        else:
            tagged_events.append(event)
    return tagged_events


def _bucket_emails(emails: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    today = timeutil.today()
    week_start = today - timedelta(days=today.weekday())
    buckets = {"today": [], "this_week": [], "older": []}

    for email in emails:
        received = email.get("date")
        if isinstance(received, str):
            try:
                received = parsedate_to_datetime(received)
            except Exception:
                received = None

        if not isinstance(received, datetime):
            continue

        received_day = timeutil.local_day(received)
        if received_day == today:
            buckets["today"].append(email)
        elif week_start <= received_day <= today:
            buckets["this_week"].append(email)
        else:
            buckets["older"].append(email)

    for bucket in buckets:
        buckets[bucket].sort(key=lambda item: item.get("date") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return buckets


def task_due_day(task: dict[str, Any]) -> date | None:
    # Google Tasks due values are date-only (midnight UTC), so take the UTC date as-is.
    due = _coerce_task_due(task.get("due"))
    return due.date() if due else None


def task_key(task: dict[str, Any]) -> str:
    """Stable id for a task: its id (Google or iCal), else list/title."""
    return str(task.get("id") or f"{task.get('list', '')}/{task.get('title', '')}".lower())


def normalize(
    events: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    emails: list[dict[str, Any]],
    workday_start: int = DEFAULT_WORKDAY_START,
    workday_end: int = DEFAULT_WORKDAY_END,
) -> tuple[dict[str, Any], dict[str, Any]]:
    today = timeutil.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    normalized_tasks = flatten_tasks(tasks)

    today_events = _filter_today(events)
    week_events = _filter_week(events)
    free_blocks = _find_free_blocks(today_events, workday_start, workday_end)
    conflicts = _find_conflicts(today_events)
    tagged_today_events = _tag_events_with_tasks(today_events, normalized_tasks)

    email_buckets = _bucket_emails(emails)

    # Task buckets are disjoint so no task is listed (or drawn on the calendar) twice.
    overdue_tasks, due_today_tasks, week_tasks, later_tasks, no_due_tasks = [], [], [], [], []
    for task in normalized_tasks:
        due_day = task_due_day(task)
        if due_day is None:
            no_due_tasks.append(task)
        elif due_day < today:
            overdue_tasks.append(task)
        elif due_day == today:
            due_today_tasks.append(task)
        elif due_day <= week_end:
            week_tasks.append(task)
        else:
            later_tasks.append(task)

    day_context = {
        "date": today,
        "events": tagged_today_events,
        "free_blocks": free_blocks,
        "conflicts": conflicts,
        "tasks_overdue": overdue_tasks,
        "tasks_due_today": due_today_tasks,
        "emails_today": email_buckets["today"],
    }

    week_context = {
        "date_range": (week_start, week_end),
        "events_by_day": {},
        "tasks_this_week": week_tasks,
        "tasks_later": later_tasks,
        "tasks_no_due": no_due_tasks,
        "emails_this_week": email_buckets["this_week"],
        "emails_older": email_buckets["older"],
    }

    for event in week_events:
        event_day = timeutil.local_day(event.get("start"))
        if event_day is None:
            continue
        week_context["events_by_day"].setdefault(event_day, []).append(event)

    for day_key in week_context["events_by_day"]:
        week_context["events_by_day"][day_key] = sorted(week_context["events_by_day"][day_key], key=_start_key)

    return day_context, week_context
