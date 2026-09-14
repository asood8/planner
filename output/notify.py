"""Windows toast notification for the scheduled morning plan (plan.py --notify).

Uses PowerShell's built-in access to the Windows notification API, so there's nothing to install.
"""
from __future__ import annotations

import base64
import os
import socket
import subprocess
import sys
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape, quoteattr

# Windows only shows toasts from a registered app id; PowerShell's always exists.
POWERSHELL_APP_ID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"
# The XML and app id arrive through environment variables, so nothing needs quoting inside the script.
TOAST_SCRIPT = """
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml($env:PLANNER_TOAST_XML)
$toast = New-Object Windows.UI.Notifications.ToastNotification $doc
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:PLANNER_TOAST_APP_ID).Show($toast)
"""


def toast_xml(title: str, lines: list[str], open_url: str | None = None) -> str:
    """ToastGeneric XML: a bold title plus up to two lines. Clicking the toast opens open_url."""
    texts = "".join(f"<text>{escape(text)}</text>" for text in [title, *lines][:3])
    launch = f' activationType="protocol" launch={quoteattr(open_url)}' if open_url else ""
    return f'<toast{launch}><visual><binding template="ToastGeneric">{texts}</binding></visual></toast>'


def send_toast(title: str, lines: list[str], open_url: str | None = None) -> bool:
    """Show a Windows toast. Returns False (doing nothing) off Windows or if PowerShell fails."""
    if sys.platform != "win32":
        return False
    env = {**os.environ, "PLANNER_TOAST_XML": toast_xml(title, lines, open_url), "PLANNER_TOAST_APP_ID": POWERSHELL_APP_ID}
    encoded = base64.b64encode(TOAST_SCRIPT.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            env=env,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def server_is_running(port: int = 5000) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _sessions(count: int) -> str:
    return f"{count} session{'s' if count != 1 else ''}"


def review_summary(review: dict[str, Any], checkins: int, now: datetime) -> tuple[str, list[str]]:
    """Toast title and two lines for the evening review (core/review.py): what's left, then how tomorrow starts."""
    parts = []
    if checkins:
        parts.append(f"{_sessions(checkins)} to check in")
    still_open = len(review.get("open", []))
    if still_open:
        parts.append(f"{still_open} task{'s' if still_open != 1 else ''} still open")
    finished = len(review.get("finished", []))
    if finished:
        parts.append(f"{finished} done today")
    return f"Wrapping up {now:%A}", [" · ".join(parts) or "All caught up", review.get("tomorrow", "")]


def morning_summary(
    calendar_entries: list[dict[str, Any]],
    day_context: dict[str, Any],
    notices: list[str],
    now: datetime,
    plan_ok: bool,
    checkins: int = 0,
) -> tuple[str, list[str]]:
    """Toast title and two lines: what's due (and past sessions to check in), then the next few timed items today."""
    due_today = len(day_context.get("tasks_due_today", []))
    overdue = len(day_context.get("tasks_overdue", []))
    counts = [text for count, text in ((due_today, f"{due_today} due today"), (overdue, f"{overdue} overdue")) if count]
    first = " · ".join(counts) or "Nothing due today"
    if notices:
        first += " · not enough time for everything"
    if checkins:
        first += f" · {_sessions(checkins)} to check in"

    # FullCalendar entries use local "YYYY-MM-DDTHH:MM:SS" strings, which compare chronologically.
    today_prefix = now.strftime("%Y-%m-%dT")
    now_text = now.strftime("%Y-%m-%dT%H:%M:%S")
    upcoming = sorted(
        (
            entry for entry in calendar_entries
            if not entry.get("allDay") and entry.get("display") != "background"
            and str(entry.get("start", "")).startswith(today_prefix) and entry["start"] >= now_text
        ),
        key=lambda entry: entry["start"],
    )
    if upcoming:
        second = " · ".join(
            f"{datetime.fromisoformat(entry['start']).strftime('%I:%M %p').lstrip('0')} {entry['title']}"
            for entry in upcoming[:3]
        )
    elif plan_ok:
        second = "Nothing else scheduled today"
    else:
        second = "The plan couldn't be generated (is Ollama running?)"
    return f"Your plan for {now:%A}", [first, second]
