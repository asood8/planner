import unittest
from unittest import mock

import requests

from ai import ollama_client
from ai.ollama_client import OllamaClient


def _stream_response(lines):
    response = mock.Mock()
    response.iter_lines.return_value = iter(lines)
    return response


def _json_response(body):
    response = mock.Mock()
    response.json.return_value = {"response": body}
    return response


class IterGenerateTests(unittest.TestCase):
    def test_yields_tokens_from_ndjson_stream(self):
        lines = ['{"response": "Hel"}', "", '{"response": "lo", "done": false}', '{"done": true}']
        with mock.patch.object(ollama_client.requests, "post", return_value=_stream_response(lines)) as post:
            tokens = list(OllamaClient("http://ollama").iter_generate("prompt", model="m"))

        self.assertEqual(tokens, ["Hel", "lo"])
        self.assertTrue(post.call_args.kwargs["json"]["stream"])

    def test_error_chunk_raises(self):
        lines = ['{"response": "partial"}', '{"error": "model crashed"}']
        with mock.patch.object(ollama_client.requests, "post", return_value=_stream_response(lines)):
            with self.assertRaisesRegex(RuntimeError, "model crashed"):
                list(OllamaClient("http://ollama").iter_generate("prompt", model="m"))

    def test_connection_error_explains_how_to_start_ollama(self):
        with mock.patch.object(ollama_client.requests, "post", side_effect=requests.exceptions.ConnectionError()):
            with self.assertRaisesRegex(RuntimeError, "ollama serve"):
                list(OllamaClient("http://ollama").iter_generate("prompt", model="m"))


class GenerateJsonTests(unittest.TestCase):
    def test_sends_schema_and_parses_response(self):
        schema = {"type": "object"}
        with mock.patch.object(ollama_client.requests, "post", return_value=_json_response('{"items": []}')) as post:
            result = OllamaClient("http://ollama").generate_json("prompt", schema, model="m")

        self.assertEqual(result, {"items": []})
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["format"], schema)
        self.assertFalse(sent["stream"])
        self.assertEqual(sent["options"], {"temperature": 0})

    def test_malformed_output_is_empty(self):
        with mock.patch.object(ollama_client.requests, "post", return_value=_json_response("oops")):
            self.assertEqual(OllamaClient("http://ollama").generate_json("prompt", {}, model="m"), {})


if __name__ == "__main__":
    unittest.main()
