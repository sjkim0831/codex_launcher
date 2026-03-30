from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any

class BaseProvider(ABC):
    name = "base"

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def generate(self, prompt: str, **kwargs: Any) -> str: ...
