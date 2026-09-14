import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest import mock

import requests

import server
from core import done_tasks, local_store, plan_history, saved_events
from core import settings as settings_module
from core.settings import Settings

TEST_SETTINGS = Settings()


def _ollama_response(body):
    response = mock.Mock()
    response.json.return_value = {"response": body}
    return response


def _event_today(title, hour):
    start = datetime.combine(date.today(), time(hour)).astimezone()
    return {"title": title, "start": start, "end": start + timedelta(hours=1), "all_day": False}


def _task(title, days_from_today, task_id):
    due = datetime.combine(date.today() + timedelta(days=days_from_today), time.min, tzinfo=timezone.utc)
    return {"id": task_id, "title": title, "notes": "", "due": due, "list": "School"}


def _email(email_id, subject):
    return {"id": email_id, "sender": "Prof", "subject": subject, "snippet": "", "date": datetime.now(timezone.utc)}


class ServerTestCase(unittest.TestCase):
    """Isolates each test from Google, config.json, the Google cache, and the real data/ files."""

    patch_settings = True

    def setUp(self):
        self.client = server.app.test_client()
        server._google_cache.clear()
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.data_dir = Path(temp_dir.name)
        self._patch(local_store, "DATA_DIR", self.data_dir)
        self._patch(server, "_config_problem", None)
        if self.patch_settings:
            self.load_settings = self._patch(server, "_load_settings", return_value=TEST_SETTINGS)
        self.status = {"calendar_ok": True, "tasks_ok": True, "gmail_ok": True}
        self.get_credentials = self._patch(server, "get_credentials", return_value=object())
        self.fetch_sources = self._patch(server, "fetch_sources", return_value=([], [], [], self.status))

    def _patch(self, *args, **kwargs):
        patcher = mock.patch.object(*args, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def _set_google(self, events=(), tasks=(), emails=(), status=None):
        self.fetch_sources.return_value = (list(events), list(tasks), list(emails), status or self.status)

    def _api_events(self):
        return self.client.get("/api/events").get_json()["events"]

    def _suggestions(self):
        return [event["extendedProps"]["suggestion"] for event in self._api_events() if event.get("category") == "suggestion"]


class GenerateEndpointTests(ServerTestCase):
    def _generate(self, body, prompt="Permanent note:\nI go to the gym daily at 2 PM"):
        with mock.patch.object(server.requests, "post", return_value=_ollama_response(body)) as post:
            result = self.client.post("/generate", json={"prompt": prompt})
        return result, post

    def _gym_body(self):
        return json.dumps({"events": [{"date": date.today().isoformat(), "start": "14:00", "end": "15:00", "title": "Gym"}]})

    def test_prompt_has_system_prompt_model_and_existing_calendar(self):
        self._set_google(events=[_event_today("CS Lecture", 10)])

        result, post = self._generate('{"events": []}')

        self.assertEqual(result.status_code, 200)
        sent = post.call_args.kwargs["json"]
        self.assertIn("calendar events", server.SYSTEM_PROMPT)
        self.assertTrue(sent["prompt"].startswith(server.SYSTEM_PROMPT))
        self.assertIn("EXISTING CALENDAR", sent["prompt"])
        self.assertIn("10:00–11:00 CS Lecture", sent["prompt"])
        self.assertEqual(sent["model"], "phi4-mini:3.8b")

    def test_events_are_saved_with_ids_and_duplicates_skipped(self):
        first = self._generate(self._gym_body())[0].get_json()
        self.assertEqual(len(first["events"]), 1)
        self.assertTrue(first["events"][0]["id"])
        self.assertEqual(len(saved_events.load_saved_events()), 1)

        second = self._generate(self._gym_body())[0].get_json()
        self.assertEqual(second, {"events": [], "skipped": 1})

    def test_model_cannot_mark_events_as_accepted_suggestions(self):
        body = json.dumps({"events": [
            {"date": date.today().isoformat(), "start": "14:00", "end": "15:00", "title": "Gym", "ref": "study:t1"}
        ]})
        self._generate(body)
        self.assertNotIn("ref", saved_events.load_saved_events()[0])

    def test_saved_events_count_as_existing_calendar(self):
        self._generate(self._gym_body())
        _, post = self._generate('{"events": []}')
        self.assertIn("14:00–15:00 Gym", post.call_args.kwargs["json"]["prompt"])

    def test_missing_prompt_is_rejected(self):
        self.assertEqual(self.client.post("/generate", json={}).status_code, 400)

    def test_unreachable_ollama_returns_502(self):
        with mock.patch.object(server.requests, "post", side_effect=requests.exceptions.ConnectionError()):
            result = self.client.post("/generate", json={"prompt": "gym at 2pm"})
        self.assertEqual(result.status_code, 502)

    def test_malformed_model_output_yields_no_events(self):
        result, _ = self._generate("not json")
        self.assertEqual(result.get_json(), {"events": [], "skipped": 0})

    def test_still_works_when_google_sign_in_fails(self):
        self.get_credentials.side_effect = FileNotFoundError("credentials.json missing")
        result, _ = self._generate(self._gym_body())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.get_json()["events"]), 1)


