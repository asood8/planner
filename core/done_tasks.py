"""Tasks marked done on the dashboard, kept in data/done_tasks.json.

Google Tasks stays read-only, so marking a task done here only hides it in the planner: from the
calendar, the plan context, and study suggestions. Canvas/iCal deadlines can be marked done the same way.
Entries also keep the time measurements core/estimates.py learns from: the task's list, the estimate
the planner used, and how long it actually took.
"""
from __future__ import annotations

from typing import Any

from core import timeutil
from core.local_store import data_path, locked, read_json, write_json_atomic
from core.normalizer import task_key

FILE_NAME = "done_tasks.json"
MAX_ENTRIES = 500
MEASUREMENT_FIELDS = ("list", "estimate", "from_task", "actual")


def _read() -> list[dict[str, Any]]:
    data = read_json(data_path(FILE_NAME), [])
    return [entry for entry in data if isinstance(entry, dict) and entry.get("key")] if isinstance(data, list) else []


def load_done() -> list[dict[str, Any]]:
    """Entries {key, title, done_at, [list, estimate, from_task, actual]}, newest first."""
    return list(reversed(_read()))


def mark_done(key: str, title: str, measurement: dict[str, Any] | None = None) -> None:
    key = str(key).strip()
    if not key:
        raise ValueError("missing task key")
    entry = {"key": key, "title": str(title or "Untitled task")[:200], "done_at": timeutil.today().isoformat()}
    entry.update({name: value for name, value in (measurement or {}).items() if name in MEASUREMENT_FIELDS and value is not None})
    with locked(FILE_NAME):
        entries = [existing for existing in _read() if existing["key"] != key]
        entries.append(entry)
        write_json_atomic(data_path(FILE_NAME), entries[-MAX_ENTRIES:])


def record_actual(key: str, minutes: int) -> bool:
    """Set how long a finished task really took, as the user reported. False if it isn't in the done list."""
    with locked(FILE_NAME):
        entries = _read()
        for entry in entries:
            if entry["key"] == key:
                entry["actual"] = int(minutes)
                write_json_atomic(data_path(FILE_NAME), entries)
                return True
        return False


def undo_done(key: str) -> bool:
    with locked(FILE_NAME):
        entries = _read()
        kept = [entry for entry in entries if entry["key"] != key]
        if len(kept) == len(entries):
            return False
        write_json_atomic(data_path(FILE_NAME), kept)
        return True


def without_done(tasks: Any) -> Any:
    """Drop done tasks from a task list or Google's grouped {bucket: [tasks]} dict."""
    keys = {entry["key"] for entry in _read()}
    if not keys:
        return tasks

    def keep(task: Any) -> bool:
        return not (isinstance(task, dict) and task_key(task) in keys)

    if isinstance(tasks, dict):
        return {bucket: [task for task in items if keep(task)] if isinstance(items, list) else items for bucket, items in tasks.items()}
    if isinstance(tasks, list):
        return [task for task in tasks if keep(task)]
    return tasks
