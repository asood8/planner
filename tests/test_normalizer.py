import unittest
from datetime import date, datetime, time, timedelta, timezone

from core import timeutil
from core.normalizer import _filter_week, _find_free_blocks, free_blocks_for_day, normalize


def _local(hour, minute=0):
    """Aware local datetime today, the shape fetch/calendar.py produces."""
    return datetime.combine(date.today(), time(hour, minute)).astimezone()


def _hours(blocks):
    return [(start.hour, end.hour) for start, end in blocks]


class FreeBlockTests(unittest.TestCase):
    def test_local_event_blocks_its_own_hours(self):
        blocks = _find_free_blocks([{"start": _local(10), "end": _local(11)}])
        self.assertEqual(_hours(blocks), [(8, 10), (11, 22)])

    def test_naive_datetimes_are_treated_as_local(self):
        start = datetime.combine(date.today(), time(10))
        blocks = _find_free_blocks([{"start": start, "end": start + timedelta(hours=1)}])
        self.assertEqual(_hours(blocks), [(8, 10), (11, 22)])

    def test_blocks_are_clipped_to_workday_end(self):
        blocks = _find_free_blocks([{"start": _local(23), "end": _local(23, 30)}], workday_start=20, workday_end=22)
        self.assertEqual(_hours(blocks), [(20, 22)])

    def test_workday_end_of_24_means_midnight(self):
        blocks = _find_free_blocks([], workday_start=8, workday_end=24)
        self.assertEqual(blocks[0][1] - blocks[0][0], timedelta(hours=16))

    def test_free_blocks_for_another_day_use_only_that_days_events(self):
        tomorrow = date.today() + timedelta(days=1)
        start = datetime.combine(tomorrow, time(9)).astimezone()
        events = [{"start": start, "end": start + timedelta(hours=2)}, {"start": _local(10), "end": _local(11)}]

        blocks = free_blocks_for_day(events, tomorrow)

        self.assertEqual(_hours(blocks), [(8, 9), (11, 22)])
        self.assertEqual({block[0].date() for block in blocks}, {tomorrow})


class NormalizeTests(unittest.TestCase):
    def test_each_task_lands_in_exactly_one_bucket(self):
        today = date.today()
        week_end = today - timedelta(days=today.weekday()) + timedelta(days=6)

        def task(title, days_from_today):
            due = datetime.combine(today + timedelta(days=days_from_today), time.min, tzinfo=timezone.utc)
            return {"title": title, "due": due}

        tasks = [task("past", -1), task("today", 0), task("later", 30), {"title": "someday", "due": None}]
        if week_end > today:
            tasks.append(task("this week", (week_end - today).days))

        day_context, week_context = normalize([], tasks, [])

        bucketed = (
            day_context["tasks_overdue"]
            + day_context["tasks_due_today"]
            + week_context["tasks_this_week"]
            + week_context["tasks_later"]
            + week_context["tasks_no_due"]
        )
        self.assertEqual(sorted(t["title"] for t in bucketed), sorted(t["title"] for t in tasks))
        self.assertEqual([t["title"] for t in day_context["tasks_overdue"]], ["past"])
        self.assertEqual([t["title"] for t in day_context["tasks_due_today"]], ["today"])
        self.assertEqual([t["title"] for t in week_context["tasks_later"]], ["later"])

    def test_workday_settings_are_applied(self):
        day_context, _ = normalize([], [], [], workday_start=9, workday_end=17)
        self.assertEqual(_hours(day_context["free_blocks"]), [(9, 17)])

    def test_unparseable_event_start_is_skipped(self):
        self.assertEqual(_filter_week([{"title": "bad", "start": "not a date"}]), [])


class DaylightSavingTests(unittest.TestCase):
    """US clocks fall back on Sun Nov 1, 2026, so days after it are -05:00 whatever today's offset is."""

    def setUp(self):
        timeutil.configure("America/New_York")
        self.addCleanup(timeutil.configure, None)

    def test_each_days_workday_uses_that_days_offset(self):
        ((winter_start, winter_end),) = free_blocks_for_day([], date(2026, 11, 2))
        ((summer_start, _),) = free_blocks_for_day([], date(2026, 7, 1))

        self.assertEqual((winter_start.hour, winter_end.hour), (8, 22))
        self.assertEqual(winter_start.utcoffset(), timedelta(hours=-5))
        self.assertEqual(summer_start.utcoffset(), timedelta(hours=-4))

    def test_events_after_the_change_block_the_right_hours(self):
        day = date(2026, 11, 2)
        lecture = {"start": timeutil.at(day, time(10)), "end": timeutil.at(day, time(11))}
        self.assertEqual(_hours(free_blocks_for_day([lecture], day)), [(8, 10), (11, 22)])


if __name__ == "__main__":
    unittest.main()
