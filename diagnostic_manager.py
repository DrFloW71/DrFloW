from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


@dataclass(frozen=True)
class DiagnosticResult:
    status: str
    name: str
    detail: str


def run_drflow_diagnostics(
    *,
    base_dir: str | Path,
    data_dir: str | Path,
    config: dict,
    microphone_count: int,
    server_running: bool,
    fly_hotkey_ready: bool,
    stt_label: str,
    patient_context_state: str,
    lmstudio_probe: Callable[[], str],
) -> list[DiagnosticResult]:
    base = Path(base_dir)
    data = Path(data_dir)
    results: list[DiagnosticResult] = []

    python_ok = sys.version_info >= (3, 10)
    results.append(
        DiagnosticResult(
            "ok" if python_ok else "error",
            "Python",
            f"{platform.python_version()} • {platform.system()} {platform.release()}",
        )
    )

    config_path = base / "config.json"
    try:
        json.loads(config_path.read_text(encoding="utf-8"))
        results.append(DiagnosticResult("ok", "Configuration", "config.json valide"))
    except Exception as exc:
        results.append(DiagnosticResult("error", "Configuration", f"JSON invalide : {type(exc).__name__}"))

    writable_target = data if data.exists() else data.parent
    results.append(
        DiagnosticResult(
            "ok" if os.access(writable_target, os.W_OK) else "error",
            "Données locales",
            "Dossier local accessible en écriture" if os.access(writable_target, os.W_OK) else "Dossier non accessible",
        )
    )
    results.append(
        DiagnosticResult(
            "ok" if microphone_count > 0 else "error",
            "Microphone",
            f"{microphone_count} périphérique(s) détecté(s)" if microphone_count > 0 else "Aucun périphérique détecté",
        )
    )
    results.append(DiagnosticResult("ok" if server_running else "error", "Serveur local", "Actif" if server_running else "Arrêté"))
    results.append(
        DiagnosticResult(
            "ok" if fly_hotkey_ready else "warning",
            "Dictée à la volée",
            "Raccourci global actif" if fly_hotkey_ready else "Raccourci global inactif ou désactivé",
        )
    )
    results.append(DiagnosticResult("ok" if stt_label else "warning", "Moteur STT", stt_label or "Non chargé"))

    patient_status = "ok" if patient_context_state == "ok" else "warning"
    results.append(DiagnosticResult(patient_status, "Verrou patient", patient_context_state or "inconnu"))

    lm_url = str(config.get("lmstudio", {}).get("url") or "")
    host = (urlparse(lm_url).hostname or "").lower()
    local_host = host in {"localhost", "127.0.0.1", "::1"}
    results.append(
        DiagnosticResult(
            "ok" if local_host else "warning",
            "Confidentialité LM Studio",
            "Adresse locale" if local_host else "Adresse non locale configurée",
        )
    )
    try:
        results.append(DiagnosticResult("ok", "LM Studio", lmstudio_probe()))
    except Exception as exc:
        results.append(DiagnosticResult("error", "LM Studio", f"Injoignable : {type(exc).__name__}"))

    bridge = base / "tampermonkey" / "weda_bridge.user.js"
    if bridge.exists():
        text = bridge.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"@version\s+([^\s]+)", text)
        version = match.group(1) if match else "inconnue"
        results.append(DiagnosticResult("ok", "Pont WEDA", f"Présent • version {version}"))
    else:
        results.append(DiagnosticResult("error", "Pont WEDA", "Userscript absent"))

    hook_status = _git_hook_status(base)
    results.append(hook_status)
    privacy_script = base / "tools" / "check_private_data.py"
    results.append(
        DiagnosticResult(
            "ok" if privacy_script.exists() else "error",
            "Contrôle confidentialité Git",
            "Script présent" if privacy_script.exists() else "Script absent",
        )
    )
    return results


def sanitized_diagnostic_report(results: list[DiagnosticResult]) -> str:
    lines = ["Diagnostic DrFloW (aucune donnée patient)"]
    for item in results:
        lines.append(f"[{item.status.upper()}] {item.name}: {item.detail}")
    return "\n".join(lines)


def diagnostic_results_as_dicts(results: list[DiagnosticResult]) -> list[dict]:
    return [asdict(item) for item in results]


def _git_hook_status(base_dir: Path) -> DiagnosticResult:
    try:
        completed = subprocess.run(
            ["git", "-C", str(base_dir), "config", "--get", "core.hooksPath"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        value = completed.stdout.strip().replace("\\", "/")
    except Exception:
        value = ""
    hook_exists = (base_dir / ".githooks" / "pre-commit").exists()
    if value == ".githooks" and hook_exists:
        return DiagnosticResult("ok", "Hook Git privé", ".githooks/pre-commit actif")
    if hook_exists:
        return DiagnosticResult("warning", "Hook Git privé", "Hook présent mais chemin Git non configuré")
    return DiagnosticResult("error", "Hook Git privé", "Hook pre-commit absent")