class EventsEndpointTests(ServerTestCase):
    def test_delete_single_event_then_rest_of_batch(self):
        today = date.today().isoformat()
        saved = saved_events.add_saved_events(
            [{"date": today, "start": f"{hour}:00", "end": f"{hour}:30", "title": f"Block {hour}"} for hour in (9, 10, 11)]
        )

        self.assertEqual(self.client.delete(f"/events/{saved[0]['id']}").get_json(), {"removed": 1})
        self.assertEqual(self.client.delete(f"/events/{saved[1]['id']}?batch=1").get_json(), {"removed": 2})
        self.assertEqual(saved_events.load_saved_events(), [])

    def test_unknown_event_is_404(self):
        self.assertEqual(self.client.delete("/events/nope").status_code, 404)


class IndexTests(ServerTestCase):
    def test_renders_fetched_google_data(self):
        self._set_google(events=[_event_today("CS Lecture", 10)], status={"calendar_ok": True, "tasks_ok": True, "gmail_ok": None})

        with mock.patch.object(server, "_configured_model", return_value="test-model:1b"):
            html = self.client.get("/").get_data(as_text=True)

        self.assertIn("CS Lecture", html)
        self.assertIn(f'"{date.today().isoformat()}T10:00:00"', html)
        self.assertIn('"test-model:1b"', html)
        self.assertIn('title="Calendar: connected"', html)
        self.assertIn('title="Gmail: not loaded"', html)
        self.assertIn('id="plan-btn"', html)
        self.assertIn('id="model-select"', html)
        self.assertIn('href="/?refresh=1"', html)

    def test_saved_events_are_rendered(self):
        saved_events.add_saved_events([{"date": date.today().isoformat(), "start": "14:00", "end": "15:00", "title": "Gym"}])
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('"source": "ask_ai"', html)
        self.assertIn('"title": "Gym"', html)

    def test_notices_for_tasks_that_do_not_fit(self):
        self._set_google(tasks=[_task("Thesis ~20h", 0, "t9")])
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("min short", html)

    def test_google_data_is_cached_until_refresh(self):
        self.client.get("/")
        self.client.get("/")
        self.assertEqual(self.fetch_sources.call_count, 1)

        response = self.client.get("/?refresh=1")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.fetch_sources.call_count, 2)

    def test_failed_sources_are_not_cached(self):
        self._set_google(status={"calendar_ok": False, "tasks_ok": True, "gmail_ok": True})
        self.client.get("/")
        self.client.get("/")
        self.assertEqual(self.fetch_sources.call_count, 2)

    def test_sign_in_failure_still_renders_page(self):
        self.get_credentials.side_effect = FileNotFoundError("credentials.json <missing>")

        response = self.client.get("/")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.fetch_sources.assert_not_called()
        self.assertIn('title="Calendar: fetch failed"', html)
        self.assertIn("credentials.json &lt;missing&gt;", html)

    def test_python_sources_in_output_are_not_served(self):
        self.assertEqual(self.client.get("/calendar_formatter.py").status_code, 404)
        self.assertEqual(self.client.get("/static/calendar_formatter.py").status_code, 404)


