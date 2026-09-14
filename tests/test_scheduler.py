import unittest
from datetime import date, datetime, time, timedelta
from unittest import mock

from core import scheduler
from core.scheduler import Session, remaining_slots, schedule
from core.settings import StudyBlocks

TODAY = date(2026, 9, 14)  # a Monday; fixed so results don't depend on the clock


def _at(day_offset, hour, minute=0):
    return datetime.combine(TODAY + timedelta(days=day_offset), time(hour, minute)).astimezone()


def _slot(day_offset, start_hour, end_hour):
    return [_at(day_offset, start_hour), _at(day_offset, end_hour)]


def _candidate(key, minutes, due_in_days):
    due = TODAY + timedelta(days=due_in_days)
    return {"key": key, "task": {"title": key}, "due": due, "last_day": max(due, TODAY), "remaining": minutes}


def _minutes(session):
    return int((session.end - session.start).total_seconds() // 60)


def _per_day(sessions):
    totals = {}
    for session in sessions:
        totals[session.start.date()] = totals.get(session.start.date(), 0) + _minutes(session)
    return totals


class SchedulerTestCase(unittest.TestCase):
    def setUp(self):
        scheduler._cache.clear()
        self.addCleanup(scheduler._cache.clear)


@unittest.skipIf(scheduler.cp_model is None, "OR-Tools isn't installed")
class OptimizedScheduleTests(SchedulerTestCase):
    def test_hard_rules_hold(self):
        settings = StudyBlocks(max_minutes_per_day=180)
        candidates = [_candidate("essay", 240, 2), _candidate("lab", 120, 1)]

        result = schedule(candidates, [_slot(0, 8, 22), _slot(1, 8, 22), _slot(2, 8, 12)], settings, TODAY)

        self.assertEqual(result.method, "optimized")
        self.assertEqual(result.short_minutes, {})
        for session in result.sessions:
            self.assertGreaterEqual(_minutes(session), 30)
            self.assertLessEqual(_minutes(session), settings.max_session_minutes)
            candidate = next(c for c in candidates if c["key"] == session.key)
            self.assertLessEqual(session.start.date(), candidate["last_day"])
        self.assertTrue(all(total <= 180 for total in _per_day(result.sessions).values()))

        ordered = sorted(result.sessions, key=lambda session: session.start)
        stretch_start = ordered[0].start
        for earlier, later in zip(ordered, ordered[1:]):
            self.assertLessEqual(earlier.end, later.start)  # no overlaps
            if later.start > earlier.end:
                stretch_start = later.start
            # Back-to-back work (even across tasks) never runs longer than one session without a break.
            self.assertLessEqual(later.end - stretch_start, timedelta(minutes=settings.max_session_minutes))

    def test_preferred_hours_are_used_when_there_is_room(self):
        settings = StudyBlocks(preferred_start=13, preferred_end=18)

        result = schedule([_candidate("essay", 120, 3)], [_slot(0, 8, 22)], settings, TODAY)

        self.assertEqual(sum(map(_minutes, result.sessions)), 120)
        for session in result.sessions:
            self.assertGreaterEqual(session.start, _at(0, 13))
            self.assertLessEqual(session.end, _at(0, 18))
            self.assertIn("Inside your preferred study hours", session.reasons)

    def test_work_goes_as_soon_and_as_early_as_it_can(self):
        slots = [_slot(0, 8, 22), _slot(1, 8, 22), _slot(2, 8, 22)]

        result = schedule([_candidate("essay", 60, 2)], slots, StudyBlocks(), TODAY)

        self.assertEqual([(s.start, s.end) for s in result.sessions], [(_at(0, 9), _at(0, 10))])  # 9 starts the preferred hours

    def test_long_work_is_spread_across_days(self):
        slots = [_slot(0, 9, 21), _slot(1, 9, 21), _slot(2, 9, 21)]

        result = schedule([_candidate("essay", 180, 2)], slots, StudyBlocks(), TODAY)

        per_day = _per_day(result.sessions)
        self.assertGreaterEqual(len(per_day), 2)
        self.assertTrue(all(total <= 90 for total in per_day.values()))
        self.assertIn("Split across 2 days so it isn't crammed", result.sessions[0].reasons)

    def test_the_nearer_deadline_wins_when_time_is_short(self):
        result = schedule([_candidate("later", 60, 3), _candidate("sooner", 60, 1)], [_slot(0, 9, 10)], StudyBlocks(), TODAY)

        self.assertEqual({session.key for session in result.sessions}, {"sooner"})
        self.assertEqual(result.short_minutes, {"later": 60})

    def test_study_already_added_counts_toward_the_daily_limit(self):
        settings = StudyBlocks(max_minutes_per_day=240)

        result = schedule([_candidate("essay", 120, 0)], [_slot(0, 9, 21)], settings, TODAY, day_loads={TODAY: 210})

        self.assertEqual(sum(map(_minutes, result.sessions)), 30)
        self.assertEqual(result.short_minutes, {"essay": 90})
        self.assertIn("Monday is at your daily study limit", result.sessions[0].reasons)

    def test_exam_review_keeps_its_daily_cap_and_aims_at_its_target_days(self):
        exam = {
            **_candidate("exam:midterm", 180, 5),
            "kind": "exam",
            "last_day": TODAY + timedelta(days=4),
            "day_cap": 60,
            "target_days": [TODAY + timedelta(days=offset) for offset in (2, 3, 4)],
        }

        result = schedule([exam], [_slot(offset, 9, 21) for offset in range(5)], StudyBlocks(), TODAY)

        self.assertEqual(_per_day(result.sessions), {TODAY + timedelta(days=offset): 60 for offset in (2, 3, 4)})
        self.assertEqual(result.sessions[0].reasons[:2], ("Exam Sat Sep 19 (in 5 days)", "Spaced over 3 days before the exam"))

    def test_a_target_day_without_room_does_not_leave_review_short(self):
        exam = {
            **_candidate("exam:midterm", 180, 3),
            "kind": "exam",
            "last_day": TODAY + timedelta(days=2),
            "day_cap": 60,
            "target_days": [TODAY + timedelta(days=offset) for offset in (0, 1, 2)],
        }

        result = schedule([exam], [_slot(1, 9, 21), _slot(2, 9, 21)], StudyBlocks(), TODAY)  # no time left today

        self.assertEqual(result.short_minutes, {})
        self.assertEqual(sum(_per_day(result.sessions).values()), 180)

    def test_results_are_cached(self):
        args = ([_candidate("essay", 60, 1)], [_slot(0, 9, 12)], StudyBlocks(), TODAY)
        self.assertIs(schedule(*args), schedule(*args))


class FallbackTests(SchedulerTestCase):
    def test_greedy_scheduler_without_ortools(self):
        with mock.patch.object(scheduler, "cp_model", None):
            result = schedule([_candidate("essay", 120, 1)], [_slot(0, 9, 12)], StudyBlocks(), TODAY)

        self.assertEqual(result.method, "greedy")
        self.assertEqual([(s.start.hour, s.start.minute, _minutes(s)) for s in result.sessions], [(9, 0, 90), (10, 45, 30)])
        self.assertIn("The earliest free time before it's due", result.sessions[0].reasons)

    def test_greedy_scheduler_keeps_the_daily_limit(self):
        with mock.patch.object(scheduler, "cp_model", None):
            result = schedule([_candidate("essay", 120, 0)], [_slot(0, 9, 21)], StudyBlocks(), TODAY, day_loads={TODAY: 210})

        self.assertEqual([(s.start.hour, _minutes(s)) for s in result.sessions], [(9, 30)])
        self.assertEqual(result.short_minutes, {"essay": 90})
        self.assertIn("Monday is at your daily study limit", result.sessions[0].reasons)

    def test_greedy_scheduler_keeps_an_exam_day_cap(self):
        exam = {**_candidate("exam:quiz", 120, 3), "kind": "exam", "day_cap": 60}
        with mock.patch.object(scheduler, "cp_model", None):
            result = schedule([exam], [_slot(0, 9, 12), _slot(1, 9, 12)], StudyBlocks(), TODAY)

        self.assertEqual(_per_day(result.sessions), {TODAY: 60, TODAY + timedelta(days=1): 60})

    def test_greedy_scheduler_goes_past_the_cap_rather_than_fall_short(self):
        exam = {**_candidate("exam:quiz", 120, 3), "kind": "exam", "day_cap": 60}
        with mock.patch.object(scheduler, "cp_model", None):
            result = schedule([exam], [_slot(0, 9, 12)], StudyBlocks(), TODAY)

        self.assertEqual(result.short_minutes, {})
        self.assertEqual([(s.start.hour, s.start.minute, _minutes(s)) for s in result.sessions], [(9, 0, 60), (10, 15, 60)])

    def test_nothing_to_schedule(self):
        self.assertEqual(schedule([], [_slot(0, 9, 12)], StudyBlocks(), TODAY).sessions, [])


class RemainingSlotsTests(unittest.TestCase):
    def test_sessions_are_cut_out_of_free_time(self):
        slots = [_slot(0, 9, 12)]
        sessions = [Session("a", _at(0, 10), _at(0, 11))]
        self.assertEqual(remaining_slots(slots, sessions), [[_at(0, 9), _at(0, 10)], [_at(0, 11), _at(0, 12)]])
        self.assertEqual(slots, [_slot(0, 9, 12)])  # the input isn't changed


if __name__ == "__main__":
    unittest.main()
