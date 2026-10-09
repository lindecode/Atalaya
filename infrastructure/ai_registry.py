from __future__ import annotations

import hashlib
import json
import os
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

from settings import data_home


ROLES = ("chat", "analysis", "summary", "embedding")


@dataclass(frozen=True, slots=True)
class RegisteredModel:
    id: str
    name: str
    path: str
    sha256: str
    size_bytes: int
    gguf_version: int
    roles: tuple[str, ...]


def registry_path() -> Path:
    return data_home() / "models" / "registry.json"


def inspect_gguf(path: Path) -> dict:
    """Validate and hash a GGUF without loading or executing it."""
    resolved = path.expanduser().resolve()
    if resolved.suffix.casefold() != ".gguf" or not resolved.is_file():
        raise ValueError("Seleccione un archivo .gguf existente")
    size = resolved.stat().st_size
    if size < 24:
        raise ValueError("El archivo es demasiado pequeño para ser un GGUF")
    with resolved.open("rb") as stream:
        header = stream.read(24)
        if header[:4] != b"GGUF":
            raise ValueError("El archivo no tiene la firma GGUF")
        version = struct.unpack("<I", header[4:8])[0]
        if version not in {2, 3}:
            raise ValueError(f"Versión GGUF no compatible: {version}")
        digest = hashlib.sha256(header)
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(resolved), "name": resolved.stem, "sha256": digest.hexdigest(),
            "size_bytes": size, "gguf_version": version}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ModelRegistry:
    """User-authorized catalog; it never scans disk or executes a candidate."""

    def __init__(self, path: Path | None = None):
        self.path = path or registry_path()

    def _read(self) -> dict:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {"schema": 1, "models": [], "assignments": {}}
        return payload if isinstance(payload, dict) else {"schema": 1, "models": [], "assignments": {}}

    def _write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def models(self) -> list[RegisteredModel]:
        result = []
        for item in self._read().get("models", []):
            try:
                result.append(RegisteredModel(**{**item, "roles": tuple(item.get("roles", ())) }))
            except (TypeError, ValueError):
                continue
        return result

    def register(self, path: Path, roles: tuple[str, ...]) -> RegisteredModel:
        selected = tuple(dict.fromkeys(roles))
        if not selected or any(role not in ROLES for role in selected):
            raise ValueError("Seleccione al menos una función válida")
        info = inspect_gguf(path)
        model = RegisteredModel(id=info["sha256"][:16], roles=selected, **info)
        payload = self._read()
        payload["models"] = [item for item in payload.get("models", []) if item.get("id") != model.id]
        payload["models"].append(asdict(model))
        self._write(payload)
        return model

    def assign(self, role: str, model_id: str) -> None:
        if role not in ROLES:
            raise ValueError("Función de modelo inválida")
        model = next((item for item in self.models() if item.id == model_id), None)
        if model is None or role not in model.roles:
            raise ValueError("El modelo no está autorizado para esa función")
        payload = self._read()
        payload.setdefault("assignments", {})[role] = model_id
        self._write(payload)

    def set_provider(self, provider: str) -> None:
        if provider not in {"auto", "ollama", "llama_cpp", "none"}:
            raise ValueError("Proveedor inválido")
        payload = self._read()
        payload["provider"] = provider
        self._write(payload)

    def provider(self) -> str:
        value = self._read().get("provider", "auto")
        return value if value in {"auto", "ollama", "llama_cpp", "none"} else "auto"

    def register_runtime(self, path: Path) -> dict:
        resolved = path.expanduser().resolve()
        if not resolved.is_file() or resolved.name.casefold() != "llama-server.exe":
            raise ValueError("Seleccione llama-server.exe")
        with resolved.open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise ValueError("El archivo no tiene una cabecera ejecutable PE")
            stream.seek(0)
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        runtime = {"path": str(resolved), "sha256": digest.hexdigest(), "size_bytes": resolved.stat().st_size}
        payload = self._read()
        payload["runtime"] = runtime
        self._write(payload)
        return runtime

    def runtime(self) -> dict | None:
        value = self._read().get("runtime")
        return value if isinstance(value, dict) and Path(str(value.get("path", ""))).is_file() else None

    def verify_execution(self, role: str) -> None:
        """Fail closed if an explicitly registered executable or model changed after authorization."""
        runtime = self.runtime()
        model = self.assigned(role) or (self.assigned("chat") if role == "analysis" else None)
        for label, path, expected in (
            ("llama-server.exe", Path(runtime["path"]), runtime["sha256"]) if runtime else (None, None, None),
            (f"modelo {role}", Path(model.path), model.sha256) if model else (None, None, None),
        ):
            if path is not None and _sha256(path) != expected:
                raise RuntimeError(f"{label} cambió después de ser autorizado; vuelva a registrarlo")

    def assigned(self, role: str) -> RegisteredModel | None:
        model_id = self._read().get("assignments", {}).get(role)
        return next((item for item in self.models() if item.id == model_id and Path(item.path).is_file()), None)


def hardware_recommendations(models: list[RegisteredModel], ram_bytes: int) -> dict[str, str | None]:
    usable = [model for model in models if model.size_bytes <= max(int(ram_bytes * 0.70), 1)]
    largest = lambda role: max((m for m in usable if role in m.roles), key=lambda m: m.size_bytes, default=None)
    smallest = lambda role: min((m for m in usable if role in m.roles), key=lambda m: m.size_bytes, default=None)
    return {"analysis": getattr(largest("analysis"), "id", None),
            "chat": getattr(largest("chat"), "id", None),
            "summary": getattr(smallest("summary"), "id", None),
            "embedding": getattr(largest("embedding"), "id", None)}
