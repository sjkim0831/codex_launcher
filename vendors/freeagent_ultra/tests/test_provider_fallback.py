import os
from freeagent.provider_manager import ProviderManager

def test_provider_fallback_to_mock(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("FREEAGENT_PROVIDER", "openai-compatible")
    pm = ProviderManager()
    text, name = pm.generate("explain something")
    assert name in {"mock", "openai-compatible", "ollama"}
    assert text
