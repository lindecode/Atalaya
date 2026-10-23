# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import json
from typing import Any
from urllib.request import ProxyHandler, Request, build_opener

from settings import Settings


# Fallback for Ollama servers too old to report capabilities in /api/show
EMBEDDING_HINTS = ("embed", "minilm", "bge-", "nomic-bert")
KNOWN_TOOL_HINTS = ("qwen", "llama", "granite", "mistral", "gemma", "command-r")

_CAPABILITIES_CACHE: dict[str, list[str]] = {}


def _raw_tags_query(host: str, timeout: float = 3.0) -> list[dict[str, Any]]:
    """Direct REST query to /api/tags as fallback or when SDK fails."""
    try:
        url = f"{host.rstrip('/')}/api/tags"
        opener = build_opener(ProxyHandler({}))
        req = Request(url, headers={"Accept": "application/json"})
        with opener.open(req, timeout=timeout) as response:
            if response.status == 200:
                payload = json.loads(response.read().decode("utf-8"))
                return payload.get("models") or []
    except Exception:
        pass
    return []


class OllamaModelCatalog:
    """Models installed in the local Ollama, with what each one can do."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def list_models(self) -> list[dict[str, Any]]:
        from ollama import Client

        host = self.settings.validated_ollama_host()
        client = Client(host=host, timeout=5)
        raw_items = []
        try:
            raw_items = list(client.list().models)
        except Exception:
            raw_items = _raw_tags_query(host)

        models = []
        for item in raw_items:
            name = (
                getattr(item, "model", None)
                or getattr(item, "name", None)
                or (item.get("model") if isinstance(item, dict) else None)
                or (item.get("name") if isinstance(item, dict) else None)
            )
            if not name:
                continue

            capabilities = _CAPABILITIES_CACHE.get(name)
            if capabilities is None:
                try:
                    capabilities = list(client.show(name).capabilities or [])
                except Exception:
                    capabilities = []
                if not capabilities:
                    if any(hint in name.casefold() for hint in EMBEDDING_HINTS):
                        capabilities = ["embedding"]
                    else:
                        capabilities = ["completion"]
                        if any(hint in name.casefold() for hint in KNOWN_TOOL_HINTS):
                            capabilities.append("tools")
                _CAPABILITIES_CACHE[name] = capabilities

            details = getattr(item, "details", None) if not isinstance(item, dict) else item.get("details")
            parameter_size = getattr(details, "parameter_size", None) if details and not isinstance(details, dict) else (details.get("parameter_size") if isinstance(details, dict) else None)
            quantization = getattr(details, "quantization_level", None) if details and not isinstance(details, dict) else (details.get("quantization_level") if isinstance(details, dict) else None)

            size_bytes = getattr(item, "size", None) if not isinstance(item, dict) else item.get("size")
            size_bytes = int(size_bytes or 0)
            if size_bytes > 0:
                raw_gb = size_bytes / 1e9
                size_gb = max(round(raw_gb, 1), 0.1)
            else:
                size_gb = 0.0

            models.append({
                "name": name,
                "size_bytes": size_bytes,
                "size_gb": size_gb,
                "parameters": parameter_size,
                "quantization": quantization,
                "capabilities": capabilities,
                "chat": "completion" in capabilities,
                "tools": "tools" in capabilities,
            })
        return sorted(models, key=lambda model: model["name"])
