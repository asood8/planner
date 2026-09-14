import unittest
from datetime import date, datetime, time, timedelta

from core.context_builder import build_busy_times, build_context


class BusyTimesTests(unittest.TestCase):
    def test_lists_each_day_in_local_24_hour_time(self):
        today = date.today()
        start = datetime.combine(today, time(14)).astimezone()
        events = [
            {"title": "Lecture", "start": start, "end": start + timedelta(hours=1)},
            {"title": "Trip", "start": today + timedelta(days=1), "end": today + timedelta(days=3), "all_day": True},
        ]

        lines = build_busy_times(events, today, days=4).splitlines()

        self.assertEqual(len(lines), 4)
        self.assertIn("14:00–15:00 Lecture", lines[0])
        self.assertIn("All day: Trip", lines[1])
        self.assertIn("All day: Trip", lines[2])
        self.assertTrue(lines[3].endswith(": free"))

    def test_same_day_entries_are_sorted_with_all_day_first(self):
        today = date.today()
        late = datetime.combine(today, time(18)).astimezone()
        early = datetime.combine(today, time(9)).astimezone()
        events = [
            {"title": "Dinner", "start": late, "end": late + timedelta(hours=1)},
            {"title": "Standup", "start": early, "end": early + timedelta(minutes=15)},
            {"title": "Holiday", "start": today, "end": today + timedelta(days=1), "all_day": True},
        ]

        line = build_busy_times(events, today, days=1)

        self.assertLess(line.index("Holiday"), line.index("Standup"))
        self.assertLess(line.index("Standup"), line.index("Dinner"))


class SuggestionSectionTests(unittest.TestCase):
    def test_suggestions_are_listed_for_the_model(self):
        today = date.today()
        suggestions = {
            "items": [
                {"kind": "study", "title": "Work on: Essay", "date": today.isoformat(), "start": "12:00", "end": "13:00", "details": "Due Tue"},
                {"kind": "deadline", "title": "Due: Problem set", "date": (today + timedelta(days=1)).isoformat(), "details": "From Prof: PS3"},
                {"kind": "reply", "title": "Reply: Confirm meeting", "date": today.isoformat(), "start": "08:00", "end": "08:15", "details": "From Advisor"},
            ],
            "notices": ["Not enough free time for Thesis"],
        }

        text = build_context({"date": today}, {}, suggestions=suggestions)

        self.assertIn("SUGGESTED WORK SESSIONS", text)
        self.assertIn("12:00–13:00 Work on: Essay (Due Tue)", text)
        self.assertIn("DEADLINES FOUND IN EMAIL", text)
        self.assertIn("Due: Problem set (From Prof: PS3)", text)
        self.assertIn("EMAILS WAITING FOR A REPLY", text)
        self.assertIn("NOT ENOUGH TIME", text)

    def test_no_suggestion_sections_without_suggestions(self):
        text = build_context({"date": date.today()}, {})
        self.assertNotIn("SUGGESTED WORK SESSIONS", text)
        self.assertNotIn("DEADLINES FOUND IN EMAIL", text)


if __name__ == "__main__":
    unittest.main()
