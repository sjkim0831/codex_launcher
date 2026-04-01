from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path


def _default_preset_path() -> Path:
    return Path(__file__).resolve().parents[3] / "configs" / "ui_presets.json"


def _preset_path() -> Path:
    override = os.environ.get("FREE_AGENT_UI_PRESETS_PATH", "").strip()
    return Path(override) if override else _default_preset_path()


@lru_cache(maxsize=1)
def load_ui_preset_catalog() -> dict[str, dict[str, object]]:
    path = _preset_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def reset_ui_preset_catalog_cache() -> None:
    load_ui_preset_catalog.cache_clear()
