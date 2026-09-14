import unittest
from datetime import date, datetime, time, timedelta, timezone

from core import timeutil


class TimeutilTests(unittest.TestCase):
    def tearDown(self):
        timeutil.configure(None)

    def test_configured_zone_is_local_time(self):
        timeutil.configure("Asia/Tokyo")

        self.assertEqual(timeutil.now().utcoffset(), timedelta(hours=9))
        self.assertEqual(timeutil.to_utc(datetime(2026, 9, 13, 9, 0)), datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(timeutil.wall_clock(datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)), "2026-09-13T09:00:00")
        self.assertEqual(timeutil.local_day(datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc)), date(2026, 9, 14))

    def test_each_day_gets_its_own_offset(self):
        timeutil.configure("America/New_York")
        self.assertEqual(timeutil.at(date(2026, 7, 1), time(8)).utcoffset(), timedelta(hours=-4))
        self.assertEqual(timeutil.at(date(2026, 12, 1), time(8)).utcoffset(), timedelta(hours=-5))

    def test_plain_dates_mean_local_midnight(self):
        timeutil.configure("America/New_York")
        self.assertEqual(timeutil.to_utc(date(2026, 12, 1)), datetime(2026, 12, 1, 5, 0, tzinfo=timezone.utc))
        self.assertEqual(timeutil.local_day(date(2026, 12, 1)), date(2026, 12, 1))

    def test_machine_zone_by_default(self):
        naive = datetime(2026, 9, 13, 9, 0)
        self.assertEqual(timeutil.to_local(naive), naive.astimezone())
        self.assertEqual(timeutil.today(), date.today())

    def test_unknown_zone_is_a_readable_error(self):
        with self.assertRaisesRegex(ValueError, "America/New_York"):
            timeutil.configure("Mars/Olympus_Mons")

    def test_small_helpers(self):
        self.assertEqual(timeutil.twelve_hour("23:59"), "11:59 PM")
        self.assertEqual(timeutil.twelve_hour("08:05"), "8:05 AM")
        self.assertEqual(timeutil.twelve_hour("soon"), "soon")
        self.assertIsNone(timeutil.to_utc("not a date"))
        self.assertIsNone(timeutil.local_day(None))


if __name__ == "__main__":
    unittest.main()
