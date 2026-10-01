from __future__ import annotations

from typing import Protocol


class SystemInfo(Protocol):
    def is_admin(self) -> bool: ...

