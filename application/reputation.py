from __future__ import annotations

import hashlib
import re
from pathlib import Path

from domain.reputation import ReputationResult


ALLOWED_EXTENSIONS = {".exe", ".dll", ".sys", ".msi", ".scr", ".ocx", ".cpl"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class FileReputationService:
    def __init__(self, store, clock, settings, signature_analyzer, provider=None):
        self.store, self.clock, self.settings = store, clock, settings
        self.signature_analyzer, self.provider = signature_analyzer, provider

    def inspect(self, raw_path: Path, online=False):
        path = raw_path.resolve(strict=True)
        if raw_path.is_symlink() or not path.is_file(): raise ValueError("Debe indicar un archivo regular, no un enlace")
        if path.suffix.casefold() not in ALLOWED_EXTENSIONS: raise ValueError("Tipo de ejecutable no admitido")
        if path.stat().st_size > self.settings.reputation_max_bytes: raise ValueError("Archivo mayor que el límite de reputación")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""): digest.update(block)
        local = {"size": path.stat().st_size, "extension": path.suffix.casefold(),
                 "signature": self.signature_analyzer.inspect(path)}
        return self._evaluate(digest.hexdigest(), str(path), local, online)

    def lookup(self, sha256: str):
        sha256 = sha256.casefold()
        if not SHA256.fullmatch(sha256): raise ValueError("SHA-256 inválido")
        return self._evaluate(sha256, None, {}, True)

    def _evaluate(self, sha256, path, local, online):
        if online and not self.provider: raise ValueError("Configure VIRUSTOTAL_API_KEY para consultar reputación")
        external = self.provider.lookup_hash(sha256) if online else None
        malicious = int((external or {}).get("stats", {}).get("malicious", 0))
        suspicious = int((external or {}).get("stats", {}).get("suspicious", 0))
        valid = bool(local.get("signature", {}).get("valid"))
        if malicious >= 5:
            verdict, confidence, reasons = "malicious", min(0.99, 0.75 + malicious / 100), [f"{malicious} motores lo clasifican como malicioso"]
        elif malicious or suspicious:
            verdict, confidence, reasons = "suspicious", 0.70, [f"Detecciones: {malicious} maliciosas y {suspicious} sospechosas"]
        elif external and valid:
            verdict, confidence, reasons = "likely_safe", 0.85, ["Firma Authenticode válida", "Sin detecciones conocidas en la consulta"]
        elif external:
            verdict, confidence, reasons = "unknown", 0.55, ["Sin detecciones conocidas, pero sin firma válida comprobada"]
        elif valid:
            verdict, confidence, reasons = "unknown", 0.45, ["Firma Authenticode válida; reputación externa no consultada o desconocida"]
        else:
            verdict, confidence, reasons = "unknown", 0.25, ["No hay evidencia suficiente para determinar confianza"]
        result = ReputationResult(sha256, path, self.clock.now_iso(), local,
                                  self.provider.name if online and self.provider else "local", external,
                                  verdict, confidence, tuple(reasons))
        self.store.initialize(); self.store.save(result)
        return result

    def latest(self, limit=100):
        self.store.initialize(); return self.store.latest(limit)
