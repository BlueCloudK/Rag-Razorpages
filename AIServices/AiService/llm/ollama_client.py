"""Small Ollama HTTP client."""

import requests


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def generate(self, model: str, prompt: str, options=None):
        response = requests.post(
            f"{self.base_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "options": options or {}},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json().get("response", "")
