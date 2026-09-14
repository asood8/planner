"""Suggested calendar items the user can accept or dismiss: work sessions before task deadlines, review
sessions before exams, and deadlines / reply requests found in unread emails.

A suggestion is {ref, kind: study|exam|deadline|reply, title, date, start, end, all_day, details}. Refs are
stable across reloads, so dismissing one (data/dismissed_suggestions.json) or accepting it (a saved
event carrying the ref) keeps it from coming back. Dismissing a study ref drops the whole task, and an exam
ref the whole exam. Sessions are placed by core/scheduler.py, with estimates learned by core/estimates.py.
An accepted session checked in as skipped no longer counts, so its time is suggested again.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from core import timeutil
from core.done_tasks import load_done
from core.email_deadlines import cached_items
from core.estimates import describe, learn
from core.exam_prep import EXAM_PREFIX, exam_candidates
from core.local_store import data_path, locked, read_json, write_json_atomic
from core.scheduler import remaining_slots, schedule
from core.settings import Settings
from core.study_blocks import allocate, free_slots, study_candidates
from core.week_ahead import week_warnings

DISMISSED_FILE = "dismissed_suggestions.json"
MAX_DISMISSED = 1000
REPLY_MINUTES = 15
STUDY_PREFIX = "study:"
SESSION_PREFIXES = (STUDY_PREFIX, EXAM_PREFIX)


def load_dismissed() -> set[str]:
    data = read_json(data_path(DISMISSED_FILE), [])
    return {str(ref) for ref in data} if isinstance(data, list) else set()


def dismiss(ref: str) -> None:
    ref = str(ref).strip()
    if not ref:
        return
    with locked(DISMISSED_FILE):
        data = read_json(data_path(DISMISSED_FILE), [])
        refs = [str(existing) for existing in data] if isinstance(data, list) else []
        if ref not in refs:
            refs.append(ref)
        write_json_atomic(data_path(DISMISSED_FILE), refs[-MAX_DISMISSED:])


def _minutes(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() // 60)


def _timed_item(ref: str, kind: str, title: str, start: datetime, end: datetime, details: str) -> dict[str, Any]:
    return {
        "ref": ref,
        "kind": kind,
        "title": title,
        "date": start.date().isoformat(),
        "start": start.strftime("%H:%M"),
        "end": end.strftime("%H:%M"),
        "all_day": False,
        "details": details,
    }


def _details(reasons: tuple[str, ...], note: str) -> str:
    return ". ".join([*reasons, note]) + "."


def _accepted(events: list[dict[str, Any]]) -> tuple[set[str], dict[str, int], dict[date, int]]:
    """(refs of every accepted suggestion, minutes per work-session ref, work-session minutes per day).

    Sessions checked in as skipped are left out of the minutes, so their time goes back into the suggestions.
    """
    refs: set[str] = set()
    minutes_by_ref: dict[str, int] = {}
    day_loads: dict[date, int] = {}
    for event in events:
        ref = event.get("ref")
        if event.get("source") != "ask_ai" or not ref:
            continue
        refs.add(ref)
        start, end = event.get("start"), event.get("end")
        if not ref.startswith(SESSION_PREFIXES) or event.get("status") == "skipped":
            continue
        if isinstance(start, datetime) and isinstance(end, datetime):
            minutes = _minutes(start, end)
            minutes_by_ref[ref] = minutes_by_ref.get(ref, 0) + minutes
            day = timeutil.local_day(start)
            day_loads[day] = day_loads.get(day, 0) + minutes
    return refs, minutes_by_ref, day_loads


def build_suggestions(
    events: list[dict[str, Any]],
    day_context: dict[str, Any],
    week_context: dict[str, Any],
    emails: list[dict[str, Any]],
    settings: Settings,
    now: datetime | None = None,
) -> dict[str, list]:
    """Returns {"items": [suggestion], "notices": [str], "estimates": [str], "week": [str]}.

    `events` must include saved (accepted) events. "estimates" describes what's been learned about task
    length; "week" warns about crunches and packed days in the next seven days (core/week_ahead.py).
    """
    now = now or timeutil.now()
    today = now.date()
    dismissed = load_dismissed()
    accepted_refs, accepted_minutes, day_loads = _accepted(events)

    profile = settings.user_profile
    study = settings.study_blocks
    calibration = learn(load_done()) if study.learn_estimates else None
    tasks = (
        day_context.get("tasks_overdue", [])
        + day_context.get("tasks_due_today", [])
        + week_context.get("tasks_this_week", [])
        + week_context.get("tasks_later", [])
    )
    dismissed_keys = {ref[len(STUDY_PREFIX):] for ref in dismissed if ref.startswith(STUDY_PREFIX)}
    study_minutes = {
        ref[len(STUDY_PREFIX):]: minutes for ref, minutes in accepted_minutes.items() if ref.startswith(STUDY_PREFIX)
    }
    exams = exam_candidates(events, today, settings.exam_prep, accepted_minutes, dismissed)
    candidates = study_candidates(tasks, today, study, study_minutes, dismissed_keys, calibration) + exams
    candidates.sort(key=lambda candidate: (candidate["due"], str(candidate["task"].get("title", ""))))
    email_items = [item for item in cached_items(emails) if item["ref"] not in dismissed | accepted_refs]

    last_day = max([candidate["last_day"] for candidate in candidates] + [today + timedelta(days=1)])
    slots = free_slots(events, today, last_day, now, profile.workday_start, profile.workday_end)
    plan = schedule(candidates, slots, study, today, day_loads)

    items: list[dict[str, Any]] = []
    notices: list[str] = []
    by_key = {candidate["key"]: candidate for candidate in candidates}
    for session in plan.sessions:
        candidate = by_key[session.key]
        title = str(candidate["task"].get("title", "Untitled task"))
        if candidate.get("kind") == "exam":
            details = _details(session.reasons, candidate["note"])
            items.append(_timed_item(candidate["key"], "exam", f"Review for: {title}", session.start, session.end, details))
        else:
            details = _details(session.reasons, candidate["estimate_info"].note())
            items.append(_timed_item(f"{STUDY_PREFIX}{session.key}", "study", f"Work on: {title}", session.start, session.end, details))
    for candidate in candidates:
        short = plan.short_minutes.get(candidate["key"], 0)
        if short >= 15:
            title = str(candidate["task"].get("title", "Untitled task"))
            what = f"to review for “{title}”" if candidate.get("kind") == "exam" else f"for “{title}”"
            notices.append(f"Not enough free time before {candidate['due']:%a %b %d} {what} ({short} min short).")

    reply_slots = remaining_slots(slots, plan.sessions)
    for item in email_items:
        source = f"From {item['sender'] or 'unknown sender'}: {item['subject'] or '(no subject)'}"
        if item["kind"] == "deadline" and item.get("date"):
            when = f" ({timeutil.twelve_hour(item['time'])})" if item.get("time") else ""
            items.append({
                "ref": item["ref"],
                "kind": "deadline",
                "title": f"Due: {item['title']}{when}",
                "date": item["date"],
                "start": None,
                "end": None,
                "all_day": True,
                "details": source,
            })
        elif item["kind"] == "reply":
            sessions = allocate(reply_slots, REPLY_MINUTES, today + timedelta(days=1), REPLY_MINUTES, REPLY_MINUTES)
            if sessions:
                start, end = sessions[0]
                items.append(_timed_item(item["ref"], "reply", f"Reply: {item['title']}", start, end, source))

    week = week_warnings(events, tasks, exams, today, now, settings, calibration, study_minutes, day_loads)
    return {"items": items, "notices": notices, "estimates": describe(calibration) if calibration else [], "week": week}
