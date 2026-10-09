from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from application.doctor import find_ollama
from infrastructure.windows.authenticode import PowerShellAuthenticodeAnalyzer


WINGET_PACKAGE = "Ollama.Ollama"


def winget_path() -> str | None:
    return shutil.which("winget")


def install_command(executable: str) -> list[str]:
    return [executable, "install", "--id", WINGET_PACKAGE, "-e",
            "--accept-package-agreements", "--accept-source-agreements"]


def start_install(popen=subprocess.Popen):
    executable = winget_path()
    if not executable:
        raise RuntimeError("winget no está disponible en este equipo")
    # Fixed arguments, no shell, visible console: the person can see agreements, progress and errors.
    return popen(install_command(executable), shell=False,
                 creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))


def verify_installation(run=subprocess.run, signer=None, opener=None) -> dict:
    executable = find_ollama()
    if not executable:
        return {"installed": False, "signature_valid": False, "version": None, "api": False,
                "error": "No se encontró ollama.exe"}
    path = Path(executable).resolve()
    signature = (signer or PowerShellAuthenticodeAnalyzer()).inspect(path)
    completed = run([str(path), "--version"], capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=20, check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    version = (completed.stdout or completed.stderr).strip()[:200] if completed.returncode == 0 else None
    api = False
    api_version = None
    try:
        client = opener or build_opener(ProxyHandler({}))
        with client.open(Request("http://127.0.0.1:11434/api/version", headers={"Accept": "application/json"}),
                         timeout=2) as response:
            payload = json.loads(response.read(4096).decode("utf-8"))
            api_version = payload.get("version")
            api = response.status == 200 and isinstance(api_version, str)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return {"installed": True, "path": str(path), "signature_valid": bool(signature.get("valid")),
            "signature_status": signature.get("status"), "publisher": signature.get("subject"),
            "version": version, "api": api, "api_version": api_version}
