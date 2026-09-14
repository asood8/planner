"""Regenerate the README screenshots from made-up sample data.

Runs the web app in this process with Google, config.json, and data/ swapped for a fictional student's week
(nothing real is read, and nothing is sent anywhere except the page's usual font and FullCalendar downloads),
then photographs it with headless Chrome or Edge:

    .venv\\Scripts\\python.exe docs\\make_screenshots.py

It writes docs/screenshots/week.png (desktop, as of 7:30 AM today) and docs/screenshots/phone.png (a phone-width
screen at 8:30 PM, when the end-of-day review shows). The server's clock is pinned so the layout doesn't depend on
when this runs; the browser's own clock only moves the red "now" line.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
import threading
import time as clock
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from core import local_store, timeutil  # noqa: E402
from core.exam_prep import exam_ref  # noqa: E402
from core.local_store import data_path, write_json_atomic  # noqa: E402
from core.saved_events import add_saved_events, set_session_status  # noqa: E402
from core.settings import Settings  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]

SAMPLE_PLAN = """## Today

The reading response is due tonight, so it goes first. Midterm review starts today in short sessions instead of one long cram on Thursday night.

- **8:00 AM - 9:00 AM** Reading response for Econ
- **11:15 AM - 12:45 PM** Problem set 4, questions 1 to 4
- **4:00 PM - 4:45 PM** Walk and a snack before the gym
- **7:30 PM - 8:00 PM** Look over tomorrow's lab handout

## Watch out for

- Saturday is taken up by the hackathon, so aim to finish the lab report by Friday.
- Thursday's career fair overlaps Econ recitation. Decide which one you're going to.
"""

TODAY = timeutil.today()
SUNDAY = TODAY - timedelta(days=(TODAY.weekday() + 1) % 7)  # the calendar's week starts on Sunday


def _day(offset: int) -> date:
    return SUNDAY + timedelta(days=offset)


def _at(offset: int, hour: int, minute: int = 0) -> datetime:
    return timeutil.at(_day(offset), time(hour, minute))


def _event(title: str, offset: int, start: tuple[int, int], end: tuple[int, int]) -> dict:
    return {"title": title, "start": _at(offset, *start), "end": _at(offset, *end), "all_day": False,
            "description": "", "location": "", "recurring": False}


def _task(task_id: str, title: str, offset: int | None, task_list: str, **extra) -> dict:
    due = datetime.combine(_day(offset), time.min, tzinfo=timezone.utc) if offset is not None else None
    return {"id": task_id, "title": title, "notes": "", "due": due, "list": task_list, **extra}


EVENTS = [
    _event("Brunch with roommates", 0, (11, 0), (12, 30)),
    _event("CS 201 Lecture", 1, (10, 0), (11, 15)),
    _event("FIN 310 Lecture", 1, (13, 0), (14, 15)),
    _event("Gym", 1, (17, 0), (18, 0)),
    _event("CS 201 Lab", 2, (9, 0), (11, 0)),
    _event("Econ Recitation", 2, (14, 0), (15, 0)),
    _event("Club meeting", 2, (18, 0), (19, 30)),
    _event("CS 201 Lecture", 3, (10, 0), (11, 15)),
    _event("FIN 310 Lecture", 3, (13, 0), (14, 15)),
    _event("Coffee with advisor", 3, (15, 30), (16, 0)),
    _event("Gym", 3, (17, 0), (18, 0)),
    _event("CS 201 Lab", 4, (9, 0), (11, 0)),
    _event("Career fair", 4, (12, 0), (15, 0)),
    _event("Econ Recitation", 4, (14, 0), (15, 0)),
    _event("FIN 310 Midterm", 5, (10, 0), (11, 30)),
    _event("CS 201 Lecture", 5, (13, 0), (14, 0)),
    _event("Gym", 5, (17, 0), (18, 0)),
    _event("Hackathon", 6, (9, 0), (21, 0)),
]
TASKS = [
    _task("t-reading", "Reading response ~45m", 1, "Econ"),
    _task("t-pset", "Problem set 4 ~3h", 2, "CS 201"),
    _task("ical:assignment-dcf", "DCF model ~4h", 4, "Canvas", due_time="23:59", source="ical"),
    _task("t-lab", "Lab report ~2h", 6, "CS 201"),
    _task("t-email", "Email TA about regrade", None, "Personal"),
]
STATUS = {"calendar_ok": True, "tasks_ok": True, "gmail_ok": True, "feeds_ok": True}


def seed_data() -> str:
    """Fill the temporary data/ folder. Returns the id of today's finished session (checked in for the evening shot)."""
    earlier = (TODAY - timedelta(days=10)).isoformat()
    finished = [{"key": f"old-{n}", "title": f"Problem set {n}", "done_at": earlier, "list": "CS 201",
                 "estimate": 60, "actual": 90, "from_task": True} for n in (1, 2, 3)]
    finished.append({"key": "t-quiz", "title": "Quiz 2 corrections", "done_at": TODAY.isoformat()})
    write_json_atomic(data_path("done_tasks.json"), finished)

    midterm = exam_ref("FIN 310 Midterm", _day(5))
    add_saved_events([
        {"date": _day(0).isoformat(), "start": "14:00", "end": "15:30", "title": "Work on: Problem set 4 ~3h", "ref": "study:t-pset"},
        {"date": _day(0).isoformat(), "start": "16:00", "end": "17:00", "title": "Review for: FIN 310 Midterm", "ref": midterm},
        {"date": _day(2).isoformat(), "start": "16:00", "end": "17:00", "title": "Office hours"},
    ])
    (today_session,) = add_saved_events([
        {"date": TODAY.isoformat(), "start": "08:00", "end": "09:00", "title": "Work on: Reading response ~45m", "ref": "study:t-reading"},
    ])
    return today_session["id"]


