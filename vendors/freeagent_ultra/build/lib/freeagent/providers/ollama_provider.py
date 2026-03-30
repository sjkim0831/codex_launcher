from __future__ import annotations
import os, requests
from freeagent.providers.base import BaseProvider

class OllamaProvider(BaseProvider):
    name = "ollama"

    def __init__(self, host: str | None = None, model: str | None = None) -> None:
        self.host = host or os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        self.model = model or os.getenv("FREEAGENT_MODEL", "qwen2.5-coder:7b")
        self.timeout_sec = int(os.getenv("OLLAMA_TIMEOUT_SEC", "90"))

    def available(self) -> bool:
        try:
            r = requests.get(f"{self.host}/api/version", timeout=2)
            return r.ok
        except Exception:
            return False

    def generate(self, prompt: str, **kwargs) -> str:
        r = requests.post(
            f"{self.host}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=(3, self.timeout_sec),
        )
        r.raise_for_status()
        data = r.json()
        return data.get("response", "")
