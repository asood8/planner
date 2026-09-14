import unittest
from datetime import date, datetime, time, timedelta, timezone

from core.settings import Settings
from core.week_ahead import busy_minutes, week_warnings

TODAY = date(2026, 9, 14)  # a Monday
NOW = datetime.combine(TODAY, time(7)).astimezone()


def _event(day_offset, start_hour, end_hour, title="Class"):
    day = TODAY + timedelta(days=day_offset)
    start = datetime.combine(day, time(start_hour)).astimezone()
    end = datetime.combine(day, time(end_hour)).astimezone()
    return {"title": title, "start": start, "end": end, "all_day": False}


def _task(title, due_in_days, task_id):
    due = datetime.combine(TODAY + timedelta(days=due_in_days), time.min, tzinfo=timezone.utc)
    return {"id": task_id, "title": title, "notes": "", "due": due, "list": "School"}


def _booked_week():
    """Classes 8-12 and 13-22 every day: one free hour a day."""
    return [event for offset in range(7) for event in (_event(offset, 8, 12), _event(offset, 13, 22))]


class BusyMinutesTests(unittest.TestCase):
    def test_overlaps_count_once_and_only_inside_the_workday(self):
        day = TODAY + timedelta(days=1)
        events = [
            _event(1, 7, 10),  # 8-10 counts
            _event(1, 9, 11),  # adds 10-11
            _event(1, 21, 23),  # 21-22 counts
            _event(2, 9, 17),  # another day
            {"title": "Holiday", "start": day, "end": day + timedelta(days=1), "all_day": True},
        ]
        self.assertEqual(busy_minutes(events, day, 8, 22), 240)


class WeekWarningsTests(unittest.TestCase):
    def _warnings(self, events=(), tasks=(), exams=()):
        return week_warnings(list(events), list(tasks), list(exams), TODAY, NOW, Settings(), None, {}, {})

    def test_a_quiet_week_has_no_warnings(self):
        self.assertEqual(self._warnings(tasks=[_task("Essay", 5, "t1")]), [])

    def test_a_crunch_after_the_suggestion_window_and_packed_days(self):
        warnings = self._warnings(_booked_week(), [_task("Thesis ~10h", 5, "t1")])

        self.assertEqual(warnings, [
            "By Sat Sep 19: about 10 h of work is due (1 thing), but only about 6 h of study time is left before then.",
            "Tue Sep 15 is packed: 13 h of events and 1 h free.",
            "Wed Sep 16 is packed: 13 h of events and 1 h free.",
            "Thu Sep 17 is packed: 13 h of events and 1 h free.",
        ])

    def test_near_deadlines_are_left_to_the_study_suggestions(self):
        warnings = self._warnings(_booked_week(), [_task("Thesis ~10h", 2, "t1")])
        self.assertFalse([line for line in warnings if line.startswith("By ")])

    def test_exam_review_counts_as_work(self):
        exam = {"last_day": TODAY + timedelta(days=5), "remaining": 600}
        warnings = self._warnings(_booked_week(), exams=[exam])
        self.assertTrue(warnings[0].startswith("By Sat Sep 19: about 10 h of work is due (1 thing)"))


if __name__ == "__main__":
    unittest.main()
