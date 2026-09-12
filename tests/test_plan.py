import json
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

from core.pipeline import script_safe_json
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
                "plan", day_context, {}, True, False, None, {"model": "m"}, output_path=str(Path(tmp) / "dashboard.html")
            )
            html = Path(path).read_text(encoding="utf-8")

        self.assertNotIn("</script><script>alert(1)", html)
        self.assertIn('title="Calendar: connected"', html)
        self.assertIn('title="Tasks: fetch failed"', html)
        self.assertIn('title="Gmail: not loaded"', html)


if __name__ == "__main__":
    unittest.main()
