from __future__ import annotations
from freeagent.providers.base import BaseProvider

class MockProvider(BaseProvider):
    name = "mock"

    def available(self) -> bool:
        return True

    def generate(self, prompt: str, **kwargs) -> str:
        pl = prompt.lower()
        if "401" in pl and "500" in pl:
            return "ACTION: backend_status_fix\nPATCH_HINT: unauthorized->401\nTEST_HINT: pytest -q"
        if "button" in pl and ("toast" in pl or "fetch" in pl):
            return "ACTION: react_button_fetch_toast\nPATCH_HINT: add button, loading state, fetch, toast\nTEST_HINT: npm test"
        if "explain" in pl:
            return "SUMMARY: This file appears to be a component or service related to the requested symbol."
        return "ACTION: generic_minimal_safe_change\nPATCH_HINT: minimal patch\nTEST_HINT: pytest -q"
