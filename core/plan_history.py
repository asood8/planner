"""Generated plans saved in data/plan_history.json, so the latest survives restarts and old ones can be reviewed."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from core import timeutil
from core.local_store import data_path, locked, read_json, write_json_atomic

FILE_NAME = "plan_history.json"
MAX_PLANS = 60
SUMMARY_FIELDS = ("id", "date", "created", "mode", "model")


def _read() -> list[dict[str, Any]]:
    data = read_json(data_path(FILE_NAME), [])
    return [entry for entry in data if isinstance(entry, dict) and entry.get("text")] if isinstance(data, list) else []


def save_plan(text: str, mode: str, model: str) -> dict[str, Any]:
    now = timeutil.now()
    entry = {
        "id": uuid.uuid4().hex[:12],
        "date": now.date().isoformat(),
        "created": now.isoformat(timespec="seconds"),
        "mode": mode,
        "model": model,
        "text": text,
    }
    with locked(FILE_NAME):
        write_json_atomic(data_path(FILE_NAME), (_read() + [entry])[-MAX_PLANS:])
    return entry


def latest_plan_for(day: date) -> dict[str, Any] | None:
    matches = [entry for entry in _read() if entry.get("date") == day.isoformat()]
    return matches[-1] if matches else None


def list_plans(limit: int = 30) -> list[dict[str, Any]]:
    """Newest first, without the plan text."""
    return [{key: entry.get(key) for key in SUMMARY_FIELDS} for entry in reversed(_read())][:limit]


def get_plan(plan_id: str) -> dict[str, Any] | None:
    return next((entry for entry in _read() if entry.get("id") == plan_id), None)
