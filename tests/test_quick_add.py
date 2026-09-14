import unittest
from datetime import datetime

from core.quick_add import parse_quick_add

# Saturday, September 12, 2026, 10:00 local time.
NOW = datetime(2026, 9, 12, 10, 0).astimezone()


def _parse(text, now=NOW):
    return parse_quick_add(text, now)


class QuickAddTests(unittest.TestCase):
    def test_relative_day_and_time(self):
        self.assertEqual(_parse("gym tomorrow 5pm"), {"date": "2026-09-13", "start": "17:00", "end": "18:00", "title": "Gym"})

    def test_weekday_with_a_range_that_shares_am_pm(self):
        self.assertEqual(
            _parse("Dentist fri 2:30-3:30pm"),
            {"date": "2026-09-18", "start": "14:30", "end": "15:30", "title": "Dentist"},
        )

    def test_duration_is_applied_and_title_words_are_kept(self):
        self.assertEqual(
            _parse("study for exam tomorrow 9am for 2h"),
            {"date": "2026-09-13", "start": "09:00", "end": "11:00", "title": "Study for exam"},
        )

    def test_bare_time_means_the_next_time_it_comes_around(self):
        self.assertEqual(_parse("lunch with Sam at noon"), {"date": "2026-09-12", "start": "12:00", "end": "13:00", "title": "Lunch with Sam"})
        self.assertEqual(_parse("lunch with Sam at noon", datetime(2026, 9, 12, 13, 0).astimezone())["date"], "2026-09-13")

    def test_tonight_defaults_to_the_evening(self):
        self.assertEqual(_parse("call mom tonight"), {"date": "2026-09-12", "start": "20:00", "end": "21:00", "title": "Call mom"})

    def test_date_without_a_time_is_all_day(self):
        self.assertEqual(_parse("Project due 9/20"), {"date": "2026-09-20", "all_day": True, "title": "Project due"})
        # A date that has already passed this year means next year.
        self.assertEqual(_parse("Taxes 1/5")["date"], "2027-01-05")

    def test_other_date_formats(self):
        self.assertEqual(
            _parse("meeting 14:00-15:30 on 2026-09-20"),
            {"date": "2026-09-20", "start": "14:00", "end": "15:30", "title": "Meeting"},
        )
        self.assertEqual(
            _parse("sep 25 career fair 10am-2pm"),
            {"date": "2026-09-25", "start": "10:00", "end": "14:00", "title": "Career fair"},
        )
        self.assertEqual(
            _parse("next mon standup 9:15am for 15m"),
            {"date": "2026-09-14", "start": "09:15", "end": "09:30", "title": "Standup"},
        )
        self.assertEqual(_parse("Sunday brunch 11am")["date"], "2026-09-13")

    def test_range_crossing_noon(self):
        self.assertEqual(_parse("11-1pm lunch"), {"date": "2026-09-12", "start": "11:00", "end": "13:00", "title": "Lunch"})

    def test_time_alone_gets_a_default_title(self):
        self.assertEqual(_parse("5pm")["title"], "Event")

    def test_no_date_or_time_returns_none(self):
        self.assertIsNone(_parse("hw 3"))
        self.assertIsNone(_parse("stretch every morning"))

    def test_impossible_input_raises(self):
        with self.assertRaises(ValueError):
            _parse("movie 11pm for 3h")
        with self.assertRaises(ValueError):
            _parse("Read 2/30")


if __name__ == "__main__":
    unittest.main()