def _ollama_tags(*args, **kwargs):
    response = mock.Mock()
    response.json.return_value = {"models": [{"name": Settings().model}]}
    return response


def shoot(browser: str, url: str, path: Path, width: int, height: int, profile: Path) -> None:
    path.unlink(missing_ok=True)
    subprocess.run(
        [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={profile}",
         f"--window-size={width},{height}", "--virtual-time-budget=10000", f"--screenshot={path}", url],
        capture_output=True, timeout=120,
    )
    for _ in range(60):  # some launchers return before the screenshot is written
        if path.exists():
            return
        clock.sleep(0.5)
    raise RuntimeError(f"The browser didn't write {path.name}")


def main() -> int:
    browser = next((path for path in BROWSERS if Path(path).exists()), None)
    if browser is None:
        print("Couldn't find Chrome or Edge.")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)  # no line per request
    with tempfile.TemporaryDirectory() as tmp, \
            mock.patch.object(local_store, "DATA_DIR", Path(tmp) / "data"), \
            mock.patch.object(server, "_config_problem", None), \
            mock.patch.object(server, "_load_settings", return_value=Settings()), \
            mock.patch.object(server, "get_credentials", return_value=object()), \
            mock.patch.object(server, "fetch_sources", return_value=(EVENTS, TASKS, [], STATUS)), \
            mock.patch.object(server, "_todays_plan_text", return_value=SAMPLE_PLAN), \
            mock.patch.object(server.requests, "get", side_effect=_ollama_tags):
        server._google_cache.clear()
        session_id = seed_data()
        httpd = make_server("127.0.0.1", 0, server.app, threaded=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{httpd.server_port}/"
        try:
            with mock.patch.object(timeutil, "now", return_value=timeutil.at(TODAY, time(7, 30))):
                shoot(browser, url, OUT / "week.png", 1440, 900, Path(tmp) / "profile-week")
            set_session_status(session_id, "done")
            with mock.patch.object(timeutil, "now", return_value=timeutil.at(TODAY, time(20, 30))):
                shoot(browser, url, OUT / "phone.png", 500, 1160, Path(tmp) / "profile-phone")
        finally:
            httpd.shutdown()
    print(f"Wrote {OUT / 'week.png'} and {OUT / 'phone.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
