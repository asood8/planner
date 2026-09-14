import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest import mock

from core import local_store
from core.checkins import pending_checkins
from core.saved_events import add_saved_events, load_saved_events, set_session_status


class PendingCheckinsTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        patcher = mock.patch.object(local_store, "DATA_DIR", Path(temp_dir.name))
        self.addCleanup(patcher.stop)
        patcher.start()
        self.now = datetime.combine(date.today(), time(12)).astimezone()  # fixed at noon, whatever the clock says

    def _session(self, day_offset, start, end, title="Work on: Essay", ref="study:t1"):
        day = (date.today() + timedelta(days=day_offset)).isoformat()
        return {"date": day, "start": start, "end": end, "title": title, "ref": ref}

    def test_lists_past_sessions_nobody_checked_in_on(self):
        add_saved_events([
            self._session(0, "09:00", "10:00"),
            self._session(0, "11:30", "12:30", title="Work on: Lab"),  # still going
            self._session(1, "09:00", "10:00", title="Work on: Tomorrow"),
            self._session(-1, "15:00", "16:00", title="Review for: Midterm", ref="exam:midterm|2026-09-20"),
            self._session(-10, "09:00", "10:00", title="Work on: Long ago"),
            self._session(0, "07:00", "08:00", title="Work on: Finished", ref="study:done-task"),
            {"date": date.today().isoformat(), "start": "08:00", "end": "08:30", "title": "Gym"},
        ])

        checkins = pending_checkins(load_saved_events(), {"done-task"}, self.now)

        self.assertEqual(
            [(item["title"], item["start"], item["end"]) for item in checkins],
            [("Review for: Midterm", "15:00", "16:00"), ("Work on: Essay", "09:00", "10:00")],
        )
        self.assertEqual(checkins[1]["date"], date.today().isoformat())

    def test_checked_in_sessions_drop_off_the_list(self):
        (session,) = add_saved_events([self._session(0, "09:00", "10:00")])
        set_session_status(session["id"], "skipped")
        self.assertEqual(pending_checkins(load_saved_events(), set(), self.now), [])


if __name__ == "__main__":
    unittest.main()
