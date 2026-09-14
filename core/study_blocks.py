"""Building blocks for study-session scheduling: free time, candidate tasks, and a simple greedy allocator.

core/scheduler.py places the sessions with an optimizer and falls back to allocate() here. How much time a
task needs comes from core/estimates.py, which also learns from how long finished tasks really took.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from core.estimates import Calibration, estimate_for, estimate_minutes  # noqa: F401 (estimate_minutes re-exported)
from core.normalizer import DEFAULT_WORKDAY_END, DEFAULT_WORKDAY_START, free_blocks_for_day, task_due_day, task_key
from core.settings import StudyBlocks

MIN_SESSION_MINUTES = 30
MIN_SLOT = timedelta(minutes=15)
BREAK = timedelta(minutes=15)


def _round_up(moment: datetime, minutes: int = 15) -> datetime:
    extra = timedelta(minutes=moment.minute % minutes, seconds=moment.second, microseconds=moment.microsecond)
    return moment + (timedelta(minutes=minutes) - extra) if extra else moment


def free_slots(
    events: list[dict[str, Any]],
    first_day: date,
    last_day: date,
    now: datetime,
    workday_start: int = DEFAULT_WORKDAY_START,
    workday_end: int = DEFAULT_WORKDAY_END,
) -> list[list[datetime]]:
    """Chronological, mutable [start, end] free slots from first_day through last_day, none before `now`."""
    earliest = _round_up(now)
    slots = []
    day = first_day
    while day <= last_day:
        for start, end in free_blocks_for_day(events, day, workday_start, workday_end):
            start = max(start, earliest)
            if end - start >= MIN_SLOT:
                slots.append([start, end])
        day += timedelta(days=1)
    return slots


def allocate(
    slots: list[list[datetime]],
    minutes: int,
    last_day: date,
    max_session_minutes: int,
    min_session_minutes: int = MIN_SESSION_MINUTES,
) -> list[tuple[datetime, datetime]]:
    """Take up to `minutes` from the earliest slots on or before last_day, consuming them (slots are mutated)."""
    remaining = timedelta(minutes=minutes)
    max_session = timedelta(minutes=max_session_minutes)
    min_session = timedelta(minutes=min(min_session_minutes, minutes))
    sessions = []
    for slot in slots:
        if slot[0].date() > last_day:
            break
        while remaining > timedelta(0) and slot[1] - slot[0] >= min_session:
            length = min(remaining, max_session, slot[1] - slot[0])
            sessions.append((slot[0], slot[0] + length))
            slot[0] = slot[0] + length + BREAK
            remaining -= length
        if remaining <= timedelta(0):
            break
    return sessions


def study_candidates(
    tasks: list[dict[str, Any]],
    today: date,
    settings: StudyBlocks,
    accepted_minutes: dict[str, int],
    dismissed_keys: set[str],
    calibration: Calibration | None = None,
) -> list[dict[str, Any]]:
    """Tasks due within settings.days_ahead that still need time, earliest deadline first."""
    horizon = today + timedelta(days=settings.days_ahead)
    candidates = []
    for task in tasks:
        due_day = task_due_day(task)
        if due_day is None or due_day > horizon:
            continue
        key = task_key(task)
        if key in dismissed_keys:
            continue
        estimate = estimate_for(task, settings, calibration)
        remaining = estimate.minutes - accepted_minutes.get(key, 0)
        if remaining < 15:
            continue
        candidates.append(
            {
                "task": task,
                "key": key,
                "due": due_day,
                # Overdue work still gets a slot, today or tomorrow.
                "last_day": due_day if due_day >= today else today + timedelta(days=1),
                "estimate": estimate.minutes,
                "estimate_info": estimate,
                "remaining": remaining,
            }
        )
    return sorted(candidates, key=lambda candidate: (candidate["due"], str(candidate["task"].get("title", ""))))
