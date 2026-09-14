import unittest
from datetime import date, datetime, time, timedelta, timezone

from core.settings import StudyBlocks
from core.study_blocks import allocate, estimate_minutes, free_slots, study_candidates


def _local(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute)).astimezone()


def _hm(slots):
    return [(start.strftime("%H:%M"), end.strftime("%H:%M")) for start, end in slots]


def _task(title, due_day, **extra):
    return {"title": title, "due": datetime.combine(due_day, time.min, tzinfo=timezone.utc), "list": "School", **extra}


class EstimateTests(unittest.TestCase):
    def test_estimates_from_title_or_notes(self):
        self.assertEqual(estimate_minutes({"title": "Essay ~2h"}, 60), 120)
        self.assertEqual(estimate_minutes({"title": "Lab", "notes": "est 90m"}, 60), 90)
        self.assertEqual(estimate_minutes({"title": "Read ch. 4 (estimate: 1.5 hours)"}, 60), 90)
        self.assertEqual(estimate_minutes({"title": "Quick form ~5m"}, 60), 15)

    def test_falls_back_to_the_default(self):
        self.assertEqual(estimate_minutes({"title": "Latest news digest", "notes": None}, 60), 60)


class FreeSlotsTests(unittest.TestCase):
    def test_skips_events_and_starts_after_now(self):
        today = date.today()
        events = [{"title": "Class", "start": _local(today, 10), "end": _local(today, 11)}]
        slots = free_slots(events, today, today, _local(today, 9, 7))
        self.assertEqual(_hm(slots), [("09:15", "10:00"), ("11:00", "22:00")])

    def test_covers_several_days(self):
        today = date.today()
        slots = free_slots([], today, today + timedelta(days=1), _local(today, 21, 50))
        self.assertEqual([(start.date(), start.strftime("%H:%M")) for start, _ in slots], [(today + timedelta(days=1), "08:00")])


class AllocateTests(unittest.TestCase):
    def test_splits_long_work_into_sessions_with_breaks(self):
        day = date.today()
        slots = [[_local(day, 8), _local(day, 12)]]
        self.assertEqual(_hm(allocate(slots, 150, day, 90)), [("08:00", "09:30"), ("09:45", "10:45")])
        # The slot was consumed, so the next allocation starts after another break.
        self.assertEqual(_hm(allocate(slots, 30, day, 90)), [("11:00", "11:30")])

    def test_never_goes_past_the_last_day(self):
        day = date.today()
        tomorrow = day + timedelta(days=1)
        slots = [[_local(day, 8), _local(day, 8, 20)], [_local(tomorrow, 8), _local(tomorrow, 12)]]
        self.assertEqual(allocate(slots, 60, day, 90), [])


class CandidateTests(unittest.TestCase):
    def test_filters_to_the_horizon_and_orders_by_deadline(self):
        today = date.today()
        tasks = [
            _task("Later", today + timedelta(days=10)),
            _task("Soon", today + timedelta(days=1)),
            _task("Now", today),
            _task("Old", today - timedelta(days=2)),
            {"title": "Someday", "due": None},
        ]

        candidates = study_candidates(tasks, today, StudyBlocks(), {}, set())

        self.assertEqual([candidate["task"]["title"] for candidate in candidates], ["Old", "Now", "Soon"])
        self.assertEqual(candidates[0]["last_day"], today + timedelta(days=1))

    def test_accepted_time_and_dismissals_are_respected(self):
        today = date.today()
        tasks = [_task("Essay", today + timedelta(days=1), id="t1"), _task("Lab", today + timedelta(days=1), id="t2")]

        self.assertEqual(study_candidates(tasks, today, StudyBlocks(), {"t1": 50}, {"t2"}), [])
        partial = study_candidates(tasks[:1], today, StudyBlocks(), {"t1": 20}, set())
        self.assertEqual(partial[0]["remaining"], 40)

    def test_settings_change_the_horizon_and_default_effort(self):
        today = date.today()
        tasks = [_task("Report", today + timedelta(days=5), id="t1")]
        self.assertEqual(study_candidates(tasks, today, StudyBlocks(), {}, set()), [])
        (candidate,) = study_candidates(tasks, today, StudyBlocks(days_ahead=7, default_minutes=120), {}, set())
        self.assertEqual(candidate["estimate"], 120)


if __name__ == "__main__":
    unittest.main()
