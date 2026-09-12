"""Fetch + normalize steps shared by plan.py (CLI) and server.py (web app)."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from core.normalizer import normalize
from fetch.calendar import get_events
from fetch.gmail import get_unread_emails
from fetch.tasks import get_tasks

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _safe_fetch(future, label: str, default):
    """Resolve a future; on failure, warn and fall back instead of crashing the whole run."""
    try:
        return future.result(), True
    except Exception as exc:
        print(f"Warning: {label} fetch failed: {exc}")
        return default, False


def fetch_sources(creds, config: dict[str, Any]) -> tuple[list, Any, list, dict[str, bool | None]]:
    """Fetch calendar events, tasks, and unread Gmail in parallel.

    Returns (events, tasks, emails, status). status maps calendar_ok/tasks_ok/gmail_ok to
    True (fetched), False (fetch failed), or None (not fetched because Gmail is disabled).
    """
    with ThreadPoolExecutor(max_workers=3) as executor:
        events_future = executor.submit(get_events, creds, config.get("calendar_days_ahead", 14))
        tasks_future = executor.submit(get_tasks, creds)
        emails_future = (
            executor.submit(get_unread_emails, creds, config.get("max_emails", 20))
            if config.get("include_gmail", True) else None
        )

        events, calendar_ok = _safe_fetch(events_future, "calendar", [])
        tasks, tasks_ok = _safe_fetch(tasks_future, "tasks", [])
        if emails_future is not None:
            emails, gmail_ok = _safe_fetch(emails_future, "gmail", [])
        else:
            emails, gmail_ok = [], None

    return events, tasks, emails, {"calendar_ok": calendar_ok, "tasks_ok": tasks_ok, "gmail_ok": gmail_ok}


def normalize_sources(events: list, tasks: Any, emails: list, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """normalize() with the workday hours from config.json's user_profile."""
    profile = config.get("user_profile", {})
    workday = {key: int(profile[key]) for key in ("workday_start", "workday_end") if key in profile}
    return normalize(events, tasks, emails, **workday)


def script_safe_json(value: Any) -> str:
    """JSON that can't close the surrounding <script> tag (event titles come from other people's invites)."""
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
