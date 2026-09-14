import json
import tempfile
import unittest
from pathlib import Path

from core.settings import ConfigError, Feed, Settings, StudyBlocks, UserProfile, load_settings, settings_from_dict

ROOT = Path(__file__).resolve().parent.parent


class LoadSettingsTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.path = Path(temp_dir.name) / "config.json"

    def _load(self, data):
        self.path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return load_settings(self.path)

    def test_missing_file_means_defaults(self):
        self.assertEqual(load_settings(self.path), Settings())

    def test_the_example_config_is_valid(self):
        settings = load_settings(ROOT / "config.example.json")
        self.assertEqual(settings.timezone, "America/New_York")
        self.assertEqual(settings.ical_feeds, ())  # the example's feed has a blank URL

    def test_values_are_read_and_normalized(self):
        settings = self._load({
            "model": "qwen2.5:7b",
            "timezone": "Europe/London",
            "calendar_days_ahead": 7,
            "max_emails": "5",
            "include_gmail": False,
            "user_context": "  CS and Finance student  ",
            "user_profile": {"workday_start": 9, "workday_end": 24, "sleep_time": "11 PM", "recurring_commitments": ["Gym", " "]},
            "study_blocks": {"days_ahead": 5},
            "output_mode": "browser",
        })

        self.assertEqual(settings, Settings(
            model="qwen2.5:7b",
            timezone="Europe/London",
            calendar_days_ahead=7,
            max_emails=5,
            include_gmail=False,
            user_context="CS and Finance student",
            user_profile=UserProfile(sleep_time="11 PM", recurring_commitments=("Gym",), workday_start=9, workday_end=24),
            study_blocks=StudyBlocks(days_ahead=5),
        ))

    def test_bad_values_name_the_setting(self):
        cases = [
            ({"user_profile": {"workday_start": "8am"}}, "user_profile.workday_start must be an hour from 0 to 24 (got '8am')"),
            ({"user_profile": {"workday_start": 18, "workday_end": 9}}, "must be earlier than workday_end"),
            ({"include_gmail": "yes"}, "include_gmail must be true or false"),
            ({"timezone": "Mars/Base"}, "timezone: unknown time zone 'Mars/Base'"),
            ({"max_emails": 1000}, "max_emails must be a whole number from 0 to 100"),
            ({"study_blocks": [1]}, "study_blocks must be an object"),
            ({"study_blocks": {"preferred_hours": [9]}}, "study_blocks.preferred_hours must be two hours like [9, 21]"),
            ({"study_blocks": {"preferred_hours": [21, 9]}}, "study_blocks.preferred_hours must start before it ends"),
            ({"study_blocks": {"max_minutes_per_day": 5}}, "study_blocks.max_minutes_per_day must be a whole number from 15 to 960"),
            ({"study_blocks": {"learn_estimates": "no"}}, "study_blocks.learn_estimates must be true or false"),
            ({"user_profile": {"recurring_commitments": [1, 2]}}, "recurring_commitments must be a list of text"),
            (["not", "an", "object"], "must be a JSON object"),
            ("{not json", "isn't valid JSON"),
        ]
        for data, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(ConfigError) as caught:
                    self._load(data)
                self.assertIn(message, str(caught.exception))


class StudySettingsTests(unittest.TestCase):
    def test_scheduler_settings_are_read(self):
        settings = settings_from_dict({"study_blocks": {"max_minutes_per_day": 180, "preferred_hours": [10, 20], "learn_estimates": False}})
        self.assertEqual(
            settings.study_blocks,
            StudyBlocks(max_minutes_per_day=180, preferred_start=10, preferred_end=20, learn_estimates=False),
        )


class FeedSettingsTests(unittest.TestCase):
    def test_feeds_are_normalized(self):
        settings = settings_from_dict({"ical_feeds": [
            "webcal://example.com/a.ics",
            {"name": "Canvas", "url": "https://canvas.example.edu/feed.ics"},
            {"name": "Empty", "url": ""},
        ]})
        self.assertEqual(settings.ical_feeds, (
            Feed("Feed 1", "https://example.com/a.ics"),
            Feed("Canvas", "https://canvas.example.edu/feed.ics"),
        ))

    def test_feed_urls_stay_out_of_errors_and_reprs(self):
        with self.assertRaises(ConfigError) as caught:
            settings_from_dict({"ical_feeds": ["ftp://secret.example/token123"]})
        self.assertNotIn("token123", str(caught.exception))

        settings = settings_from_dict({"ical_feeds": ["https://canvas.example.edu/feeds/token123.ics"]})
        self.assertNotIn("token123", repr(settings))

    def test_entries_must_be_urls_or_objects(self):
        with self.assertRaises(ConfigError):
            settings_from_dict({"ical_feeds": [42]})


if __name__ == "__main__":
    unittest.main()
