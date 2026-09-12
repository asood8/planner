import unittest
from datetime import date, datetime, time, timedelta
from unittest import mock

import requests

import server


def _ollama_response(body):
    response = mock.Mock()
    response.json.return_value = {"response": body}
    return response


class GenerateEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()

    def test_ask_ai_system_prompt_is_loaded_and_sent(self):
        self.assertIn("calendar events", server.SYSTEM_PROMPT)
        body = '{"events": [{"date": "2026-09-14", "start": "14:00", "end": "15:00", "title": "Gym"}]}'

        with mock.patch.object(server.requests, "post", return_value=_ollama_response(body)) as post:
            result = self.client.post("/generate", json={"prompt": "Permanent note:\nI go to the gym daily at 2 PM"})

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.get_json()["events"][0]["title"], "Gym")
        sent = post.call_args.kwargs["json"]
        self.assertTrue(sent["prompt"].startswith(server.SYSTEM_PROMPT))
        self.assertEqual(sent["model"], server._configured_model())

    def test_missing_prompt_is_rejected(self):
        self.assertEqual(self.client.post("/generate", json={}).status_code, 400)

    def test_unreachable_ollama_returns_502(self):
        with mock.patch.object(server.requests, "post", side_effect=requests.exceptions.ConnectionError()):
            result = self.client.post("/generate", json={"prompt": "gym at 2pm"})
        self.assertEqual(result.status_code, 502)

    def test_malformed_model_output_yields_no_events(self):
        with mock.patch.object(server.requests, "post", return_value=_ollama_response("not json")):
            result = self.client.post("/generate", json={"prompt": "gym at 2pm"})
        self.assertEqual(result.get_json(), {"events": []})


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()

    def test_renders_fetched_google_data(self):
        start = datetime.combine(date.today(), time(10)).astimezone()
        events = [{"title": "CS Lecture", "start": start, "end": start + timedelta(hours=1), "all_day": False}]
        status = {"calendar_ok": True, "tasks_ok": True, "gmail_ok": None}

        with mock.patch.object(server, "get_credentials", return_value=object()), \
                mock.patch.object(server, "fetch_sources", return_value=(events, [], [], status)), \
                mock.patch.object(server, "_configured_model", return_value="test-model:1b"):
            html = self.client.get("/").get_data(as_text=True)

        self.assertIn("CS Lecture", html)
        self.assertIn(f'"{date.today().isoformat()}T10:00:00"', html)
        self.assertIn('"test-model:1b"', html)
        self.assertIn('title="Calendar: connected"', html)
        self.assertIn('title="Gmail: not loaded"', html)

    def test_sign_in_failure_still_renders_page(self):
        with mock.patch.object(server, "get_credentials", side_effect=FileNotFoundError("credentials.json <missing>")), \
                mock.patch.object(server, "fetch_sources") as fetch:
            response = self.client.get("/")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        fetch.assert_not_called()
        self.assertIn('title="Calendar: fetch failed"', html)
        self.assertIn("credentials.json &lt;missing&gt;", html)

    def test_python_sources_in_output_are_not_served(self):
        self.assertEqual(self.client.get("/calendar_formatter.py").status_code, 404)
        self.assertEqual(self.client.get("/static/calendar_formatter.py").status_code, 404)


if __name__ == "__main__":
    unittest.main()
