import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from core import email_deadlines, local_store
from core.email_deadlines import cached_items, looks_actionable, scan_emails


class FakeClient:
    """Stands in for OllamaClient.generate_json; responses (dicts or exceptions) are used in order."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def generate_json(self, prompt, schema, model=None):
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _email(email_id, subject, snippet=""):
    return {"id": email_id, "sender": "Prof", "subject": subject, "snippet": snippet, "date": datetime.now(timezone.utc)}


class EmailDeadlineTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        patcher = mock.patch.object(local_store, "DATA_DIR", Path(temp_dir.name))
        self.addCleanup(patcher.stop)
        patcher.start()
        self.today = date.today()
        self.due = (self.today + timedelta(days=2)).isoformat()

    def test_only_actionable_emails_go_to_the_model(self):
        emails = [_email("news", "Weekly digest", "Top stories this week"), _email("hw", "Problem set 3 due Friday")]
        client = FakeClient({"items": [{"email_id": "hw", "kind": "deadline", "title": "Problem set 3", "date": self.due}]})

        self.assertEqual(scan_emails(emails, client, "m", self.today), 1)

        self.assertEqual(len(client.prompts), 1)
        self.assertIn("[hw]", client.prompts[0])
        self.assertNotIn("[news]", client.prompts[0])
        items = cached_items(emails)
        self.assertEqual([(i["ref"], i["title"], i["date"]) for i in items], [("deadline:hw:0", "Problem set 3", self.due)])

    def test_emails_are_scanned_only_once(self):
        emails = [_email("hw", "Problem set 3 due Friday")]
        scan_emails(emails, FakeClient({"items": []}), "m", self.today)
        # A client with no responses would fail if it were called again.
        self.assertEqual(scan_emails(emails, FakeClient(), "m", self.today), 0)

    def test_invalid_items_are_dropped(self):
        emails = [_email("a", "Reply needed: meeting time?"), _email("b", "Exam registration deadline")]
        client = FakeClient({"items": [
            {"email_id": "zzz", "kind": "deadline", "title": "Unknown email", "date": self.due},
            {"email_id": "a", "kind": "reply", "title": "Confirm meeting time"},
            {"email_id": "b", "kind": "deadline", "title": "Bad date", "date": "Friday"},
            {"email_id": "b", "kind": "deadline", "title": "Too far", "date": (self.today + timedelta(days=400)).isoformat()},
            {"email_id": "[b]", "kind": "deadline", "title": "Exam registration", "date": self.due, "time": "11:59 PM"},
            {"email_id": "b", "kind": "deadline", "title": "  ", "date": self.due},
            {"email_id": "b", "kind": "other", "title": "Wrong kind", "date": self.due},
        ]})

        scan_emails(emails, client, "m", self.today)

        items = {(item["kind"], item["title"]): item for item in cached_items(emails)}
        self.assertEqual(sorted(items), [("deadline", "Exam registration"), ("reply", "Confirm meeting time")])
        self.assertEqual(items[("deadline", "Exam registration")]["time"], "23:59")

    def test_model_failure_keeps_results_so_far(self):
        emails = [_email("news", "Weekly digest"), _email("hw", "Problem set 3 due Friday")]
        with self.assertRaises(RuntimeError):
            scan_emails(emails, FakeClient(RuntimeError("Ollama server is not running")), "m", self.today)

        retry = FakeClient({"items": []})
        self.assertEqual(scan_emails(emails, retry, "m", self.today), 1)
        self.assertNotIn("[news]", retry.prompts[0])

    def test_large_scans_are_batched(self):
        emails = [_email(f"e{n}", f"Quiz {n} due tomorrow") for n in range(email_deadlines.BATCH_SIZE + 2)]
        client = FakeClient({"items": []}, {"items": []})
        self.assertEqual(scan_emails(emails, client, "m", self.today), len(emails))
        self.assertEqual(len(client.prompts), 2)

    def test_a_scan_already_running_returns_none(self):
        with local_store.locked(email_deadlines.SCAN_LOCK):
            self.assertIsNone(scan_emails([_email("hw", "Homework due")], FakeClient(), "m", self.today))

    def test_looks_actionable(self):
        self.assertTrue(looks_actionable({"subject": "Please RSVP by Friday"}))
        self.assertFalse(looks_actionable({"subject": "Your weekly newsletter", "snippet": "Top picks for you"}))


if __name__ == "__main__":
    unittest.main()
