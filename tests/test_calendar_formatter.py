import unittest
from datetime import date

from output.calendar_formatter import _parse_ai_plan_events


class CalendarFormatterTests(unittest.TestCase):
    def test_parses_machine_readable_days(self):
        ai_text = """2026-08-15 02:00 PM - 03:00 PM Gym
2026-08-16 02:00 PM - 03:00 PM Gym"""

        events = _parse_ai_plan_events(ai_text, date(2026, 8, 14))

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["title"], "Gym")
        self.assertEqual(events[0]["start"], "2026-08-15T14:00:00")
        self.assertEqual(events[0]["end"], "2026-08-15T15:00:00")

    def test_ignores_explanatory_narrative_and_keeps_only_machine_readable_lines(self):
        ai_text = """Plan Response in Machine-Readable Format:
1. Schedule Gym Visit:
2026-08-15 02:00 PM - 03:00 PM Gym
Note: This is daily.
"""

        events = _parse_ai_plan_events(ai_text, date(2026, 8, 14))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["title"], "Gym")
        self.assertEqual(events[0]["start"], "2026-08-15T14:00:00")


if __name__ == "__main__":
    unittest.main()