class ApiEventsTests(ServerTestCase):
    def test_returns_events_and_notices(self):
        self._set_google(events=[_event_today("CS Lecture", 10)])
        data = self.client.get("/api/events").get_json()
        self.assertIn("CS Lecture", [event["title"] for event in data["events"]])
        self.assertEqual(data["notices"], [])

    def test_overlapping_events_are_flagged(self):
        self._set_google(events=[_event_today("Lecture", 10), _event_today("Meeting", 10), _event_today("Gym", 14)])
        flagged = [event["title"] for event in self._api_events() if event.get("extendedProps", {}).get("conflict")]
        self.assertEqual(sorted(flagged), ["Lecture", "Meeting"])


class OllamaStatusTests(ServerTestCase):
    def test_running_lists_models(self):
        response = mock.Mock()
        response.json.return_value = {"models": [{"name": "qwen2.5:7b"}, {"name": "phi4-mini:3.8b"}]}
        with mock.patch.object(server.requests, "get", return_value=response):
            data = self.client.get("/ollama/status").get_json()
        self.assertEqual(data, {"running": True, "models": ["phi4-mini:3.8b", "qwen2.5:7b"], "default": "phi4-mini:3.8b"})

    def test_not_running(self):
        with mock.patch.object(server.requests, "get", side_effect=requests.exceptions.ConnectionError()):
            data = self.client.get("/ollama/status").get_json()
        self.assertEqual(data, {"running": False, "models": [], "default": "phi4-mini:3.8b"})


