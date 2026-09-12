import unittest
from datetime import date, datetime, time, timedelta, timezone

from core.normalizer import _filter_week, _find_free_blocks, normalize


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


if __name__ == "__main__":
    unittest.main()
