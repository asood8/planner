import json
import os
from typing import Any

import requests


class OllamaClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    def generate(self, prompt: str, model: str | None = None, stream: bool = True) -> str:
        payload = {
            "model": model or os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
            "prompt": prompt,
            "stream": stream,
        }

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

        if not stream:
            data = response.json()
            return data.get("response") or data.get("result", "")

        full_text = []
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                chunk = line
                if chunk.startswith("data:"):
                    chunk = chunk[5:].strip()
                if not chunk:
                    continue
                payload_chunk = None
                try:
                    payload_chunk = json.loads(chunk)
                except ValueError:
                    payload_chunk = {"response": chunk}
                token = payload_chunk.get("response") or payload_chunk.get("result", "")
                if token:
                    print(token, end="", flush=True)
                    full_text.append(token)
            except Exception:
                continue

        print()
        return "".join(full_text)
