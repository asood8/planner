import unittest
from datetime import date, datetime, time, timedelta, timezone
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

    def test_overlapping_events_are_flagged(self):
        today = date.today()
        lecture = _event("Lecture", today, 10)
        meeting = _event("Meeting", today, 10)
        meeting["start"] += timedelta(minutes=30)
        meeting["end"] += timedelta(minutes=30)
        day_context = {"date": today, "events": [lecture, meeting, _event("Gym", today, 14)]}

        events = to_fullcalendar_events(day_context, {})

        flagged = sorted(event["title"] for event in events if event.get("extendedProps", {}).get("conflict"))
        self.assertEqual(flagged, ["Lecture", "Meeting"])
        self.assertEqual(next(event for event in events if event["title"] == "Lecture")["classNames"], ["has-conflict"])

    def test_suggestions_render_as_dashed_entries_and_absorb_matching_plan_blocks(self):
        today = date.today()
        study = {"ref": "study:t1", "kind": "study", "title": "Work on: Essay", "date": today.isoformat(),
                 "start": "12:00", "end": "13:00", "all_day": False, "details": "Due Tue"}
        deadline = {"ref": "deadline:e1:0", "kind": "deadline", "title": "Due: PS3", "date": today.isoformat(),
                    "start": None, "end": None, "all_day": True, "details": "From Prof"}

        events = to_fullcalendar_events({"date": today}, {}, "- 12:00 PM - 1:00 PM Work on: Essay", [], [study, deadline])

        by_title = {event["title"]: event for event in events}
        self.assertNotIn("plan", [event["category"] for event in events])
        self.assertEqual(by_title["Work on: Essay"]["start"], f"{today.isoformat()}T12:00:00")
        self.assertEqual(by_title["Work on: Essay"]["classNames"], ["suggestion"])
        self.assertEqual(by_title["Work on: Essay"]["extendedProps"]["suggestion"], study)
        self.assertTrue(by_title["Due: PS3"]["allDay"])

    def test_task_entries_carry_their_key_and_due_time(self):
        today = date.today()
        task = {"id": "ical:1", "title": "HW 3", "notes": "", "due": datetime.combine(today, time.min, tzinfo=timezone.utc),
                "due_time": "23:59", "list": "Canvas", "source": "ical"}

        (entry,) = to_fullcalendar_events({"date": today, "tasks_due_today": [task]}, {})

        self.assertEqual(entry["title"], "Task: HW 3 (due 11:59 PM)")
        self.assertEqual((entry["extendedProps"]["key"], entry["extendedProps"]["source"]), ("ical:1", "task"))
        self.assertEqual(entry["extendedProps"]["details"], "From Canvas")

    def test_saved_events_and_timed_suggestions_are_draggable(self):
        today = date.today()
        gym = dict(_event("Gym", today, 18), source="ask_ai", id="a")
        due = {"title": "Due", "start": today, "end": today + timedelta(days=1), "all_day": True, "source": "ask_ai", "id": "b"}
        study = {"ref": "study:t1", "kind": "study", "title": "Work on: Essay", "date": today.isoformat(),
                 "start": "12:00", "end": "13:00", "all_day": False, "details": ""}
        deadline = {"ref": "deadline:e1:0", "kind": "deadline", "title": "Due: PS3", "date": today.isoformat(),
                    "start": None, "end": None, "all_day": True, "details": ""}

        events = to_fullcalendar_events({"date": today, "events": [gym, due, _event("Lecture", today, 8)]}, {}, None, [], [study, deadline])

        by_title = {event["title"]: event for event in events}
        self.assertTrue(by_title["Gym"]["editable"])
        self.assertEqual((by_title["Due"]["editable"], by_title["Due"]["durationEditable"]), (True, False))
        self.assertNotIn("editable", by_title["Lecture"])
        self.assertTrue(by_title["Work on: Essay"]["editable"])
        self.assertFalse(by_title["Due: PS3"]["editable"])

    def test_saved_sessions_carry_their_ref_and_check_in(self):
        start = datetime.combine(date.today(), time(9)).astimezone()
        session = {
            "title": "Work on: Essay", "start": start, "end": start + timedelta(hours=1), "source": "ask_ai",
            "id": "e1", "batch": "b1", "ref": "study:t1", "status": "skipped",
        }

        (entry,) = [e for e in to_fullcalendar_events({"date": date.today(), "events": [session]}, {}, None, []) if e.get("category") == "ask_ai"]

        self.assertEqual((entry["extendedProps"]["ref"], entry["extendedProps"]["status"]), ("study:t1", "skipped"))
        self.assertTrue(entry["extendedProps"]["details"].startswith("Skipped."))

    def test_reply_suggestion_does_not_hide_a_plan_block_at_the_same_time(self):
        today = date.today()
        reply = {"ref": "reply:e1:0", "kind": "reply", "title": "Reply: RSVP", "date": today.isoformat(),
                 "start": "09:00", "end": "09:15", "all_day": False, "details": ""}

        events = to_fullcalendar_events({"date": today}, {}, "- 9:00 AM - 10:30 AM Problem set 4", [], [reply])

        self.assertEqual(sorted(event["title"] for event in events), ["Problem set 4", "Reply: RSVP"])


if __name__ == "__main__":
    unittest.main()
