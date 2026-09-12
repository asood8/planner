import unittest
from datetime import datetime, timezone
from unittest import mock

from fetch import calendar as calendar_fetch
from fetch import tasks as tasks_fetch
from fetch.gmail import _parse_received


class CalendarFetchTests(unittest.TestCase):
    def test_mixed_all_day_and_timed_events_sort_across_pages(self):
        pages = [
            {
                "items": [{
                    "summary": "Class",
                    "start": {"dateTime": "2026-09-14T10:00:00-04:00"},
                    "end": {"dateTime": "2026-09-14T11:00:00-04:00"},
                }],
                "nextPageToken": "page-2",
            },
            {"items": [{"summary": "Holiday", "start": {"date": "2026-09-14"}, "end": {"date": "2026-09-15"}}]},
        ]
        service = mock.MagicMock()
        service.events.return_value.list.return_value.execute.side_effect = pages

        with mock.patch.object(calendar_fetch, "build", return_value=service):
            events = calendar_fetch.get_events(creds=object(), days_ahead=7)

        self.assertEqual([event["title"] for event in events], ["Holiday", "Class"])
        self.assertEqual(service.events.return_value.list.call_count, 2)
        class_start = events[1]["start"]
        self.assertIsNotNone(class_start.tzinfo)
        self.assertEqual(class_start.astimezone(timezone.utc), datetime(2026, 9, 14, 14, tzinfo=timezone.utc))


class TasksFetchTests(unittest.TestCase):
    def test_follows_page_tokens_and_skips_completed(self):
        service = mock.MagicMock()
        service.tasklists.return_value.list.return_value.execute.return_value = {"items": [{"id": "L1", "title": "Inbox"}]}
        service.tasks.return_value.list.return_value.execute.side_effect = [
            {"items": [{"title": "A"}], "nextPageToken": "page-2"},
            {"items": [{"title": "B", "status": "completed"}, {"title": "C", "due": "2026-09-20T00:00:00.000Z"}]},
        ]

        with mock.patch.object(tasks_fetch, "build", return_value=service):
            grouped = tasks_fetch.get_tasks(creds=object())

        titles = sorted(task["title"] for bucket in grouped.values() for task in bucket)
        self.assertEqual(titles, ["A", "C"])


class GmailDateTests(unittest.TestCase):
    def test_parses_header_with_trailing_zone_comment(self):
        self.assertEqual(
            _parse_received("Fri, 11 Sep 2026 14:03:00 +0000 (UTC)", None),
            datetime(2026, 9, 11, 14, 3, tzinfo=timezone.utc),
        )

    def test_parses_named_gmt_zone(self):
        self.assertEqual(
            _parse_received("Fri, 11 Sep 2026 14:03:00 GMT", None),
            datetime(2026, 9, 11, 14, 3, tzinfo=timezone.utc),
        )

    def test_falls_back_to_internal_date(self):
        self.assertEqual(
            _parse_received("garbage", "1789000000000"),
            datetime.fromtimestamp(1789000000, tz=timezone.utc),
        )

    def test_returns_none_when_nothing_parses(self):
        self.assertIsNone(_parse_received("", None))


if __name__ == "__main__":
    unittest.main()
