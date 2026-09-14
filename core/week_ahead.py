"""A look at the next seven days, so a crunch shows up while there's still time to do something about it.

Two kinds of warning:
- A crunch: the work due by some day after the study-suggestion window (study_blocks.days_ahead) needs more
  time than the free study time left before then, within the daily study limit. Nearer deadlines already
  get work sessions, and their own "not enough free time" notices.
- A packed day: at least PACKED_MINUTES of timed events inside the workday.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from core import timeutil
from core.estimates import Calibration, estimate_for, format_minutes
from core.normalizer import task_due_day, task_key
from core.settings import Settings
from core.study_blocks import free_slots

WEEK_DAYS = 7
PACKED_MINUTES = 8 * 60
MAX_PACKED_DAYS = 3


def _minutes(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() // 60)


def _bound(day: date, hour: int) -> datetime:
    """Local time at `hour` on `day`; hour 24 means the next midnight."""
    return timeutil.at(day + timedelta(days=hour // 24), time(hour % 24))


def busy_minutes(events: list[dict[str, Any]], day: date, workday_start: int, workday_end: int) -> int:
    """Minutes of the workday on `day` covered by timed events, counting overlaps once."""
    first, last = _bound(day, workday_start), _bound(day, workday_end)
    spans = []
    for event in events:
        start, end = event.get("start"), event.get("end")
        if event.get("all_day") or not isinstance(start, datetime) or not isinstance(end, datetime):
            continue
        start, end = max(timeutil.to_local(start), first), min(timeutil.to_local(end), last)
        if start < end:
            spans.append((start, end))
    total, covered_until = 0, first
    for start, end in sorted(spans):
        start = max(start, covered_until)
        if end > start:
            total += _minutes(start, end)
            covered_until = end
    return total


def week_warnings(
    events: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    exams: list[dict[str, Any]],
    today: date,
    now: datetime,
    settings: Settings,
    calibration: Calibration | None,
    accepted: dict[str, int],
    day_loads: dict[date, int],
) -> list[str]:
    """Plain-language warnings for the sidebar and the plan prompt.

    `exams` are exam_prep candidates; `accepted` maps task keys to study minutes already on the calendar;
    `day_loads` maps days to study minutes already added on them.
    """
    profile, study = settings.user_profile, settings.study_blocks
    days = [today + timedelta(days=offset) for offset in range(WEEK_DAYS)]
    free = {day: 0 for day in days}
    for start, end in free_slots(events, today, days[-1], now, profile.workday_start, profile.workday_end):
        free[start.date()] = free.get(start.date(), 0) + _minutes(start, end)
    room = {day: max(0, min(free[day], study.max_minutes_per_day - day_loads.get(day, 0))) for day in days}

    work: list[tuple[date, int]] = []  # (last day to do it, minutes still needed)
    for task in tasks:
        due = task_due_day(task)
        if due is None or due > days[-1]:
            continue
        needed = estimate_for(task, study, calibration).minutes - accepted.get(task_key(task), 0)
        if needed >= 15:
            work.append((max(due, today), needed))
    work += [(exam["last_day"], exam["remaining"]) for exam in exams if exam["last_day"] <= days[-1]]

    warnings = []
    window_end = today + timedelta(days=study.days_ahead)
    for day in days:
        if day <= window_end or not any(last == day for last, _ in work):
            continue
        needed = [minutes for last, minutes in work if last <= day]
        available = sum(room[other] for other in days if other <= day)
        if sum(needed) > available:
            things = f"{len(needed)} thing{'s' if len(needed) != 1 else ''}"
            warnings.append(
                f"By {day:%a %b %d}: about {format_minutes(sum(needed))} of work is due ({things}), "
                f"but only about {format_minutes(available)} of study time is left before then."
            )
            break

    packed = 0
    for day in days[1:]:  # today is already in front of you
        busy = busy_minutes(events, day, profile.workday_start, profile.workday_end)
        if busy >= PACKED_MINUTES and packed < MAX_PACKED_DAYS:
            warnings.append(f"{day:%a %b %d} is packed: {format_minutes(busy)} of events and {format_minutes(free[day])} free.")
            packed += 1
    return warnings
