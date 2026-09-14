import unittest
from datetime import date, datetime, time, timedelta

from core.exam_prep import exam_candidates, exam_ref, is_exam
from core.settings import ExamPrep

TODAY = date(2026, 9, 14)  # a Monday


def _day(offset):
    return TODAY + timedelta(days=offset)


def _event(title, day_offset, description=""):
    start = datetime.combine(_day(day_offset), time(10)).astimezone()
    return {"title": title, "start": start, "end": start + timedelta(hours=2), "description": description}


class IsExamTests(unittest.TestCase):
    def test_exam_titles(self):
        for title in ("Midterm 1", "CS 101 Final Exam", "Quiz 3", "Finals", "Econ test", "Exams"):
            with self.subTest(title=title):
                self.assertTrue(is_exam(title))

    def test_things_that_only_mention_exams(self):
        for title in ("Midterm review session", "Final project due", "Practice exam", "Exam prep with Sam",
                      "Office hours", "Test drive", "Lecture", "Contest"):
            with self.subTest(title=title):
                self.assertFalse(is_exam(title))


class ExamCandidatesTests(unittest.TestCase):
    def test_review_is_spread_over_the_days_before(self):
        (candidate,) = exam_candidates([_event("Midterm  1", 7)], TODAY, ExamPrep(), {}, set())

        self.assertEqual(candidate["key"], "exam:midterm 1|2026-09-21")
        self.assertEqual(
            (candidate["kind"], candidate["due"], candidate["last_day"], candidate["remaining"], candidate["day_cap"]),
            ("exam", _day(7), _day(6), 240, 60),
        )
        # Four hour-long sessions over the seven days before, ending the day before the exam.
        self.assertEqual(candidate["target_days"], [_day(1), _day(3), _day(5), _day(6)])
        self.assertEqual(candidate["note"], "About 4 h of review in total, spread over the days before")

    def test_quizzes_estimates_and_short_notice(self):
        quiz, final = exam_candidates([_event("Final exam", 2, "Covers everything ~6h"), _event("Quiz 3", 1)], TODAY, ExamPrep(), {}, set())

        self.assertEqual((quiz["remaining"], quiz["day_cap"], quiz["target_days"]), (60, 60, [TODAY]))
        # Six hours with two days left can't be an hour a day, so each day takes half.
        self.assertEqual((final["remaining"], final["day_cap"], final["target_days"]), (360, 180, [_day(0), _day(1)]))

    def test_accepted_review_counts_and_duplicates_count_once(self):
        ref = exam_ref("Midterm", _day(4))
        (candidate,) = exam_candidates([_event("Midterm", 4), _event("midterm", 4)], TODAY, ExamPrep(), {ref: 180}, set())
        self.assertEqual(candidate["remaining"], 60)

    def test_skips_today_far_off_dismissed_saved_and_finished_exams(self):
        events = [
            _event("Midterm", 0),
            _event("Midterm", 9),
            _event("Econ test", 3),
            {**_event("Quiz 1", 2), "source": "ask_ai"},
            _event("Final exam", 4),
        ]
        dismissed = {exam_ref("Econ test", _day(3))}
        accepted = {exam_ref("Final exam", _day(4)): 240}
        self.assertEqual(exam_candidates(events, TODAY, ExamPrep(), accepted, dismissed), [])

    def test_can_be_turned_off(self):
        self.assertEqual(exam_candidates([_event("Midterm", 3)], TODAY, ExamPrep(days_before=0), {}, set()), [])


if __name__ == "__main__":
    unittest.main()
