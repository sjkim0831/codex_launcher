from __future__ import annotations
import os, requests
from freeagent.providers.base import BaseProvider

class OpenAICompatibleProvider(BaseProvider):
    name = "openai-compatible"

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model or os.getenv("FREEAGENT_MODEL", "gpt-4.1-mini")

    def available(self) -> bool:
        return bool(self.base_url and self.api_key)

    def generate(self, prompt: str, **kwargs) -> str:
        r = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
