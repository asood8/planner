import json
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

from core.pipeline import script_safe_json
from core.settings import Settings
from plan import render_dashboard


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
                suggestions={"items": [], "notices": ["<b>Essay</b> is short"]},
            )
            html = Path(path).read_text(encoding="utf-8")
        self.assertIn("&lt;b&gt;Essay&lt;/b&gt; is short", html)


if __name__ == "__main__":
    unittest.main()
