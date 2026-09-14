import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from core import local_store, plan_history
from core.plan_history import get_plan, latest_plan_for, list_plans, save_plan


class PlanHistoryTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        patcher = mock.patch.object(local_store, "DATA_DIR", Path(temp_dir.name))
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_save_list_get_and_latest(self):
        first = save_plan("plan one", "daily", "m")
        second = save_plan("plan two", "weekly", "m")

        self.assertEqual([plan["id"] for plan in list_plans()], [second["id"], first["id"]])
        self.assertNotIn("text", list_plans()[0])
        self.assertEqual(get_plan(first["id"])["text"], "plan one")
        self.assertEqual(latest_plan_for(date.today())["id"], second["id"])
        self.assertIsNone(latest_plan_for(date.today() - timedelta(days=1)))
        self.assertIsNone(get_plan("missing"))

    def test_history_is_capped(self):
        with mock.patch.object(plan_history, "MAX_PLANS", 3):
            ids = [save_plan(f"plan {n}", "daily", "m")["id"] for n in range(5)]
        self.assertEqual([plan["id"] for plan in list_plans()], [ids[4], ids[3], ids[2]])


if __name__ == "__main__":
    unittest.main()
