import unittest

from server import _build_fallback_event_lines


class ServerFallbackTests(unittest.TestCase):
    def test_daily_gym_fallback_creates_event_lines(self):
        text = "Reminder to go to the gym daily at 2 PM, as scheduled in your permanent plans."
        prompt = "Permanent note:\nI go to the gym daily at 2 PM\n"

        lines = _build_fallback_event_lines(prompt, text)

        self.assertTrue(lines)
        self.assertIn("[", lines[0])
        self.assertIn("Gym", lines[0])
        self.assertTrue(any("[02:00 PM] - Gym" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
