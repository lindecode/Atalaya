from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path


class PowerShellAuthenticodeAnalyzer:
    _SCRIPT = """[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$s = Get-AuthenticodeSignature -LiteralPath $env:NETWORK_LLM_SIGNATURE_TARGET
[pscustomobject]@{
 Status = [string]$s.Status
 StatusMessage = [string]$s.StatusMessage
 Subject = if ($s.SignerCertificate) { $s.SignerCertificate.Subject } else { $null }
 Issuer = if ($s.SignerCertificate) { $s.SignerCertificate.Issuer } else { $null }
 Thumbprint = if ($s.SignerCertificate) { $s.SignerCertificate.Thumbprint } else { $null }
 NotBefore = if ($s.SignerCertificate) { $s.SignerCertificate.NotBefore.ToUniversalTime().ToString('o') } else { $null }
 NotAfter = if ($s.SignerCertificate) { $s.SignerCertificate.NotAfter.ToUniversalTime().ToString('o') } else { $null }
} | ConvertTo-Json -Compress
"""

    def inspect(self, path: Path) -> dict[str, object]:
        if os.name != "nt":
            return {"status": "UnsupportedPlatform", "valid": False}
        encoded = base64.b64encode(self._SCRIPT.encode("utf-16-le")).decode("ascii")
        environment = os.environ.copy()
        environment["NETWORK_LLM_SIGNATURE_TARGET"] = str(path)
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], env=environment,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            return {"status": "Error", "valid": False, "error": completed.stderr.strip()[:500]}
        raw = json.loads(completed.stdout)
        return {
            "status": raw.get("Status"), "valid": raw.get("Status") == "Valid",
            "status_message": raw.get("StatusMessage"), "subject": raw.get("Subject"),
            "issuer": raw.get("Issuer"), "thumbprint": raw.get("Thumbprint"),
            "not_before": raw.get("NotBefore"), "not_after": raw.get("NotAfter"),
        }
