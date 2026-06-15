"""Small Ollama HTTP client and JSON helper utilities."""

import json
import re
import requests

from utils.text_normalization import clean_llm_output


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def prepare_prompt(self, prompt, model_name=None):
        prompt = str(prompt or "").strip()
        if str(model_name or "").lower().startswith("qwen3") and "/no_think" not in prompt[:80].lower():
            return "/no_think\n" + prompt
        return prompt

    def generate(
        self,
        model,
        prompt,
        num_ctx=None,
        num_predict=None,
        temperature=None,
        timeout=None,
        response_format=None,
    ):
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2 if temperature is None else temperature,
            },
        }
        if num_ctx is not None:
            payload["options"]["num_ctx"] = num_ctx
        if num_predict is not None:
            payload["options"]["num_predict"] = num_predict
        if response_format:
            payload["format"] = response_format
        if str(model or "").lower().startswith("qwen3"):
            payload["think"] = False
        response = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=self.timeout if timeout is None else timeout,
        )
        response.raise_for_status()
        return clean_llm_output(response.json().get("response", ""))


def parse_json_object(text):
    text = str(text or "").strip()
    text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()
    if not text or text == "{}":
        raise ValueError("small agent returned empty JSON")
    try:
        data = json.loads(text)
        if data == {}:
            raise ValueError("small agent returned empty JSON")
        return data
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
        if data == {}:
            raise ValueError("small agent returned empty JSON")
        return data
