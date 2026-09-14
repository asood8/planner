"""Fetch, normalize, and prompt steps shared by plan.py (CLI) and server.py (web app)."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from core.context_builder import build_context
from core.done_tasks import without_done
from core.logs import log_failure
from core.normalizer import normalize
from core.prompt_builder import PLAN_REQUESTS, build_prompt
from core.saved_events import load_saved_events, to_calendar_events
from core.settings import Settings
from core.suggestions import build_suggestions
from fetch.calendar import get_events
from fetch.gmail import get_unread_emails
from fetch.ical import fetch_feeds
from fetch.tasks import get_tasks

logger = logging.getLogger(__name__)


def _safe_fetch(future, label: str, default):
    """Resolve a future; on failure, warn and fall back instead of crashing the whole run."""
    try:
        return future.result(), True
    except Exception as exc:
        log_failure(logger, f"{label} fetch failed", exc)
        return default, False


def _with_deadlines(tasks: Any, deadlines: list[dict[str, Any]]) -> Any:
    """Add feed deadlines to Google's grouped task dict (or to a plain list after a failed task fetch)."""
    if not deadlines:
        return tasks
    if isinstance(tasks, dict):
        return {**tasks, "has_due_date": list(tasks.get("has_due_date", [])) + deadlines}
    return list(tasks or []) + deadlines


def _task_count(tasks: Any) -> int:
    if isinstance(tasks, dict):
        return sum(len(items) for items in tasks.values() if isinstance(items, list))
    return len(tasks or [])


def fetch_sources(creds, settings: Settings) -> tuple[list, Any, list, dict[str, bool | None]]:
    """Fetch calendar events, tasks, unread Gmail, and iCal feeds in parallel.

    Returns (events, tasks, emails, status). Feed events are merged into events and feed deadlines
    into tasks. status maps calendar_ok/tasks_ok/gmail_ok/feeds_ok to True (fetched), False (failed),
    or None (not fetched: Gmail disabled, or no feeds configured).
    """
    with ThreadPoolExecutor(max_workers=4) as executor:
        events_future = executor.submit(get_events, creds, settings.calendar_days_ahead)
        tasks_future = executor.submit(get_tasks, creds)
        emails_future = executor.submit(get_unread_emails, creds, settings.max_emails) if settings.include_gmail else None
        feeds_future = executor.submit(fetch_feeds, settings)

        events, calendar_ok = _safe_fetch(events_future, "Calendar", [])
        tasks, tasks_ok = _safe_fetch(tasks_future, "Tasks", [])
        if emails_future is not None:
            emails, gmail_ok = _safe_fetch(emails_future, "Gmail", [])
        else:
            emails, gmail_ok = [], None
        try:
            feed_events, feed_deadlines, feeds_ok = feeds_future.result()
        except Exception as exc:
            log_failure(logger, "Calendar feeds failed", exc)
            feed_events, feed_deadlines, feeds_ok = [], [], False

    events = list(events) + feed_events
    tasks = _with_deadlines(tasks, feed_deadlines)
    status = {"calendar_ok": calendar_ok, "tasks_ok": tasks_ok, "gmail_ok": gmail_ok, "feeds_ok": feeds_ok}
    logger.info("Fetched %d events, %d tasks, and %d unread emails.", len(events), _task_count(tasks), len(emails))
    return events, tasks, emails, status


def with_saved_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Google events plus locally saved Ask AI events, so both count as commitments everywhere."""
    return list(events) + to_calendar_events(load_saved_events())


def normalize_sources(events: list, tasks: Any, emails: list, settings: Settings) -> tuple[dict[str, Any], dict[str, Any]]:
    """normalize() with the configured workday hours."""
    profile = settings.user_profile
    return normalize(events, tasks, emails, profile.workday_start, profile.workday_end)


def prepare_contexts(
    events: list, tasks: Any, emails: list, settings: Settings
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, list]]:
    """Drop tasks marked done, merge saved events, normalize, and build suggestions.

    Returns (events, day_context, week_context, suggestions).
    """
    tasks = without_done(tasks)
    events = with_saved_events(events)
    day_context, week_context = normalize_sources(events, tasks, emails, settings)
    suggestions = build_suggestions(events, day_context, week_context, emails, settings)
    return events, day_context, week_context, suggestions


def build_plan_prompt(
    day_context: dict[str, Any],
    week_context: dict[str, Any],
    settings: Settings,
    mode: str = "all",
    note: str = "",
    suggestions: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Planner prompt for a mode (daily/weekly/all). Returns (prompt, context_text)."""
    context_text = build_context(day_context, week_context, max_emails=settings.max_emails, suggestions=suggestions)
    request = PLAN_REQUESTS.get(mode, PLAN_REQUESTS["all"])
    if note.strip():
        request += f"\n\nStanding notes from the user (take them into account):\n{note.strip()}"
    return build_prompt(day_context, week_context, request, context_text, settings), context_text


def script_safe_json(value: Any) -> str:
    """JSON that can't close the surrounding <script> tag (event titles come from other people's invites)."""
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
