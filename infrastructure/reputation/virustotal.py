from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SHA256 = re.compile(r"^[0-9a-f]{64}$")


class VirusTotalHashProvider:
    name = "virustotal"

    def __init__(self, api_key: str, timeout: float = 15.0):
        if not api_key: raise ValueError("VIRUSTOTAL_API_KEY no está configurada")
        self._api_key, self._timeout = api_key, timeout

    def lookup_hash(self, sha256: str):
        sha256 = sha256.casefold()
        if not SHA256.fullmatch(sha256): raise ValueError("SHA-256 inválido")
        request = Request(f"https://www.virustotal.com/api/v3/files/{sha256}",
                          headers={"x-apikey": self._api_key, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read(2_000_000))
        except HTTPError as exc:
            if exc.code == 404: return None
            raise RuntimeError(f"VirusTotal respondió HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"VirusTotal no disponible: {exc.reason}") from exc
        attributes = payload.get("data", {}).get("attributes", {})
        stats = attributes.get("last_analysis_stats", {})
        return {
            "stats": {key: int(stats.get(key, 0)) for key in ("malicious", "suspicious", "undetected", "harmless")},
            "reputation": int(attributes.get("reputation", 0)),
            "first_submission_date": attributes.get("first_submission_date"),
            "last_analysis_date": attributes.get("last_analysis_date"),
            "meaningful_name": attributes.get("meaningful_name"),
            "type_description": attributes.get("type_description"),
        }
