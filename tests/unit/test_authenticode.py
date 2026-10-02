from pathlib import Path
from unittest.mock import patch

from infrastructure.windows.authenticode import PowerShellAuthenticodeAnalyzer


def test_path_is_passed_by_environment_not_interpolated():
    completed = type("Completed", (), {"returncode": 0, "stdout": '{"Status":"Valid","Subject":"Publisher"}', "stderr": ""})()
    path = Path(r"C:\unsafe'; Write-Output injected; '.exe")
    with patch("infrastructure.windows.authenticode.os.name", "nt"), \
         patch("infrastructure.windows.authenticode.subprocess.run", return_value=completed) as run:
        result = PowerShellAuthenticodeAnalyzer().inspect(path)
    command = run.call_args.args[0]
    environment = run.call_args.kwargs["env"]
    assert str(path) not in command
    assert environment["NETWORK_LLM_SIGNATURE_TARGET"] == str(path)
    assert result["valid"] is True
