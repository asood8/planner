import unittest
from datetime import datetime, timedelta, timezone

from core.estimates import Calibration, describe, estimate_for, format_minutes, learn, measure_actual
from core.settings import StudyBlocks

NOW = datetime(2026, 9, 14, 10, 30, tzinfo=timezone.utc)


def _done(list_name, estimate, actual):
    return {"key": f"{list_name}-{estimate}-{actual}", "title": "Task", "list": list_name, "estimate": estimate, "actual": actual}


class LearnTests(unittest.TestCase):
    def test_nothing_changes_before_three_finished_tasks(self):
        calibration = learn([_done("School", 60, 120), _done("School", 60, 120)])
        self.assertEqual(calibration.by_list, {})
        self.assertEqual(calibration.multiplier_for("School"), (1.0, None))

    def test_small_samples_are_pulled_toward_one(self):
        calibration = learn([_done("School", 60, 120)] * 3)

        multiplier, samples = calibration.by_list["School"]
        self.assertAlmostEqual(multiplier, 2 ** 0.6)  # three 2x tasks plus two 1x pseudo-samples
        self.assertEqual(samples, 3)
        self.assertEqual(calibration.multiplier_for("School")[1], "School tasks")

    def test_other_lists_fall_back_to_all_tasks(self):
        calibration = learn([_done("A", 60, 30)] * 2 + [_done("B", 60, 30)] * 2)

        self.assertEqual(calibration.by_list, {})
        multiplier, source = calibration.multiplier_for("C")
        self.assertAlmostEqual(multiplier, 0.5 ** (4 / 6))
        self.assertEqual(source, "your tasks")

    def test_multiplier_is_clamped(self):
        self.assertEqual(learn([_done("School", 10, 600)] * 10).by_list["School"][0], 2.5)
        self.assertEqual(learn([_done("School", 600, 10)] * 10).by_list["School"][0], 0.5)

    def test_entries_without_both_numbers_are_ignored(self):
        entries = [
            {"key": "a", "list": "School", "estimate": 60},
            {"key": "b", "list": "School", "actual": 60},
            {"key": "c", "list": "School", "estimate": 0, "actual": 60},
            {"key": "d", "list": "School", "estimate": "60", "actual": "90"},
        ]
        self.assertEqual(learn(entries), Calibration())


class EstimateForTests(unittest.TestCase):
    def test_learned_multiplier_is_applied_and_rounded(self):
        calibration = learn([_done("School", 60, 90)] * 3)  # 1.5x each, about 1.28x after the pull toward 1x

        estimate = estimate_for({"title": "Essay ~2h", "list": "School"}, StudyBlocks(), calibration)

        self.assertEqual((estimate.minutes, estimate.base, estimate.from_task), (150, 120, True))
        self.assertEqual(
            estimate.note(),
            "About 2 h 30 min in total: you estimated 2 h, adjusted because School tasks have taken 1.3× as long as planned",
        )

    def test_default_estimate_without_learning(self):
        estimate = estimate_for({"title": "Essay"}, StudyBlocks(), Calibration())
        self.assertEqual((estimate.minutes, estimate.base, estimate.from_task), (60, 60, False))
        self.assertEqual(estimate.note(), "About 1 h in total (the default is 1 h)")

    def test_learning_can_be_turned_off(self):
        calibration = learn([_done("School", 60, 120)] * 3)
        estimate = estimate_for({"title": "Essay", "list": "School"}, StudyBlocks(learn_estimates=False), calibration)
        self.assertEqual(estimate.minutes, 60)


class DescribeTests(unittest.TestCase):
    def test_lines_for_the_sidebar(self):
        self.assertEqual(describe(Calibration()), [])
        self.assertEqual(
            describe(learn([_done("School", 60, 90)])),
            ["1 finished task measured so far. Estimates start adjusting after 3."],
        )
        self.assertEqual(
            describe(learn([_done("School", 60, 120)] * 3)),
            ["School tasks have taken 1.5× as long as planned (3 finished)"],
        )
        self.assertEqual(
            describe(learn([_done("School", 60, 120)] * 3 + [_done("Work", 60, 120)])),
            [
                "School tasks have taken 1.5× as long as planned (3 finished)",
                "All tasks: 1.6× as long as planned (4 finished)",
            ],
        )

    def test_format_minutes(self):
        self.assertEqual([format_minutes(m) for m in (45, 60, 150)], ["45 min", "1 h", "2 h 30 min"])


class MeasureActualTests(unittest.TestCase):
    def _session(self, start, minutes, ref="study:t1"):
        return {"start": start, "end": start + timedelta(minutes=minutes), "ref": ref}

    def test_counts_sessions_that_had_started(self):
        events = [
            self._session(NOW - timedelta(days=1), 90),  # yesterday: all 90 minutes
            self._session(NOW - timedelta(minutes=30), 60),  # in progress: 30 minutes so far
            self._session(NOW + timedelta(hours=2), 60),  # hasn't started
            self._session(NOW - timedelta(hours=5), 60, ref="study:other"),
            {"start": NOW.date(), "end": NOW.date() + timedelta(days=1), "ref": "study:t1"},  # all-day
        ]
        self.assertEqual(measure_actual("t1", events, NOW), 120)
        self.assertEqual(measure_actual("t1", [], NOW), 0)


if __name__ == "__main__":
    unittest.main()
