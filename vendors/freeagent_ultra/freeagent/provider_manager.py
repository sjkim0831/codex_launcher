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
            # If this is the preferred provider, try it even if .available() was False
            if p.name == self.preferred:
                try:
                    return p.generate(prompt), p.name
                except Exception as e:
                    errors.append(f"{p.name}: {e}")
                    # If preferred fails, we do NOT fallback to others unless preferred was 'mock'
                    if self.preferred != "mock":
                        break
                    continue
            
            # For non-preferred providers, only use if available
            if p.available():
                try:
                    return p.generate(prompt), p.name
                except Exception as e:
                    errors.append(f"{p.name}: {e}")
            else:
                errors.append(f"{p.name}: unavailable")

        return f"[provider_error] {' | '.join(errors)}", "none"
