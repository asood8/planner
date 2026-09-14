import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest import mock

from core import local_store, scheduler, suggestions
from core.done_tasks import mark_done
from core.settings import Settings
from core.suggestions import build_suggestions, dismiss, load_dismissed

SETTINGS = Settings()  # workday 8-22, study blocks 3 days / 60 min / 90 min sessions


def _local(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute)).astimezone()


class SuggestionTestCase(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self._patch(local_store, "DATA_DIR", Path(temp_dir.name))
        self.cached_items = self._patch(suggestions, "cached_items", return_value=[])
        scheduler._cache.clear()
        self.addCleanup(scheduler._cache.clear)
        self.today = date.today()
        self.now = _local(self.today, 7)  # before the workday, so the whole day is free

    def _patch(self, *args, **kwargs):
        patcher = mock.patch.object(*args, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def _task(self, title, days_from_today, task_id="t1"):
        due = datetime.combine(self.today + timedelta(days=days_from_today), time.min, tzinfo=timezone.utc)
        return {"id": task_id, "title": title, "notes": "", "due": due, "list": "School"}

    def _build(self, tasks=(), events=()):
        day_context = {"tasks_overdue": [], "tasks_due_today": []}
        week_context = {"tasks_this_week": list(tasks), "tasks_later": []}
        return build_suggestions(list(events), day_context, week_context, [], SETTINGS, now=self.now)


class StudySuggestionTests(SuggestionTestCase):
    def test_sessions_fill_free_time_before_the_deadline(self):
        lecture = {"title": "Lecture", "start": _local(self.today, 8), "end": _local(self.today, 12)}

        result = self._build([self._task("Essay ~2h", 1)], [lecture])

        day, tomorrow = self.today.isoformat(), (self.today + timedelta(days=1)).isoformat()
        if scheduler.cp_model is not None:
            expected = [(day, "12:00", "13:30"), (tomorrow, "09:00", "09:30")]  # spread out, in preferred hours
        else:
            expected = [(day, "12:00", "13:30"), (day, "13:45", "14:15")]  # greedy: earliest free time
        self.assertEqual([(i["date"], i["start"], i["end"]) for i in result["items"]], expected)
        self.assertEqual({item["ref"] for item in result["items"]}, {"study:t1"})
        self.assertEqual(result["items"][0]["title"], "Work on: Essay ~2h")
        self.assertEqual(result["notices"], [])
        self.assertEqual(result["estimates"], [])

    @unittest.skipIf(scheduler.cp_model is None, "OR-Tools isn't installed")
    def test_sessions_explain_themselves(self):
        due = self.today + timedelta(days=2)

        item = self._build([self._task("Essay ~1h", 2)])["items"][0]

        self.assertEqual((item["date"], item["start"], item["end"]), (self.today.isoformat(), "09:00", "10:00"))
        self.assertEqual(
            item["details"],
            f"Due {due:%a %b %d} (in 2 days). Inside your preferred study hours. About 1 h in total (you estimated 1 h).",
        )

    def test_shortfall_becomes_a_notice(self):
        result = self._build([self._task("Thesis ~20h", 0)])
        self.assertEqual(len(result["notices"]), 1)
        self.assertIn("960 min short", result["notices"][0])  # 20 h against a 4 h daily limit

    def test_finished_tasks_adjust_the_estimate(self):
        for number in range(3):
            mark_done(f"old{number}", "Old essay", {"list": "School", "estimate": 60, "actual": 120, "from_task": False})

        result = self._build([self._task("Essay", 3)])

        planned = sum(
            (datetime.strptime(item["end"], "%H:%M") - datetime.strptime(item["start"], "%H:%M")).seconds // 60
            for item in result["items"]
        )
        self.assertEqual(planned, 90)  # the 60-minute default, times about 1.5
        self.assertIn("School tasks have taken 1.5× as long as planned", result["items"][0]["details"])
        self.assertEqual(result["estimates"], ["School tasks have taken 1.5× as long as planned (3 finished)"])

    def test_accepted_sessions_count_toward_the_estimate(self):
        accepted = {
            "title": "Work on: Essay",
            "start": _local(self.today, 9),
            "end": _local(self.today, 10),
            "source": "ask_ai",
            "ref": "study:t1",
        }
        self.assertEqual(self._build([self._task("Essay", 1)], [accepted])["items"], [])

    def test_dismissed_task_is_not_suggested(self):
        dismiss("study:t1")
        self.assertEqual(self._build([self._task("Essay", 1)])["items"], [])


class EmailSuggestionTests(SuggestionTestCase):
    def setUp(self):
        super().setUp()
        self.tomorrow = self.today + timedelta(days=1)
        self.cached_items.return_value = [
            {"kind": "deadline", "title": "Problem set", "date": self.tomorrow.isoformat(), "time": "23:59",
             "ref": "deadline:e1:0", "email_id": "e1", "sender": "Prof", "subject": "PS3"},
            {"kind": "reply", "title": "Confirm meeting", "ref": "reply:e2:0", "email_id": "e2",
             "sender": "Advisor", "subject": "Meeting"},
        ]

    def test_deadlines_are_all_day_and_replies_get_a_short_block(self):
        items = {item["kind"]: item for item in self._build()["items"]}

        self.assertEqual(items["deadline"]["title"], "Due: Problem set (11:59 PM)")
        self.assertTrue(items["deadline"]["all_day"])
        self.assertEqual(items["deadline"]["date"], self.tomorrow.isoformat())
        self.assertEqual((items["reply"]["start"], items["reply"]["end"]), ("08:00", "08:15"))
        self.assertEqual(items["reply"]["details"], "From Advisor: Meeting")

    def test_dismissed_or_accepted_items_are_hidden(self):
        dismiss("reply:e2:0")
        accepted = {
            "title": "Due: Problem set",
            "start": self.tomorrow,
            "end": self.tomorrow + timedelta(days=1),
            "all_day": True,
            "source": "ask_ai",
            "ref": "deadline:e1:0",
        }
        self.assertEqual(self._build(events=[accepted])["items"], [])


class DismissTests(SuggestionTestCase):
    def test_dismiss_persists_and_ignores_duplicates_and_blanks(self):
        dismiss("x")
        dismiss("x")
        dismiss("  ")
        self.assertEqual(load_dismissed(), {"x"})


if __name__ == "__main__":
    unittest.main()