class SuggestionEndpointTests(ServerTestCase):
    def test_accepting_a_study_session_saves_it_and_stops_suggesting_it(self):
        self._set_google(tasks=[_task("Essay ~30m", 1, "t1")])
        suggestions = self._suggestions()
        self.assertEqual([item["ref"] for item in suggestions], ["study:t1"])

        response = self.client.post("/suggestions/accept", json={"suggestion": suggestions[0]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(saved_events.load_saved_events()[0]["ref"], "study:t1")
        self.assertEqual(self._suggestions(), [])
        accepted = [event["title"] for event in self._api_events() if event.get("category") == "ask_ai"]
        self.assertEqual(accepted, ["Work on: Essay ~30m"])

    def test_accepting_twice_is_a_conflict(self):
        self._set_google(tasks=[_task("Essay ~30m", 1, "t1")])
        item = self._suggestions()[0]
        self.client.post("/suggestions/accept", json={"suggestion": item})
        self.assertEqual(self.client.post("/suggestions/accept", json={"suggestion": item}).status_code, 409)

    def test_dismissing_a_suggestion_hides_it(self):
        self._set_google(tasks=[_task("Essay ~30m", 1, "t1")])
        self.assertEqual(self.client.post("/suggestions/dismiss", json={"ref": "study:t1"}).status_code, 200)
        self.assertEqual(self._suggestions(), [])

    def test_accept_and_dismiss_validate_input(self):
        self.assertEqual(self.client.post("/suggestions/accept", json={}).status_code, 400)
        self.assertEqual(self.client.post("/suggestions/dismiss", json={}).status_code, 400)

    def test_scan_emails_feeds_deadline_suggestions(self):
        self._set_google(emails=[_email("e1", "Problem set 3 due Friday")])
        due = (date.today() + timedelta(days=2)).isoformat()
        with mock.patch.object(server, "OllamaClient") as client_class:
            client_class.return_value.generate_json.return_value = {
                "items": [{"email_id": "e1", "kind": "deadline", "title": "Problem set 3", "date": due}]
            }
            first = self.client.post("/suggestions/scan-emails", json={"model": "qwen2.5:7b"}).get_json()
            second = self.client.post("/suggestions/scan-emails", json={}).get_json()

        self.assertEqual(first, {"scanned": 1})
        self.assertEqual(second, {"scanned": 0})
        self.assertEqual(client_class.return_value.generate_json.call_args.kwargs["model"], "qwen2.5:7b")
        deadlines = [item for item in self._suggestions() if item["kind"] == "deadline"]
        self.assertEqual([(item["title"], item["date"]) for item in deadlines], [("Due: Problem set 3", due)])

    def test_scan_reports_ollama_errors(self):
        self._set_google(emails=[_email("e1", "Problem set 3 due Friday")])
        with mock.patch.object(server, "OllamaClient") as client_class:
            client_class.return_value.generate_json.side_effect = RuntimeError("Ollama server is not running")
            data = self.client.post("/suggestions/scan-emails", json={}).get_json()
        self.assertEqual(data, {"scanned": 0, "error": "Ollama server is not running"})

    def test_scan_skipped_when_gmail_is_disabled(self):
        self.load_settings.return_value = replace(TEST_SETTINGS, include_gmail=False)
        with mock.patch.object(server, "OllamaClient") as client_class:
            data = self.client.post("/suggestions/scan-emails", json={}).get_json()
        self.assertEqual(data, {"scanned": 0})
        client_class.assert_not_called()


class PlanEndpointTests(ServerTestCase):
    def _stream_plan(self, tokens=None, error=None, payload=None):
        with mock.patch.object(server, "OllamaClient") as client_class:
            iter_generate = client_class.return_value.iter_generate
            if error is not None:
                iter_generate.side_effect = error
            else:
                iter_generate.return_value = iter(tokens)
            response = self.client.post("/plan", json=payload or {"mode": "daily"})
            lines = [json.loads(line) for line in response.get_data(as_text=True).splitlines() if line.strip()]
        return response, lines, iter_generate

    def test_streams_tokens_then_final_plan(self):
        self._set_google(events=[_event_today("CS Lecture", 10)])
        tokens = ["## Daily Plan\n", "- 10:00 AM - 11:00 AM CS Lecture\n", "- 11:00 AM - 12:00 PM Study\n"]

        response, lines, iter_generate = self._stream_plan(tokens)

        self.assertEqual(response.mimetype, "application/x-ndjson")
        self.assertEqual([line["token"] for line in lines[:-1]], tokens)
        final = lines[-1]
        self.assertTrue(final["done"])
        self.assertTrue(final["id"])
        self.assertIn("<li>", final["html"])
        # The lecture is already on the calendar, so only the new block is drawn.
        self.assertEqual([event["title"] for event in final["events"]], ["Study"])
        self.assertIn("Generate a daily plan only.", iter_generate.call_args.args[0])

    def test_mode_note_and_model_reach_ollama(self):
        payload = {"mode": "weekly", "note": "Gym daily at 2pm", "model": "qwen2.5:7b"}
        _, _, iter_generate = self._stream_plan(["ok"], payload=payload)
        prompt = iter_generate.call_args.args[0]
        self.assertIn("Generate a weekly overview only.", prompt)
        self.assertIn("Gym daily at 2pm", prompt)
        self.assertEqual(iter_generate.call_args.kwargs["model"], "qwen2.5:7b")

    def test_prompt_includes_suggested_work_sessions(self):
        self._set_google(tasks=[_task("Essay ~30m", 1, "t1")])
        _, _, iter_generate = self._stream_plan(["ok"])
        self.assertIn("SUGGESTED WORK SESSIONS", iter_generate.call_args.args[0])

    def test_plan_is_saved_to_history_and_shown_on_reload(self):
        _, lines, _ = self._stream_plan(["- 11:00 AM - 12:00 PM Study\n"])

        plans = self.client.get("/plans").get_json()["plans"]
        self.assertEqual([plan["id"] for plan in plans], [lines[-1]["id"]])
        detail = self.client.get(f"/plans/{plans[0]['id']}").get_json()
        self.assertIn("<li>11:00 AM - 12:00 PM Study</li>", detail["html"])

        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("<li>11:00 AM - 12:00 PM Study</li>", html)
        self.assertIn('"category": "plan"', html)

    def test_ollama_error_is_streamed_and_nothing_is_saved(self):
        _, lines, _ = self._stream_plan(error=RuntimeError("Ollama server is not running"))
        self.assertEqual(lines, [{"error": "Ollama server is not running"}])
        self.assertEqual(plan_history.list_plans(), [])

    def test_empty_plan_is_an_error(self):
        _, lines, _ = self._stream_plan(["  \n"])
        self.assertIn("error", lines[-1])
        self.assertEqual(plan_history.list_plans(), [])

    def test_unknown_plan_is_404(self):
        self.assertEqual(self.client.get("/plans/nope").status_code, 404)


class MoveEventTests(ServerTestCase):
    def setUp(self):
        super().setUp()
        self.today = date.today().isoformat()
        self.tomorrow = (date.today() + timedelta(days=1)).isoformat()
        (self.saved,) = saved_events.add_saved_events([{"date": self.today, "start": "09:00", "end": "10:00", "title": "Gym"}])

    def test_dragging_a_saved_event_updates_it(self):
        response = self.client.patch(
            f"/events/{self.saved['id']}", json={"date": self.tomorrow, "start": "17:00", "end": "18:30", "all_day": False}
        )

        self.assertEqual(response.status_code, 200)
        (event,) = saved_events.load_saved_events()
        self.assertEqual((event["date"], event["start"], event["end"], event["title"]), (self.tomorrow, "17:00", "18:30", "Gym"))

    def test_dragging_into_the_all_day_row(self):
        self.client.patch(f"/events/{self.saved['id']}", json={"date": self.today, "start": "", "end": "", "all_day": True})
        self.assertTrue(saved_events.load_saved_events()[0]["all_day"])

    def test_invalid_moves_are_rejected(self):
        self.assertEqual(self.client.patch(f"/events/{self.saved['id']}", json={"start": "10:00", "end": "09:00"}).status_code, 400)
        self.assertEqual(self.client.patch("/events/nope", json={"start": "10:00"}).status_code, 404)

    def test_saved_events_are_draggable_on_the_page(self):
        (entry,) = [event for event in self._api_events() if event.get("category") == "ask_ai"]
        self.assertTrue(entry["editable"])


class QuickAddEndpointTests(ServerTestCase):
    def test_parsed_text_is_saved_without_the_model(self):
        with mock.patch.object(server.requests, "post") as post:
            data = self.client.post("/quick-add", json={"text": "gym tomorrow 5pm"}).get_json()

        post.assert_not_called()
        self.assertTrue(data["parsed"])
        self.assertEqual([(e["title"], e["start"], e["end"]) for e in data["events"]], [("Gym", "17:00", "18:00")])

    def test_unrecognized_text_falls_back_to_the_model(self):
        body = json.dumps({"events": [{"date": date.today().isoformat(), "start": "07:00", "end": "07:30", "title": "Stretch"}]})
        with mock.patch.object(server.requests, "post", return_value=_ollama_response(body)) as post:
            data = self.client.post("/quick-add", json={"text": "stretch every morning"}).get_json()

        self.assertFalse(data["parsed"])
        self.assertEqual(data["events"][0]["title"], "Stretch")
        self.assertIn("stretch every morning", post.call_args.kwargs["json"]["prompt"])

    def test_bad_input_is_rejected(self):
        self.assertEqual(self.client.post("/quick-add", json={"text": "  "}).status_code, 400)
        response = self.client.post("/quick-add", json={"text": "movie 11pm for 3h"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("same day", response.get_json()["error"])


class DoneTaskEndpointTests(ServerTestCase):
    def _task_entries(self):
        return [event for event in self._api_events() if event.get("extendedProps", {}).get("key") == "t1"]

    def test_marking_a_task_done_hides_it_until_undone(self):
        self._set_google(tasks=[_task("Essay ~30m", 0, "t1")])
        self.assertEqual(len(self._task_entries()), 1)

        self.assertEqual(self.client.post("/tasks/done", json={"key": "t1", "title": "Essay ~30m"}).status_code, 200)

        data = self.client.get("/api/events").get_json()
        hidden = [e for e in data["events"] if e.get("extendedProps", {}).get("key") == "t1" or e.get("category") == "suggestion"]
        self.assertEqual(hidden, [])
        self.assertEqual(data["notices"], [])
        self.assertEqual([entry["key"] for entry in data["done"]], ["t1"])

        self.client.post("/tasks/undo", json={"key": "t1"})
        self.assertEqual(len(self._task_entries()), 1)

    def test_done_endpoints_validate_input(self):
        self.assertEqual(self.client.post("/tasks/done", json={}).status_code, 400)
        self.assertEqual(self.client.post("/tasks/undo", json={"key": "nope"}).status_code, 404)

    def test_marking_done_measures_the_time_and_clears_upcoming_sessions(self):
        self._set_google(tasks=[_task("Essay ~2h", 1, "t1")])
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        saved_events.add_saved_events([
            {"date": yesterday, "start": "10:00", "end": "11:30", "title": "Work on: Essay ~2h", "ref": "study:t1"},
            {"date": tomorrow, "start": "10:00", "end": "11:00", "title": "Work on: Essay ~2h", "ref": "study:t1"},
        ])

        data = self.client.post("/tasks/done", json={"key": "t1", "title": "Essay ~2h"}).get_json()

        self.assertEqual(data, {"done": "t1", "actual_minutes": 90, "estimate_minutes": 120, "removed_sessions": 1})
        self.assertEqual([event["date"] for event in saved_events.load_saved_events()], [yesterday])
        entry = done_tasks.load_done()[0]
        self.assertEqual(
            {name: entry.get(name) for name in ("list", "estimate", "from_task", "actual")},
            {"list": "School", "estimate": 120, "from_task": True, "actual": 90},
        )

    def test_reported_time_is_saved(self):
        self._set_google(tasks=[_task("Essay", 1, "t1")])
        self.client.post("/tasks/done", json={"key": "t1", "title": "Essay"})

        response = self.client.post("/tasks/time", json={"key": "t1", "minutes": 150})

        self.assertEqual(response.get_json(), {"key": "t1", "actual": 150})
        self.assertEqual(done_tasks.load_done()[0]["actual"], 150)
        for bad in ({"key": "t1", "minutes": 0}, {"key": "t1", "minutes": "90"}, {"key": "t1", "minutes": True}, {"minutes": 30}):
            with self.subTest(payload=bad):
                self.assertEqual(self.client.post("/tasks/time", json=bad).status_code, 400)
        self.assertEqual(self.client.post("/tasks/time", json={"key": "nope", "minutes": 30}).status_code, 404)


class FeedsTests(ServerTestCase):
    def test_feeds_dot_only_when_feeds_are_configured(self):
        self.assertNotIn("Feeds:", self.client.get("/").get_data(as_text=True))

        server._google_cache.clear()
        self._set_google(status={**self.status, "feeds_ok": True})
        self.assertIn('title="Feeds: connected"', self.client.get("/").get_data(as_text=True))

    def test_feeds_still_load_when_google_sign_in_fails(self):
        self.get_credentials.side_effect = FileNotFoundError("no credentials")
        with mock.patch.object(server, "fetch_feeds", return_value=([_event_today("Office hours", 15)], [], True)):
            titles = [event["title"] for event in self._api_events()]
        self.assertIn("Office hours", titles)


class ConfigProblemTests(ServerTestCase):
    """Uses the real _load_settings, pointed at a config.json in the temp directory."""

    patch_settings = False

    def _write_config(self, data):
        config = self.data_dir / "config.json"
        config.write_text(json.dumps(data), encoding="utf-8")
        self._patch(settings_module, "CONFIG_PATH", config)

    def test_bad_config_falls_back_to_defaults_and_says_why(self):
        self._write_config({"user_profile": {"workday_start": "8am"}})

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("workday_start must be an hour from 0 to 24", response.get_data(as_text=True))
        self.assertIn("workday_start", self.client.get("/api/events").get_json()["notices"][0])

    def test_fixing_the_config_clears_the_notice(self):
        self._write_config({"max_emails": "lots"})
        self.client.get("/")
        self._write_config({"max_emails": 5})
        self.assertEqual(self.client.get("/api/events").get_json()["notices"], [])


if __name__ == "__main__":
    unittest.main()
