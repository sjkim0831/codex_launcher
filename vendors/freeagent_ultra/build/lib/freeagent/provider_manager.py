from __future__ import annotations
import os
from freeagent.providers.mock_provider import MockProvider
from freeagent.providers.ollama_provider import OllamaProvider
from freeagent.providers.openai_compatible import OpenAICompatibleProvider

class ProviderManager:
    def __init__(self) -> None:
        preferred = os.getenv("FREEAGENT_PROVIDER", "mock")
        providers = {
            "mock": MockProvider(),
            "ollama": OllamaProvider(),
            "openai-compatible": OpenAICompatibleProvider(),
        }
        ordered = [preferred] + [k for k in providers if k != preferred]
        self.providers = [providers[k] for k in ordered]

    def active_provider(self):
        for p in self.providers:
            if p.available():
                return p
        return MockProvider()

    def generate(self, prompt: str) -> tuple[str, str]:
        errors: list[str] = []
        for p in self.providers:
            if not p.available():
                continue
            try:
                return p.generate(prompt), p.name
            except Exception as e:
                errors.append(f"{p.name}: {e}")

        fallback = MockProvider()
        try:
            return fallback.generate(prompt), fallback.name
        except Exception as e:
            errors.append(f"{fallback.name}: {e}")
            return f"[provider_error] {' | '.join(errors)}", "none"
