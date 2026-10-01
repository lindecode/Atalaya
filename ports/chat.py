from __future__ import annotations

from typing import Any, Protocol


class ToolExecutor(Protocol):
    def call(self, name: str, args: dict[str, Any]) -> list[dict[str, Any]]: ...

