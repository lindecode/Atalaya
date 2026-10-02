from __future__ import annotations

from typing import Any


def chat(client, **kwargs: Any):
    """client.chat with think=False, retried without it for models that have no thinking mode (e.g. granite)."""
    try:
        return client.chat(**kwargs)
    except Exception as exc:
        if "think" in kwargs and "thinking" in str(exc).casefold():
            kwargs.pop("think")
            return client.chat(**kwargs)
        raise
