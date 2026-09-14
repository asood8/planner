import json
import os
from collections.abc import Iterator
from typing import Any

import requests


class OllamaClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    def _post(self, payload: dict, stream: bool) -> requests.Response:
        try:
            response = requests.post(f"{self.base_url}/api/generate", json=payload, stream=stream, timeout=300)
            response.raise_for_status()
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(
                "Ollama server is not running. Start it with: ollama serve"
            ) from exc
        except requests.exceptions.HTTPError as exc:
            error_text = exc.response.text if exc.response is not None else ""
            if "model not found" in error_text.lower() or "no such model" in error_text.lower():
                raise RuntimeError(
                    f"Model not found. Pull it first with: ollama pull {payload['model']}"
                ) from exc
            raise RuntimeError(f"Ollama request failed: {error_text or str(exc)}") from exc
        return response

    @staticmethod
    def _payload(prompt: str, model: str | None, stream: bool) -> dict:
        return {
            "model": model or os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
            "prompt": prompt,
            "stream": stream,
        }

    def iter_generate(self, prompt: str, model: str | None = None) -> Iterator[str]:
        """Yield response tokens as Ollama streams them. Raises RuntimeError on Ollama errors."""
        response = self._post(self._payload(prompt, model, stream=True), stream=True)
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            chunk = line[5:].strip() if line.startswith("data:") else line
            if not chunk:
                continue
            try:
                payload_chunk = json.loads(chunk)
            except ValueError:
                payload_chunk = {"response": chunk}
            if not isinstance(payload_chunk, dict):
                continue
            if payload_chunk.get("error"):
                raise RuntimeError(f"Ollama error: {payload_chunk['error']}")
            token = payload_chunk.get("response") or payload_chunk.get("result", "")
            if token:
                yield token

    def generate(self, prompt: str, model: str | None = None, stream: bool = True) -> str:
        if not stream:
            data = self._post(self._payload(prompt, model, stream=False), stream=False).json()
            return data.get("response") or data.get("result", "")

        full_text = []
        for token in self.iter_generate(prompt, model):
            print(token, end="", flush=True)
            full_text.append(token)

        print()
        return "".join(full_text)

    def generate_json(self, prompt: str, schema: dict, model: str | None = None) -> Any:
        """Structured output: `schema` goes in Ollama's `format`, temperature 0. Malformed output -> {}."""
        payload = {**self._payload(prompt, model, stream=False), "format": schema, "options": {"temperature": 0}}
        data = self._post(payload, stream=False).json()
        try:
            return json.loads(data.get("response") or "{}")
        except ValueError:
            return {}
