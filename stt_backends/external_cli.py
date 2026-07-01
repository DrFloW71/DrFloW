from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from time import perf_counter

from stt_audio_utils import analyze_wav

from .base import STTBackend, STTBackendError, normalize_stt_result, parse_cli_output


class ExternalCliSTTBackend(STTBackend):
    default_runtime = "external_cli"

    def transcribe_file(self, audio_path: str | Path, options: dict) -> dict:
        config = {**self.config, **(options or {})}
        runtime = str(config.get("runtime") or self.default_runtime)
        if runtime == "disabled":
            raise STTBackendError(f"{self.name} est désactivé.", code="runtime_disabled")
        if runtime not in {"auto", "external_cli"}:
            raise STTBackendError(
                f"Runtime {runtime} non disponible pour {self.name} dans cette version. "
                "Configure un runtime external_cli local pour tester ce moteur.",
                code="runtime_unavailable",
            )

        command_template = str(config.get("external_cli_command") or "").strip()
        if not command_template:
            raise STTBackendError(
                f"{self.name} n'a pas de commande externe configurée.",
                code="external_cli_missing",
                details={"runtime": runtime},
            )

        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise STTBackendError("fichier audio introuvable", code="invalid_audio_file", details={"audio_path": str(audio_path)})

        timeout = int(float(config.get("timeout_seconds") or 300))
        audio_stats = analyze_wav(audio_path)
        started = perf_counter()
        with tempfile.TemporaryDirectory(prefix="stt_cli_") as tmp_dir:
            output_json = Path(tmp_dir) / "stt_output.json"
            command = command_template.format(
                audio_path=str(audio_path),
                output_json=str(output_json),
                model=str(config.get("model") or ""),
                language=str(config.get("language") or "fr"),
                device=str(config.get("device") or ""),
                runtime=runtime,
            )
            try:
                completed = subprocess.run(
                    command,
                    shell=True,
                    cwd=str(audio_path.parent),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise STTBackendError(
                    f"timeout {self.name} après {timeout}s",
                    code="timeout",
                    details={"command": command},
                ) from exc

            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            if completed.returncode != 0:
                raise STTBackendError(
                    f"{self.name} a échoué (code {completed.returncode}) : {(stderr or stdout).strip()[:600]}",
                    code="external_cli_failed",
                    details={"returncode": completed.returncode, "stderr": stderr[:1200], "stdout": stdout[:1200]},
                )

            parsed = parse_cli_output(stdout, output_json)

        result = normalize_stt_result(
            {
                **parsed,
                "engine": self.id,
                "model": config.get("model") or parsed.get("model") or "",
                "runtime": "external_cli",
                "device": config.get("device") or parsed.get("device") or "",
                "mode": config.get("mode") or parsed.get("mode") or "batch",
                "language": config.get("language") or parsed.get("language") or "fr",
                "duration_seconds": parsed.get("duration_seconds") or audio_stats.get("duration_seconds") or 0.0,
                "processing_seconds": perf_counter() - started,
                "raw": {
                    "audio_path": str(audio_path),
                    "audio_stats": audio_stats,
                    "backend_raw": parsed.get("raw") if isinstance(parsed, dict) else parsed,
                },
            }
        )
        if not result["text"]:
            raise STTBackendError("réponse STT vide après normalisation", code="empty_response")
        return result

    def health_check(self) -> dict:
        runtime = str(self.config.get("runtime") or self.default_runtime)
        command = str(self.config.get("external_cli_command") or "").strip()
        warnings = []
        errors = []
        ok = True
        status = f"runtime={runtime}"
        if runtime == "disabled":
            ok = False
            errors.append("runtime désactivé")
        elif runtime in {"auto", "external_cli"} and not command:
            ok = False
            errors.append("commande externe non configurée")
        elif runtime not in {"auto", "external_cli"}:
            ok = False
            errors.append(f"runtime {runtime} non disponible dans cette version")
        return {
            "engine": self.id,
            "name": self.name,
            "ok": ok,
            "status": status,
            "warnings": warnings,
            "errors": errors,
            "help": (
                "Renseigne le champ 'Commande externe' avec une commande locale qui transcrit le fichier WAV. "
                "Variables disponibles : {audio_path}, {output_json}, {model}, {language}, {device}, {runtime}. "
                "La commande doit écrire un JSON contenant au minimum {'text': '...'} dans {output_json}, "
                "ou imprimer ce JSON sur stdout."
            ) if "commande externe non configurée" in errors else "",
        }
