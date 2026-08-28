from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from difflib import SequenceMatcher
from typing import Any


MIN_FREE_BLOCK_MINUTES = 30
DEFAULT_WORKDAY_START = 8
DEFAULT_WORKDAY_END = 22


def _coerce_event_day(value: Any) -> date | None:
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


def _coerce_event_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _filter_today(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    today = date.today()
    filtered = []
    for event in events:
        event_day = _coerce_event_day(event.get("start"))
        if event_day == today:
            filtered.append(event)
    return sorted(filtered, key=lambda item: _coerce_event_datetime(item.get("start")) or datetime.max.replace(tzinfo=timezone.utc))


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


def _normalize_task_list(tasks: Any) -> list[dict[str, Any]]:
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
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    filtered = []
    for event in events:
        event_day = _coerce_event_day(event.get("start"))
        if week_start <= event_day <= week_end:
            filtered.append(event)
    return sorted(filtered, key=lambda item: _coerce_event_datetime(item.get("start")) or datetime.max.replace(tzinfo=timezone.utc))


def _find_free_blocks(today_events: list[dict[str, Any]], workday_start: int = DEFAULT_WORKDAY_START, workday_end: int = DEFAULT_WORKDAY_END) -> list[tuple[datetime, datetime]]:
    local_tz = datetime.now().astimezone().tzinfo
    timed_events = []
    for event in today_events:
        start = _coerce_event_datetime(event.get("start"))
        end = _coerce_event_datetime(event.get("end"))
        if not start or not end or event.get("all_day"):
            continue
        local_start = start.astimezone(local_tz)
        local_end = end.astimezone(local_tz)
        timed_events.append((local_start, local_end))

    timed_events.sort(key=lambda item: item[0])

    today_local = date.today()
    workday_start_dt = datetime.combine(today_local, datetime.min.time().replace(hour=workday_start), tzinfo=local_tz)
    workday_end_dt = datetime.combine(today_local, datetime.min.time().replace(hour=workday_end), tzinfo=local_tz)
    cursor = workday_start_dt
    free_blocks = []

    for start, end in timed_events:
        if cursor < start and (start - cursor).total_seconds() >= MIN_FREE_BLOCK_MINUTES * 60:
            free_blocks.append((cursor, start))
        if end > cursor:
            cursor = end

    if cursor < workday_end_dt:
        free_blocks.append((cursor, workday_end_dt))

    return free_blocks


def _find_conflicts(today_events: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    timed_events = []
    for event in today_events:
        start = _coerce_event_datetime(event.get("start"))
        end = _coerce_event_datetime(event.get("end"))
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
    tagged_events = []
    for event in today_events:
        event_title = str(event.get("title", ""))
        matched_task = None
        for task in tasks:
            task_due = _coerce_task_due(task.get("due"))
            if task_due and task_due.date() == date.today():
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
    today = date.today()
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

        if received.date() == today:
            buckets["today"].append(email)
        elif week_start <= received.date() <= today:
            buckets["this_week"].append(email)
        else:
            buckets["older"].append(email)

    for bucket in buckets:
        buckets[bucket].sort(key=lambda item: item.get("date") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return buckets


def normalize(events: list[dict[str, Any]], tasks: list[dict[str, Any]], emails: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    normalized_tasks = _normalize_task_list(tasks)

    today_events = _filter_today(events)
    week_events = _filter_week(events)
    free_blocks = _find_free_blocks(today_events)
    conflicts = _find_conflicts(today_events)
    tagged_today_events = _tag_events_with_tasks(today_events, normalized_tasks)

    email_buckets = _bucket_emails(emails)

    today_tasks = [task for task in normalized_tasks if _coerce_task_due(task.get("due")) and _coerce_task_due(task.get("due")).date() < today]
    due_today_tasks = [task for task in normalized_tasks if _coerce_task_due(task.get("due")) and _coerce_task_due(task.get("due")).date() == today]
    week_tasks = [task for task in normalized_tasks if _coerce_task_due(task.get("due")) and week_start <= _coerce_task_due(task.get("due")).date() <= week_end]
    no_due_tasks = [task for task in normalized_tasks if not _coerce_task_due(task.get("due"))]

    day_context = {
        "date": today,
        "events": tagged_today_events,
        "free_blocks": free_blocks,
        "conflicts": conflicts,
        "tasks_overdue": today_tasks,
        "tasks_due_today": due_today_tasks,
        "emails_today": email_buckets["today"],
    }

    week_context = {
        "date_range": (week_start, week_end),
        "events_by_day": {},
        "tasks_this_week": week_tasks,
        "tasks_no_due": no_due_tasks,
        "emails_this_week": email_buckets["this_week"],
        "emails_older": email_buckets["older"],
    }

    for event in week_events:
        event_day = _coerce_event_day(event.get("start"))
        if event_day is None:
            continue
        week_context["events_by_day"].setdefault(event_day, []).append(event)

    for day_key in week_context["events_by_day"]:
        week_context["events_by_day"][day_key] = sorted(
            week_context["events_by_day"][day_key],
            key=lambda item: _coerce_event_datetime(item.get("start")) or datetime.max.replace(tzinfo=timezone.utc),
        )

    return day_context, week_context
