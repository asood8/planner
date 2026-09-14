import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest import mock

from core import local_store
from core.review import day_review
from core.saved_events import add_saved_events, load_saved_events, set_session_status


def _local(day, hour):
    return datetime.combine(day, time(hour)).astimezone()


class DayReviewTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        patcher = mock.patch.object(local_store, "DATA_DIR", Path(temp_dir.name))
        self.addCleanup(patcher.stop)
        patcher.start()
        self.today = date.today()
        self.tomorrow = self.today + timedelta(days=1)
        self.now = _local(self.today, 20)

    def test_sums_up_the_day_and_looks_at_tomorrow(self):
        today = self.today.isoformat()
        done, skipped, _ = add_saved_events([
            {"date": today, "start": "09:00", "end": "10:00", "title": "Work on: Essay", "ref": "study:t1"},
            {"date": today, "start": "11:00", "end": "12:00", "title": "Work on: Lab", "ref": "study:t2"},
            {"date": today, "start": "13:00", "end": "14:00", "title": "Review for: Midterm", "ref": "exam:midterm|x"},
        ])
        set_session_status(done["id"], "done")
        set_session_status(skipped["id"], "skipped")
        done_entries = [
            {"key": "t9", "title": "Lab report", "done_at": today},
            {"key": "t8", "title": "Old", "done_at": "2000-01-01"},
        ]
        events = [
            {"title": "Gym", "start": _local(self.tomorrow, 17), "end": _local(self.tomorrow, 18)},
            {"title": "Lecture", "start": _local(self.tomorrow, 9), "end": _local(self.tomorrow, 10)},
            {"title": "Holiday", "start": self.tomorrow, "end": self.tomorrow + timedelta(days=1), "all_day": True},
        ]
        items = [
            {"kind": "study", "date": self.tomorrow.isoformat(), "start": "13:00"},
            {"kind": "exam", "date": self.tomorrow.isoformat(), "start": "11:00"},
            {"kind": "reply", "date": self.tomorrow.isoformat(), "start": "08:00"},
        ]

        review = day_review(self.now, load_saved_events(), done_entries, [{"id": "t1", "title": "Essay"}], events, items)

        self.assertEqual(review, {
            "finished": ["Lab report"],
            "sessions": {"done": 1, "skipped": 1, "unchecked": 1},
            "open": [{"key": "t1", "title": "Essay"}],
            "tomorrow": "Tomorrow starts with Lecture at 9:00 AM. 2 work sessions suggested, the first at 11:00 AM.",
        })

    def test_an_empty_day(self):
        self.assertEqual(day_review(self.now, [], [], [], [], []), {
            "finished": [],
            "sessions": {"done": 0, "skipped": 0, "unchecked": 0},
            "open": [],
            "tomorrow": "Nothing on the calendar for tomorrow yet.",
        })


if __name__ == "__main__":
    unittest.main()
