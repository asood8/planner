import json
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest import mock

from core import local_store, saved_events
from core.saved_events import add_saved_events, delete_saved_event, load_saved_events, to_calendar_events, update_saved_event


class SavedEventsTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        data_dir = Path(temp_dir.name) / "data"
        self.path = data_dir / saved_events.FILE_NAME
        patcher = mock.patch.object(local_store, "DATA_DIR", data_dir)
        self.addCleanup(patcher.stop)
        patcher.start()
        self.today = date.today().isoformat()

    def _event(self, start, end, title):
        return {"date": self.today, "start": start, "end": end, "title": title}

    def test_add_validates_normalizes_and_dedupes(self):
        added = add_saved_events([
            self._event("2:00 PM", "15:00", "  Gym   session "),
            self._event("14:00", "13:00", "Backwards"),
            {"date": "not a date", "start": "09:00", "end": "10:00", "title": "Bad date"},
            self._event("09:00", "10:00", ""),
            "junk",
        ])

        self.assertEqual([(e["start"], e["end"], e["title"]) for e in added], [("14:00", "15:00", "Gym session")])
        self.assertEqual(add_saved_events([self._event("14:00", "15:00", "gym SESSION")]), [])
        self.assertEqual(len(load_saved_events()), 1)

    def test_one_request_shares_a_batch_and_can_be_deleted_together(self):
        added = add_saved_events([self._event("09:00", "10:00", "Read"), self._event("11:00", "12:00", "Write")])

        self.assertEqual(len({event["batch"] for event in added}), 1)
        self.assertEqual(delete_saved_event(added[0]["id"], include_batch=True), 2)
        self.assertEqual(load_saved_events(), [])
        self.assertEqual(delete_saved_event("missing"), 0)

    def test_single_delete_keeps_the_rest_of_the_batch(self):
        added = add_saved_events([self._event("09:00", "10:00", "Read"), self._event("11:00", "12:00", "Write")])

        self.assertEqual(delete_saved_event(added[0]["id"]), 1)
        self.assertEqual([event["title"] for event in load_saved_events()], ["Write"])

    def test_events_older_than_keep_days_are_pruned_on_save(self):
        old_day = (date.today() - timedelta(days=saved_events.KEEP_DAYS + 1)).isoformat()
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            json.dumps([{"id": "old", "batch": "b", "date": old_day, "start": "09:00", "end": "10:00", "title": "Old"}]),
            encoding="utf-8",
        )

        add_saved_events([self._event("09:00", "10:00", "New")])

        self.assertEqual([event["title"] for event in load_saved_events()], ["New"])

    def test_corrupt_file_reads_as_empty(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("not json", encoding="utf-8")
        self.assertEqual(load_saved_events(), [])

    def test_to_calendar_events_uses_aware_local_times(self):
        added = add_saved_events([self._event("14:00", "15:00", "Gym")])

        (event,) = to_calendar_events(added)

        self.assertIsNotNone(event["start"].tzinfo)
        self.assertEqual(event["start"], datetime.combine(date.today(), time(14)).astimezone())
        self.assertEqual(event["source"], "ask_ai")
        self.assertEqual(event["id"], added[0]["id"])

    def test_all_day_events_and_refs_round_trip(self):
        added = add_saved_events([{"date": self.today, "all_day": True, "title": "Due: PS3", "ref": "deadline:e1:0"}])

        self.assertEqual((added[0]["all_day"], added[0]["ref"]), (True, "deadline:e1:0"))
        (event,) = to_calendar_events(load_saved_events())
        self.assertEqual((event["start"], event["end"]), (date.today(), date.today() + timedelta(days=1)))
        self.assertTrue(event["all_day"])
        self.assertEqual(event["ref"], "deadline:e1:0")
        self.assertEqual(event["description"], "Accepted suggestion")

    def test_update_moves_an_event_and_keeps_its_identity(self):
        (added,) = add_saved_events([{**self._event("09:00", "10:00", "Gym"), "ref": "study:t1"}])

        updated = update_saved_event(added["id"], {"start": "17:00", "end": "18:00", "title": "ignored"})

        self.assertEqual(
            (updated["id"], updated["batch"], updated["ref"], updated["title"], updated["start"], updated["end"]),
            (added["id"], added["batch"], "study:t1", "Gym", "17:00", "18:00"),
        )
        self.assertEqual(load_saved_events(), [updated])

    def test_update_to_all_day_and_back(self):
        (added,) = add_saved_events([self._event("09:00", "10:00", "Gym")])

        self.assertTrue(update_saved_event(added["id"], {"all_day": True})["all_day"])
        timed = update_saved_event(added["id"], {"all_day": False, "start": "08:00", "end": "08:30"})
        self.assertNotIn("all_day", timed)
        self.assertEqual((timed["start"], timed["end"]), ("08:00", "08:30"))

    def test_invalid_updates_raise_and_change_nothing(self):
        with self.assertRaises(KeyError):
            update_saved_event("missing", {})
        (added,) = add_saved_events([self._event("09:00", "10:00", "Gym")])
        with self.assertRaises(ValueError):
            update_saved_event(added["id"], {"start": "10:00", "end": "09:00"})
        self.assertEqual(load_saved_events()[0]["start"], "09:00")


if __name__ == "__main__":
    unittest.main()
