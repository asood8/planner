import unittest
from datetime import date, datetime, time, timedelta, timezone
from unittest import mock

import requests

from core.settings import Feed, Settings
from fetch import ical
from fetch.ical import fetch_feeds, parse_feed


def _stamp(moment):
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sample_feed(today):
    """A Canvas-style feed: one assignment, a daily lecture, a two-day break, and an assignment due far away."""
    due = datetime.combine(today + timedelta(days=2), time(23, 59)).astimezone()
    lecture = datetime.combine(today + timedelta(days=1), time(14, 0)).astimezone()
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Planner tests//EN",
        "BEGIN:VEVENT", "UID:event-assignment-101", "SUMMARY:Problem Set 3 [CS 101]",
        f"DTSTART:{_stamp(due)}", f"DTEND:{_stamp(due)}", "DESCRIPTION:Submit on Canvas", "END:VEVENT",
        "BEGIN:VEVENT", "UID:event-calendar-event-7", "SUMMARY:CS 101 Lecture",
        f"DTSTART:{_stamp(lecture)}", f"DTEND:{_stamp(lecture + timedelta(hours=1))}",
        "RRULE:FREQ=DAILY;COUNT=3", "LOCATION:Room 12", "END:VEVENT",
        "BEGIN:VEVENT", "UID:break-1", "SUMMARY:Fall Break",
        f"DTSTART;VALUE=DATE:{today + timedelta(days=3):%Y%m%d}",
        f"DTEND;VALUE=DATE:{today + timedelta(days=5):%Y%m%d}", "END:VEVENT",
        "BEGIN:VEVENT", "UID:event-assignment-202", "SUMMARY:Final Project",
        f"DTSTART;VALUE=DATE:{today + timedelta(days=60):%Y%m%d}", "END:VEVENT",
        "END:VCALENDAR", "",
    ]
    return "\r\n".join(lines), due, lecture


class ParseFeedTests(unittest.TestCase):
    def setUp(self):
        self.today = date.today()
        self.feed, self.due, self.lecture = _sample_feed(self.today)

    def test_assignments_become_deadlines_and_other_entries_events(self):
        events, deadlines = parse_feed(self.feed, "Canvas", self.today, 14)

        (deadline,) = deadlines  # the Final Project is beyond the deadline window
        self.assertEqual(deadline["id"], "ical:event-assignment-101")
        self.assertEqual(deadline["title"], "Problem Set 3 [CS 101]")
        self.assertEqual(deadline["due"], datetime.combine(self.due.date(), time.min, tzinfo=timezone.utc))
        self.assertEqual(deadline["due_time"], "23:59")
        self.assertEqual((deadline["list"], deadline["source"]), ("Canvas", "ical"))

        lectures = sorted((event for event in events if event["title"] == "CS 101 Lecture"), key=lambda event: event["start"])
        self.assertEqual(len(lectures), 3)
        self.assertEqual(lectures[0]["start"], self.lecture)
        self.assertEqual(lectures[0]["location"], "Room 12")
        (holiday,) = [event for event in events if event["title"] == "Fall Break"]
        self.assertTrue(holiday["all_day"])
        self.assertEqual((holiday["start"], holiday["end"]), (self.today + timedelta(days=3), self.today + timedelta(days=5)))

    def test_events_past_the_calendar_window_are_skipped(self):
        events, deadlines = parse_feed(self.feed, "Canvas", self.today, 1)
        titles = {event["title"] for event in events}
        self.assertIn("CS 101 Lecture", titles)
        self.assertNotIn("Fall Break", titles)
        self.assertEqual(len(deadlines), 1)


class FetchFeedsTests(unittest.TestCase):
    def test_no_feeds_configured(self):
        self.assertEqual(fetch_feeds(Settings()), ([], [], None))

    def test_one_broken_feed_does_not_hide_the_others_or_leak_its_url(self):
        feed, _, _ = _sample_feed(date.today())

        def fake_get(url, timeout):
            if "broken" in url:
                raise requests.exceptions.ConnectionError(f"Max retries exceeded with url: {url}")
            response = mock.Mock()
            response.content = feed.encode()
            return response

        settings = Settings(ical_feeds=(
            Feed("Canvas", "https://ok.example/feed.ics"),
            Feed("Other", "https://broken.example/private-token.ics"),
        ))
        with mock.patch.object(ical.requests, "get", side_effect=fake_get), self.assertLogs("fetch.ical", "WARNING") as logs:
            events, deadlines, ok = fetch_feeds(settings)

        self.assertFalse(ok)
        self.assertEqual(len(deadlines), 1)
        self.assertTrue(events)
        self.assertIn("Calendar feed 'Other' failed: couldn't connect", logs.output[0])
        self.assertNotIn("private-token", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
