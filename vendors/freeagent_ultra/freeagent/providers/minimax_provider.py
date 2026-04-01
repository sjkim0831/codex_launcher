from __future__ import annotations

import os

from freeagent.providers.openai_compatible import OpenAICompatibleProvider


class MiniMaxProvider(OpenAICompatibleProvider):
    name = "minimax"

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None) -> None:
        resolved_base_url = (
            base_url
            or os.getenv("MINIMAX_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.minimaxi.chat/v1"
        )
        resolved_api_key = api_key or os.getenv("MINIMAX_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        resolved_model = model or os.getenv("FREEAGENT_MODEL", "minimax2.7")
        super().__init__(base_url=resolved_base_url, api_key=resolved_api_key, model=resolved_model)
