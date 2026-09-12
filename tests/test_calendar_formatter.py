import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

from output.calendar_formatter import _parse_ai_plan_events, to_fullcalendar_events


def _event(title, day, hour):
    start = datetime.combine(day, time(hour)).astimezone()
    return {"title": title, "start": start, "end": start + timedelta(hours=1)}


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

    def test_calendar_events_keep_local_wall_time(self):
        today = date.today()
        naive_start = datetime.combine(today, time(15))
        day_context = {
            "date": today,
            "events": [
                _event("Aware", today, 10),
                {"title": "Naive", "start": naive_start, "end": naive_start + timedelta(hours=1)},
            ],
        }

        events = {event["title"]: event for event in to_fullcalendar_events(day_context, {})}

        self.assertEqual(events["Aware"]["start"], f"{today.isoformat()}T10:00:00")
        self.assertEqual(events["Naive"]["start"], f"{today.isoformat()}T15:00:00")

    def test_includes_other_days_without_duplicating_today(self):
        today = date.today()
        today_event = _event("Today", today, 10)
        tomorrow_event = _event("Tomorrow", today + timedelta(days=1), 10)
        day_context = {"date": today, "events": [today_event]}

        events = to_fullcalendar_events(day_context, {}, None, [today_event, tomorrow_event])

        self.assertEqual(sorted(event["title"] for event in events), ["Today", "Tomorrow"])

    def test_parses_bulleted_and_bold_plan_lines(self):
        ai_text = """## Daily Plan
- 9:00 AM - 10:30 AM Study for exam
* **12:00 PM - 12:45 PM** Lunch
- Overdue: essay"""

        events = _parse_ai_plan_events(ai_text, date(2026, 9, 14))

        self.assertEqual(
            [(event["title"], event["start"]) for event in events],
            [("Study for exam", "2026-09-14T09:00:00"), ("Lunch", "2026-09-14T12:00:00")],
        )

    def test_planner_prompt_examples_parse(self):
        # Keeps the format the planner prompt asks for in sync with what the parser accepts.
        prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "planner_system_prompt.txt"
        examples = [line for line in prompt_path.read_text(encoding="utf-8").splitlines() if line.startswith("- ") and line[2:3].isdigit()]

        self.assertTrue(examples)
        self.assertEqual(len(_parse_ai_plan_events("\n".join(examples), date(2026, 9, 14))), len(examples))

    def test_plan_blocks_restating_calendar_events_are_drawn_once(self):
        today = date.today()
        day_context = {"date": today, "events": [_event("CS Lecture", today, 10)]}
        ai_text = "- 10:00 AM - 11:00 AM CS Lecture\n- 11:00 AM - 12:00 PM Study"

        events = to_fullcalendar_events(day_context, {}, ai_text)

        self.assertEqual(sorted((event["title"], event["category"]) for event in events), [("CS Lecture", "class"), ("Study", "plan")])


if __name__ == "__main__":
    unittest.main()
