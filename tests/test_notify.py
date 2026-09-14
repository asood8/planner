import unittest
from datetime import datetime
from unittest import mock
from xml.etree import ElementTree

from output import notify
from output.notify import morning_summary, send_toast, toast_xml


class ToastXmlTests(unittest.TestCase):
    def test_escapes_text_and_keeps_at_most_three_lines(self):
        xml = toast_xml("Plan <today>", ["a & b", "c", "d"], "http://127.0.0.1:5000/?x=1&y=2")

        ElementTree.fromstring(xml)  # well-formed
        self.assertIn("<text>Plan &lt;today&gt;</text>", xml)
        self.assertIn("<text>a &amp; b</text>", xml)
        self.assertNotIn("<text>d</text>", xml)
        self.assertIn('launch="http://127.0.0.1:5000/?x=1&amp;y=2"', xml)


class SendToastTests(unittest.TestCase):
    def test_does_nothing_off_windows(self):
        with mock.patch.object(notify.sys, "platform", "linux"), mock.patch.object(notify.subprocess, "run") as run:
            self.assertFalse(send_toast("Title", ["line"]))
        run.assert_not_called()

    def test_runs_powershell_with_the_toast_xml(self):
        with mock.patch.object(notify.sys, "platform", "win32"), \
                mock.patch.object(notify.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            self.assertTrue(send_toast("Your plan", ["2 due today"]))

        args, kwargs = run.call_args
        self.assertEqual(args[0][0], "powershell")
        self.assertIn("-EncodedCommand", args[0])
        self.assertIn("<text>Your plan</text>", kwargs["env"]["PLANNER_TOAST_XML"])


class MorningSummaryTests(unittest.TestCase):
    def test_counts_what_is_due_and_lists_the_next_items(self):
        now = datetime(2026, 9, 14, 8, 0)  # a Monday
        entries = [
            {"title": "Lecture", "start": "2026-09-14T10:00:00"},
            {"title": "Study", "start": "2026-09-14T13:00:00"},
            {"title": "Earlier", "start": "2026-09-14T07:00:00"},
            {"title": "Tomorrow", "start": "2026-09-15T09:00:00"},
            {"title": "Free block", "start": "2026-09-14T09:00:00", "display": "background"},
            {"title": "Holiday", "start": "2026-09-14", "allDay": True},
        ]

        title, lines = morning_summary(entries, {"tasks_due_today": [{}], "tasks_overdue": [{}, {}]}, [], now, True)

        self.assertEqual(title, "Your plan for Monday")
        self.assertEqual(lines, ["1 due today · 2 overdue", "10:00 AM Lecture · 1:00 PM Study"])

    def test_failed_plan_on_an_empty_day(self):
        _, lines = morning_summary([], {}, ["Not enough time"], datetime(2026, 9, 14, 8, 0), False)
        self.assertEqual(lines, [
            "Nothing due today · not enough time for everything",
            "The plan couldn't be generated (is Ollama running?)",
        ])


if __name__ == "__main__":
    unittest.main()
