import tempfile
import unittest
from datetime import date, datetime, time, timezone
from pathlib import Path
from unittest import mock

from core import local_store, pipeline
from core.done_tasks import mark_done
from core.settings import Settings


class FetchSourcesTests(unittest.TestCase):
    def _fetch(self, tasks=None, tasks_error=None, feeds=None, feeds_error=None):
        google_tasks = tasks if tasks is not None else {"overdue": [], "has_due_date": [{"title": "Google task"}], "no_due_date": []}
        with mock.patch.object(pipeline, "get_events", return_value=[{"title": "Google event"}]), \
                mock.patch.object(pipeline, "get_tasks", return_value=google_tasks, side_effect=tasks_error), \
                mock.patch.object(pipeline, "get_unread_emails", return_value=[]), \
                mock.patch.object(pipeline, "fetch_feeds", return_value=feeds, side_effect=feeds_error):
            return pipeline.fetch_sources(object(), Settings())

    def test_feed_events_and_deadlines_are_merged(self):
        feeds = ([{"title": "Feed event"}], [{"id": "ical:1", "title": "Canvas HW"}], True)

        events, tasks, _, status = self._fetch(feeds=feeds)

        self.assertEqual([event["title"] for event in events], ["Google event", "Feed event"])
        self.assertEqual([task["title"] for task in tasks["has_due_date"]], ["Google task", "Canvas HW"])
        self.assertEqual(status, {"calendar_ok": True, "tasks_ok": True, "gmail_ok": True, "feeds_ok": True})

    def test_feed_failure_does_not_break_the_rest(self):
        events, _, _, status = self._fetch(feeds_error=RuntimeError("boom"))
        self.assertEqual([event["title"] for event in events], ["Google event"])
        self.assertFalse(status["feeds_ok"])

    def test_deadlines_still_arrive_when_the_task_fetch_fails(self):
        deadline = {"id": "ical:1", "title": "Canvas HW"}
        _, tasks, _, status = self._fetch(tasks_error=RuntimeError("boom"), feeds=([], [deadline], True))
        self.assertEqual(tasks, [deadline])
        self.assertFalse(status["tasks_ok"])

    def test_gmail_is_skipped_when_disabled(self):
        with mock.patch.object(pipeline, "get_events", return_value=[]), \
                mock.patch.object(pipeline, "get_tasks", return_value=[]), \
                mock.patch.object(pipeline, "get_unread_emails") as get_emails, \
                mock.patch.object(pipeline, "fetch_feeds", return_value=([], [], None)):
            _, _, emails, status = pipeline.fetch_sources(object(), Settings(include_gmail=False))
        get_emails.assert_not_called()
        self.assertEqual((emails, status["gmail_ok"]), ([], None))


class PrepareContextsTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        patcher = mock.patch.object(local_store, "DATA_DIR", Path(temp_dir.name))
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_tasks_marked_done_are_left_out(self):
        due = datetime.combine(date.today(), time.min, tzinfo=timezone.utc)
        tasks = [{"id": "t1", "title": "Essay", "due": due}, {"id": "t2", "title": "Lab", "due": due}]
        mark_done("t1", "Essay")

        _, day_context, _, _ = pipeline.prepare_contexts([], tasks, [], Settings())

        self.assertEqual([task["id"] for task in day_context["tasks_due_today"]], ["t2"])


if __name__ == "__main__":
    unittest.main()
