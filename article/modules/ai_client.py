import json
import requests


class AIClient:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"

    def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 4096) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://patternslabco.com",
            "X-Title": "PatternsLab Article Generator",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = requests.post(self.base_url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def chat_json(self, messages: list[dict], temperature: float = 0.5, max_tokens: int = 4096) -> dict | list:
        """Call AI and parse JSON from the response (strips markdown code fences if present)."""
        raw = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        text = raw.strip()
        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(text)
