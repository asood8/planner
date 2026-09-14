import io
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import local_store, logs


class LoggingTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.data_dir = Path(temp_dir.name)
        for patcher in (mock.patch.object(local_store, "DATA_DIR", self.data_dir), mock.patch("sys.stderr", io.StringIO())):
            self.addCleanup(patcher.stop)
            patcher.start()
        # Registered last so it runs first: the log file must be closed before the temp dir is removed.
        self.addCleanup(logs.teardown_logging)
        logs.setup_logging(console=True)
        self.logger = logging.getLogger("planner.test")

    def _flush(self):
        for handler in logging.getLogger().handlers:
            handler.flush()

    def test_failures_log_one_line_to_the_console_and_a_traceback_to_the_file(self):
        import sys

        try:
            raise RuntimeError("Ollama is down")
        except RuntimeError as exc:
            logs.log_failure(self.logger, "Plan generation failed", exc)
        self.logger.info("Plan saved.")
        self._flush()

        console = sys.stderr.getvalue()
        self.assertIn("Warning: Plan generation failed: Ollama is down", console)
        self.assertIn("Plan saved.", console)
        self.assertNotIn("Traceback", console)

        log_text = (self.data_dir / logs.LOG_FILE).read_text(encoding="utf-8")
        self.assertIn("WARNING planner.test: Plan generation failed: Ollama is down", log_text)
        self.assertIn("Traceback", log_text)

    def test_setting_up_again_does_not_duplicate_handlers(self):
        logs.setup_logging(console=True)
        handlers = [handler for handler in logging.getLogger().handlers if getattr(handler, "planner_handler", False)]
        self.assertEqual(len(handlers), 2)


if __name__ == "__main__":
    unittest.main()
