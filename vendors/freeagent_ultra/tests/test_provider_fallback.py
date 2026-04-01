import os
from freeagent.provider_manager import ProviderManager

def test_provider_does_not_silently_fallback_to_mock(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("FREEAGENT_PROVIDER", "openai-compatible")
    pm = ProviderManager()
    text, name = pm.generate("explain something")
    assert name == "none"
    assert "[provider_error]" in text


def test_provider_uses_mock_only_when_explicitly_requested(monkeypatch):
    monkeypatch.setenv("FREEAGENT_PROVIDER", "mock")
    pm = ProviderManager()
    text, name = pm.generate("explain something")
    assert name == "mock"
    assert text


def test_minimax_provider_selected_when_configured(monkeypatch):
    monkeypatch.setenv("FREEAGENT_PROVIDER", "minimax")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)
    pm = ProviderManager()
    assert pm.active_provider().name == "minimax"


def test_minimax_alias_minimax27_maps_to_provider(monkeypatch):
    monkeypatch.setenv("FREEAGENT_PROVIDER", "minimax2.7")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    pm = ProviderManager()
    assert pm.preferred == "minimax"
