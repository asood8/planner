import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from core import local_store
from core.done_tasks import load_done
from core.local_store import StoreBusy, locked, read_json, write_json_atomic

ROOT = Path(__file__).resolve().parent.parent

# Runs in a separate process with PLANNER_DATA_DIR pointing at the test's temp directory.
WRITER = """
import sys
sys.path.insert(0, {root!r})
from core.done_tasks import mark_done
for n in range({count}):
    mark_done("{prefix}-" + str(n), "task")
"""


class LockTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.data_dir = Path(temp_dir.name)
        patcher = mock.patch.object(local_store, "DATA_DIR", self.data_dir)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_threads_do_not_lose_updates(self):
        path = local_store.data_path("counter.json")

        def bump():
            for _ in range(25):
                with locked("counter.json"):
                    value = read_json(path, 0)
                    time.sleep(0.001)  # widen the window a lost update would need
                    write_json_atomic(path, value + 1)

        threads = [threading.Thread(target=bump) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(read_json(path, 0), 100)

    def test_processes_do_not_lose_updates(self):
        env = {**os.environ, "PLANNER_DATA_DIR": str(self.data_dir)}
        processes = [
            subprocess.Popen([sys.executable, "-c", WRITER.format(root=str(ROOT), count=15, prefix=f"p{i}")], env=env, cwd=ROOT)
            for i in range(3)
        ]
        for process in processes:
            self.assertEqual(process.wait(timeout=120), 0)

        self.assertEqual(len(load_done()), 45)

    def test_a_held_lock_times_out_with_store_busy(self):
        outcome = []

        def other_thread():
            try:
                with locked("thing.json", timeout=0.2):
                    outcome.append("acquired")
            except StoreBusy as exc:
                outcome.append(exc.name)

        with locked("thing.json"):
            thread = threading.Thread(target=other_thread)
            thread.start()
            thread.join()

        self.assertEqual(outcome, ["thing.json"])
        with locked("thing.json", timeout=0):
            pass  # free again once released

    def test_writes_replace_the_whole_file_and_leave_no_temp_files(self):
        path = local_store.data_path("state.json")
        write_json_atomic(path, {"a": 1})
        write_json_atomic(path, {"b": 2})

        self.assertEqual(read_json(path, None), {"b": 2})
        self.assertEqual([item.name for item in self.data_dir.iterdir() if item.suffix == ".tmp"], [])


if __name__ == "__main__":
    unittest.main()
