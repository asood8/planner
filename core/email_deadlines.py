"""Deadlines and reply requests pulled out of unread emails by the local model, cached per email id.

Each email is analyzed once. Emails without deadline-ish wording are cached as empty without calling
the model, which keeps newsletters away from it and keeps scans fast. Only one scan runs at a time,
across processes; results are merged into the cache under its lock, so nothing another process
wrote is lost.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from core import timeutil
from core.local_store import StoreBusy, data_path, locked, read_json, write_json_atomic
from core.saved_events import parse_clock

FILE_NAME = "email_deadlines.json"
SCAN_LOCK = "email_scan"
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "email_deadlines_prompt.txt"
BATCH_SIZE = 8
MAX_CACHED = 500
LOOKAHEAD_DAYS = 90
MAX_TITLE_LENGTH = 80
ACTIONABLE_RE = re.compile(
    r"\b(due|deadline|submit|submission|tomorrow|tonight|today|asap|rsvp|reply|respond|let me know|"
    r"confirm|reminder|exam|quiz|midterm|final|interview|application|apply|register|registration|"
    r"expires?|eod|by (?:mon|tue|wed|thu|fri|sat|sun)\w*|\d{1,2}/\d{1,2})\b",
    re.IGNORECASE,
)
SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "string"},
                    "kind": {"type": "string", "enum": ["deadline", "reply"]},
                    "title": {"type": "string"},
                    "date": {"type": "string"},
                    "time": {"type": "string"},
                },
                "required": ["email_id", "kind", "title"],
            },
        }
    },
    "required": ["items"],
}

logger = logging.getLogger(__name__)


def _load_cache() -> dict[str, Any]:
    data = read_json(data_path(FILE_NAME), {})
    return data if isinstance(data, dict) else {}


def _store(entries: dict[str, Any]) -> None:
    """Merge scan results into the cache, re-reading it under the lock so other writers aren't lost."""
    if not entries:
        return
    with locked(FILE_NAME):
        cache = _load_cache()
        cache.update(entries)
        if len(cache) > MAX_CACHED:
            def scanned(item):
                return str(item[1].get("scanned", "")) if isinstance(item[1], dict) else ""
            cache = dict(sorted(cache.items(), key=scanned, reverse=True)[:MAX_CACHED])
        write_json_atomic(data_path(FILE_NAME), cache)


def looks_actionable(email: dict[str, Any]) -> bool:
    return bool(ACTIONABLE_RE.search(f"{email.get('subject', '')} {email.get('snippet', '')}"))


def _email_line(email: dict[str, Any]) -> str:
    received = email.get("date")
    received_text = timeutil.to_local(received).strftime("%Y-%m-%d (%a)") if isinstance(received, datetime) else "unknown"
    snippet = " ".join(str(email.get("snippet") or "").split())
    return (
        f"[{email['id']}] From: {email.get('sender', '')} | Received: {received_text} | "
        f"Subject: {email.get('subject', '')} | Snippet: {snippet}"
    )


def _clean_item(raw: Any, allowed_ids, today: date) -> tuple[str, dict[str, str]] | None:
    if not isinstance(raw, dict):
        return None
    email_id = str(raw.get("email_id", "")).strip().strip("[]")
    kind = str(raw.get("kind", "")).strip().lower()
    title = " ".join(str(raw.get("title") or "").split())[:MAX_TITLE_LENGTH]
    if email_id not in allowed_ids or kind not in ("deadline", "reply") or not title:
        return None

    item = {"kind": kind, "title": title}
    if kind == "deadline":
        try:
            day = date.fromisoformat(str(raw.get("date", "")).strip())
        except ValueError:
            return None
        if not today - timedelta(days=1) <= day <= today + timedelta(days=LOOKAHEAD_DAYS):
            return None
        item["date"] = day.isoformat()
        clock = parse_clock(raw.get("time")) if raw.get("time") else None
        if clock is not None:
            item["time"] = clock.strftime("%H:%M")
    return email_id, item


def _scan(emails: list[dict[str, Any]], client, model: str, today: date) -> int:
    cache = _load_cache()
    new = [email for email in emails if email.get("id") and email["id"] not in cache]
    if not new:
        return 0

    stamp = timeutil.now().isoformat(timespec="seconds")
    candidates = [email for email in new if looks_actionable(email)]
    candidate_ids = {email["id"] for email in candidates}
    _store({email["id"]: {"items": [], "scanned": stamp} for email in new if email["id"] not in candidate_ids})

    instructions = PROMPT_PATH.read_text(encoding="utf-8").strip()
    for start in range(0, len(candidates), BATCH_SIZE):
        chunk = candidates[start:start + BATCH_SIZE]
        prompt = "\n\n".join([
            instructions,
            f"Today's date is {today.isoformat()} ({today.strftime('%A')}).",
            "EMAILS:\n" + "\n".join(_email_line(email) for email in chunk),
        ])
        result = client.generate_json(prompt, SCHEMA, model=model)
        found: dict[str, list[dict[str, str]]] = {email["id"]: [] for email in chunk}
        raw_items = result.get("items") if isinstance(result, dict) else None
        for raw in raw_items if isinstance(raw_items, list) else []:
            cleaned = _clean_item(raw, found, today)
            if cleaned is not None:
                found[cleaned[0]].append(cleaned[1])
        _store({email_id: {"items": items, "scanned": stamp} for email_id, items in found.items()})

    logger.info("Checked %d unread emails for deadlines.", len(candidates))
    return len(candidates)


def scan_emails(emails: list[dict[str, Any]], client, model: str, today: date) -> int | None:
    """Analyze unread emails not seen before. Returns how many went to the model, or None if another
    scan (in this process or another) is already running.

    `client` needs generate_json(prompt, schema, model=...). A RuntimeError from it (Ollama down)
    propagates; results saved before the failure are kept.
    """
    try:
        with locked(SCAN_LOCK, timeout=0):
            return _scan(emails, client, model, today)
    except StoreBusy as exc:
        if exc.name != SCAN_LOCK:
            raise
        return None


def cached_items(emails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extracted items for the given (still unread) emails, each with a stable ref and its email's sender/subject."""
    cache = _load_cache()
    items = []
    for email in emails:
        entry = cache.get(email.get("id") or "")
        if not isinstance(entry, dict):
            continue
        for index, item in enumerate(entry.get("items") or []):
            if not isinstance(item, dict) or item.get("kind") not in ("deadline", "reply"):
                continue
            items.append(
                {
                    **item,
                    "ref": f"{item['kind']}:{email['id']}:{index}",
                    "email_id": email["id"],
                    "sender": email.get("sender", ""),
                    "subject": email.get("subject", ""),
                }
            )
    return items
