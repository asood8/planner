"""Review sessions before exams, spread over the days before instead of crammed into the night before.

An exam is a calendar event (Google or a feed) whose title says exam, midterm, final, quiz, or test, and that
doesn't look like something else ("Midterm review session", "Final project"). Each exam from tomorrow through
exam_prep.days_before gets a total amount of review: "~6h" in its title or description, else exam_minutes
(quiz_minutes for quizzes). The scheduler gets it as a candidate with two extras: day_cap, the day's share of
review (more costs extra but is allowed, so a day with no room can't leave review short), and target_days,
evenly spaced days ending the day before the exam that it aims the sessions at.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from core import timeutil
from core.estimates import format_minutes, parse_estimate
from core.settings import ExamPrep

EXAM_PREFIX = "exam:"
EXAM_RE = re.compile(r"\b(exams?|midterms?|finals?|quiz(?:zes)?|tests?)\b", re.IGNORECASE)
QUIZ_RE = re.compile(r"\bquiz", re.IGNORECASE)
NOT_EXAM_RE = re.compile(
    r"\b(review|prep|study|studying|practice|office hours?|tutor\w*|week|project|paper|presentation|report|essay|drive|cases?)\b",
    re.IGNORECASE,
)
MAX_KEY_TITLE = 120


def is_exam(title: str) -> bool:
    return bool(EXAM_RE.search(title)) and not NOT_EXAM_RE.search(title)


def exam_ref(title: str, day: date) -> str:
    """Stable suggestion ref for one exam: its title and date (events from Google have no id here)."""
    return f"{EXAM_PREFIX}{' '.join(title.casefold().split())[:MAX_KEY_TITLE]}|{day.isoformat()}"


def _round_up(minutes: int) -> int:
    return -(-minutes // 15) * 15


def exam_candidates(
    events: list[dict[str, Any]],
    today: date,
    settings: ExamPrep,
    accepted: dict[str, int],
    dismissed: set[str],
) -> list[dict[str, Any]]:
    """Scheduler candidates for upcoming exams, earliest first.

    `accepted` maps suggestion refs to review minutes already on the calendar; dismissed refs are skipped.
    """
    if settings.days_before <= 0:
        return []
    horizon = today + timedelta(days=settings.days_before)
    candidates: dict[str, dict[str, Any]] = {}
    for event in events:
        title = " ".join(str(event.get("title") or "").split())
        if event.get("source") == "ask_ai" or not is_exam(title):
            continue
        day = timeutil.local_day(event.get("start"))
        if day is None or not today < day <= horizon:
            continue
        ref = exam_ref(title, day)
        if ref in candidates or ref in dismissed:
            continue
        total = parse_estimate({"title": title, "notes": event.get("description")})
        if total is None:
            total = settings.quiz_minutes if QUIZ_RE.search(title) else settings.exam_minutes
        remaining = total - accepted.get(ref, 0)
        if remaining < 15:
            continue

        last_day = day - timedelta(days=1)
        window = (last_day - today).days + 1
        # A session a day, unless there are too few days left for the review to fit that way.
        day_cap = max(settings.session_minutes, _round_up(-(-remaining // window)))
        sessions = min(window, -(-remaining // day_cap))
        targets = sorted({last_day - timedelta(days=int(i * window / sessions)) for i in range(sessions)})
        candidates[ref] = {
            "key": ref,
            "kind": "exam",
            "task": {"title": title},
            "due": day,
            "last_day": last_day,
            "remaining": remaining,
            "day_cap": day_cap,
            "target_days": targets,
            "note": f"About {format_minutes(total)} of review in total, spread over the days before",
        }
    return sorted(candidates.values(), key=lambda candidate: (candidate["due"], candidate["task"]["title"]))
