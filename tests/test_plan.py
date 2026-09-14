import json
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest import mock

import plan
from core import local_store
from core.pipeline import script_safe_json
from core.settings import Settings
from plan import build_parser, render_dashboard


class ScriptSafeJsonTests(unittest.TestCase):
    def test_round_trips_without_closing_script_tags(self):
        value = [{"title": "</script><script>alert(1)</script> & more"}]
        encoded = script_safe_json(value)
        self.assertNotIn("</", encoded)
        self.assertEqual(json.loads(encoded), value)


class RenderDashboardTests(unittest.TestCase):
    def test_renders_hostile_titles_safely_and_tri_state_status(self):
        today = date.today()
        start = datetime.combine(today, time(10)).astimezone()
        day_context = {
            "date": today,
            "events": [{"title": "</script><script>alert(1)</script>", "start": start, "end": start + timedelta(hours=1)}],
            "free_blocks": [],
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = render_dashboard(
                "plan", day_context, {}, True, False, None, Settings(model="m"), output_path=str(Path(tmp) / "dashboard.html")
            )
            html = Path(path).read_text(encoding="utf-8")

        self.assertNotIn("</script><script>alert(1)", html)
        self.assertIn('title="Calendar: connected"', html)
        self.assertIn('title="Tasks: fetch failed"', html)
        self.assertIn('title="Gmail: not loaded"', html)
        self.assertIn('const DEFAULT_MODEL = "m";', html)
        # Server-only controls stay out of the static dashboard.
        self.assertNotIn('id="plan-btn"', html)
        self.assertNotIn("?refresh=1", html)
        self.assertIn("const LIVE = false;", html)
        self.assertNotIn('id="model-select"', html)

    def test_notices_are_escaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = render_dashboard(
                "plan", {"date": date.today()}, {}, True, True, True, Settings(),
                output_path=str(Path(tmp) / "dashboard.html"),
                suggestions={"items": [], "notices": ["<b>Essay</b> is short"], "week": ["<i>Tue</i> is packed"]},
            )
            html = Path(path).read_text(encoding="utf-8")
        self.assertIn("&lt;b&gt;Essay&lt;/b&gt; is short", html)
        self.assertIn("<li>&lt;i&gt;Tue&lt;/i&gt; is packed</li>", html)
        self.assertIn('<p id="week-head" class="notices-head">Coming up this week</p>', html)
        self.assertIn("const INITIAL_STATE = {};", html)


class ReviewRunTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        patcher = mock.patch.object(local_store, "DATA_DIR", Path(temp_dir.name))
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_the_parser_knows_review(self):
        self.assertTrue(build_parser().parse_args(["--review"]).review)

    def test_review_sends_a_notification_without_writing_a_plan(self):
        with mock.patch.object(plan, "get_credentials", return_value=object()), \
                mock.patch.object(plan, "fetch_sources", return_value=([], [], [], {})) as fetch, \
                mock.patch.object(plan, "server_is_running", return_value=False), \
                mock.patch.object(plan, "send_toast", return_value=True) as toast, \
                mock.patch.object(plan, "OllamaClient") as client:
            plan.run_review(Settings())

        client.assert_not_called()
        self.assertFalse(fetch.call_args.args[1].include_gmail)
        title, lines, open_url = toast.call_args.args
        self.assertTrue(title.startswith("Wrapping up "))
        self.assertEqual(lines[0], "All caught up")
        self.assertIsNone(open_url)


if __name__ == "__main__":
    unittest.main()
