from pathlib import Path
from types import SimpleNamespace

import application.ollama_install as install


def test_install_uses_fixed_winget_command_without_shell(monkeypatch):
    monkeypatch.setattr(install, "winget_path", lambda: r"C:\Windows\winget.exe")
    captured = {}

    def popen(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return SimpleNamespace(pid=42)

    child = install.start_install(popen)

    assert child.pid == 42
    assert captured["command"] == [r"C:\Windows\winget.exe", "install", "--id", "Ollama.Ollama", "-e",
                                   "--accept-package-agreements", "--accept-source-agreements"]
    assert captured["kwargs"]["shell"] is False


def test_verification_reports_signature_version_and_api(monkeypatch, tmp_path):
    executable = tmp_path / "ollama.exe"; executable.write_bytes(b"MZ")
    monkeypatch.setattr(install, "find_ollama", lambda: str(executable))

    class Signer:
        def inspect(self, _path): return {"valid": True, "status": "Valid", "subject": "Ollama Publisher"}

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, _limit): return b'{"version":"1.2.3"}'

    class Opener:
        def open(self, *_args, **_kwargs): return Response()

    result = install.verify_installation(
        run=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="ollama version 1.2.3", stderr=""),
        signer=Signer(), opener=Opener())

    assert result["installed"] and result["signature_valid"] and result["api"]
    assert result["api_version"] == "1.2.3" and result["path"] == str(executable.resolve())
