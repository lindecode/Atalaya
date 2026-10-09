from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


CATALOG_VERSION = 1


@dataclass(frozen=True, slots=True)
class ModelSpec:
    name: str
    label: str
    size_gb: float
    min_ram_gb: float
    roles: tuple[str, ...]
    tools: bool = False
    min_ollama: str | None = None


# Reviewed, versioned allow-list. Updating recommendations requires an Atalaya release.
OLLAMA_CATALOG = (
    ModelSpec("qwen3.5:0.8b", "Qwen 3.5 0.8B", 1.3, 4, ("chat", "analysis", "summary"), True),
    ModelSpec("qwen3.5:2b", "Qwen 3.5 2B", 3.1, 8, ("chat", "analysis", "summary"), True),
    ModelSpec("qwen3.5:4b", "Qwen 3.5 4B", 4.0, 10, ("chat", "analysis", "summary"), True),
    ModelSpec("qwen3.5:9b", "Qwen 3.5 9B", 7.6, 16, ("chat", "analysis", "summary"), True),
    ModelSpec("embeddinggemma:latest", "EmbeddingGemma 300M", 0.7, 4, ("embedding",), False, "0.11.10"),
)


def detect_hardware(run=subprocess.run) -> dict:
    import psutil
    ram_gb = psutil.virtual_memory().total / 1024 ** 3
    disk_root = Path(os.environ.get("OLLAMA_MODELS", Path.home() / ".ollama" / "models"))
    probe = disk_root
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    disk_free_gb = shutil.disk_usage(probe).free / 1024 ** 3
    vram_gb = None
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            result = run([nvidia_smi, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, timeout=5, check=False,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            values = [float(line.strip()) / 1024 for line in result.stdout.splitlines() if line.strip()]
            if values: vram_gb = max(values)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return {"ram_gb": round(ram_gb, 1), "vram_gb": round(vram_gb, 1) if vram_gb else None,
            "disk_free_gb": round(disk_free_gb, 1), "cpu_threads": os.cpu_count() or 1}


def recommendation(hardware: dict) -> dict:
    ram = float(hardware["ram_gb"])
    vram = float(hardware.get("vram_gb") or 0)
    threads = int(hardware.get("cpu_threads") or 1)
    main = ("qwen3.5:9b" if (ram >= 20 and threads >= 8) or (ram >= 16 and vram >= 8) else
            "qwen3.5:4b" if ram >= 12 or (ram >= 10 and vram >= 4) else
            "qwen3.5:2b" if ram >= 8 else "qwen3.5:0.8b")
    if threads <= 4 and main in {"qwen3.5:9b", "qwen3.5:4b"}:
        main = "qwen3.5:2b"
    summary = "qwen3.5:2b" if ram >= 20 else "qwen3.5:0.8b"
    models = tuple(dict.fromkeys((main, summary, "embeddinggemma:latest")))
    required = sum(next(spec.size_gb for spec in OLLAMA_CATALOG if spec.name == name) for name in models) * 1.20
    fits_disk = float(hardware["disk_free_gb"]) >= required
    return {"analysis": main, "chat": main, "summary": summary, "embedding": "embeddinggemma:latest",
            "models": models, "required_disk_gb": round(required, 1), "fits_disk": fits_disk,
            "reason": f"Perfil para {ram:.0f} GB de RAM, {threads} hilos"
                      + (f" y {vram:.0f} GB de VRAM NVIDIA" if vram else " sin VRAM NVIDIA detectada")
                      + "; reserva memoria para Windows y Atalaya."}


def model_spec(name: str) -> ModelSpec:
    try:
        return next(spec for spec in OLLAMA_CATALOG if spec.name == name)
    except StopIteration as exc:
        raise ValueError("Modelo fuera del catálogo revisado de Atalaya") from exc


def enough_disk(name: str, hardware: dict) -> tuple[bool, float]:
    required = round(model_spec(name).size_gb * 1.20, 1)
    return float(hardware["disk_free_gb"]) >= required, required


def functional_test(settings, name: str, client=None) -> dict:
    """Short, explicit post-download test; never called during discovery or recommendation."""
    spec = model_spec(name)
    if client is None:
        from ollama import Client
        client = Client(host=settings.validated_ollama_host(), timeout=settings.llm_timeout_seconds)
    shown = client.show(name)
    capabilities = list(getattr(shown, "capabilities", None) or [])
    if "embedding" in spec.roles:
        response = client.embed(model=name, input=["Atalaya prueba local"])
        vectors = getattr(response, "embeddings", None) or []
        if len(vectors) != 1 or not vectors[0]:
            raise RuntimeError("El modelo no devolvió un embedding")
        return {"ok": True, "test": "embedding", "dimensions": len(vectors[0]), "capabilities": capabilities}
    if spec.tools and "tools" not in capabilities:
        raise RuntimeError("Ollama no informa capacidad de herramientas para este modelo")
    if spec.tools:
        tool = {"type": "function", "function": {"name": "atalaya_ping", "description": "Prueba local",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}}
        tool_response = client.chat(model=name, messages=[{"role": "user", "content": "Llama atalaya_ping ahora."}],
                                    tools=[tool], options={"temperature": 0}, think=False)
        if not (getattr(tool_response.message, "tool_calls", None) or []):
            raise RuntimeError("El modelo no realizó la llamada de herramienta de prueba")
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
              "additionalProperties": False}
    response = client.chat(model=name, messages=[{"role": "user", "content": "Responde {\"ok\":true}."}],
                           format=schema, options={"temperature": 0}, think=False)
    payload = json.loads(response.message.content)
    if payload.get("ok") is not True:
        raise RuntimeError("El modelo no respetó la salida JSON estructurada")
    return {"ok": True, "test": "chat+json+tools-capability", "capabilities": capabilities}
