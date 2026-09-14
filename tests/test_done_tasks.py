import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import local_store
from core.done_tasks import load_done, mark_done, record_actual, undo_done, without_done
from core.normalizer import task_key


class DoneTasksTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        patcher = mock.patch.object(local_store, "DATA_DIR", Path(temp_dir.name))
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_mark_undo_and_load(self):
        mark_done("t1", "Essay")
        mark_done("t2", "Lab")
        mark_done("t1", "Essay")

        self.assertEqual([entry["key"] for entry in load_done()], ["t1", "t2"])
        self.assertTrue(undo_done("t1"))
        self.assertFalse(undo_done("t1"))
        self.assertEqual([entry["key"] for entry in load_done()], ["t2"])

    def test_measurements_are_kept_and_other_fields_dropped(self):
        mark_done("t1", "Essay", {"list": "School", "estimate": 120, "from_task": True, "actual": None, "extra": "x"})

        entry = load_done()[0]
        self.assertEqual({name: entry[name] for name in ("list", "estimate", "from_task")}, {"list": "School", "estimate": 120, "from_task": True})
        self.assertNotIn("actual", entry)
        self.assertNotIn("extra", entry)

    def test_record_actual(self):
        mark_done("t1", "Essay")
        self.assertTrue(record_actual("t1", 95))
        self.assertEqual(load_done()[0]["actual"], 95)
        self.assertFalse(record_actual("nope", 10))

    def test_blank_key_is_rejected(self):
        with self.assertRaises(ValueError):
            mark_done("  ", "Essay")

    def test_without_done_filters_lists_and_grouped_dicts(self):
        mark_done("t1", "Essay")
        essay, lab = {"id": "t1", "title": "Essay"}, {"id": "t2", "title": "Lab"}

        self.assertEqual(without_done([essay, lab]), [lab])
        grouped = {"overdue": [essay], "has_due_date": [lab], "no_due_date": []}
        self.assertEqual(without_done(grouped), {"overdue": [], "has_due_date": [lab], "no_due_date": []})

    def test_tasks_without_ids_match_by_list_and_title(self):
        task = {"title": "Read Ch. 4", "list": "School"}
        mark_done(task_key(task), "Read Ch. 4")
        self.assertEqual(without_done([task]), [])


if __name__ == "__main__":
    unittest.main()
