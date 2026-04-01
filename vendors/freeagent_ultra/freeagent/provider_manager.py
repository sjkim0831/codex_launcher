from __future__ import annotations
import os
from freeagent.providers.mock_provider import MockProvider
from freeagent.providers.ollama_provider import OllamaProvider
from freeagent.providers.minimax_provider import MiniMaxProvider
from freeagent.providers.openai_compatible import OpenAICompatibleProvider

class ProviderManager:
    def __init__(self) -> None:
        preferred = os.getenv("FREEAGENT_PROVIDER", "mock")
        if preferred == "minimax2.7":
            preferred = "minimax"
        providers = {
            "mock": MockProvider(),
            "ollama": OllamaProvider(),
            "minimax": MiniMaxProvider(),
            "openai-compatible": OpenAICompatibleProvider(),
        }
        if preferred == "mock":
            ordered = ["mock"]
        else:
            ordered = [preferred] + [k for k in ("ollama", "minimax", "openai-compatible") if k != preferred]
        self.providers = [providers[k] for k in ordered]
        self.preferred = preferred

    def active_provider(self):
        for p in self.providers:
            if p.available():
                return p
        return MockProvider()

    def generate(self, prompt: str) -> tuple[str, str]:
        errors: list[str] = []
        for p in self.providers:
            is_available = False
            try:
                is_available = p.available()
            except Exception as e:
                errors.append(f"{p.name}: availability check failed: {e}")
            if not is_available and p.name != self.preferred:
                errors.append(f"{p.name}: unavailable")
                continue
            try:
                return p.generate(prompt), p.name
            except Exception as e:
                errors.append(f"{p.name}: {e}")

        if self.preferred == "mock":
            fallback = MockProvider()
            try:
                return fallback.generate(prompt), fallback.name
            except Exception as e:
                errors.append(f"{fallback.name}: {e}")

        if not errors:
            errors.append("no provider configured")
        return f"[provider_error] {' | '.join(errors)}", "none"
