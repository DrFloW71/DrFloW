from __future__ import annotations

import json
import mimetypes
import socket
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from time import perf_counter
from urllib.parse import urlparse

from stt_audio_utils import analyze_wav

from .base import normalize_stt_result
from .base import STTBackendError
from .external_cli import ExternalCliSTTBackend


class VoxtralBackend(ExternalCliSTTBackend):
    id = "voxtral"
    name = "Voxtral"
    supports_batch = True
    supports_realtime = True
    supports_diarization = True
    supports_word_timestamps = True
    supports_context_biasing = True

    def load(self, config: dict) -> None:
        super().load(config)
        server_url = str(config.get("server_url") or "").strip()
        if server_url and not is_local_url(server_url):
            raise STTBackendError(
                "Voxtral est configuré avec une URL non locale. Refus par défaut pour préserver la confidentialité.",
                code="non_local_backend",
                details={"server_url": server_url},
            )

    def transcribe_file(self, audio_path, options: dict) -> dict:
        config = {**self.config, **(options or {})}
        runtime = str(config.get("runtime") or "auto")
        server_url = str(config.get("server_url") or "").strip()
        if runtime in {"auto", "vllm"} and server_url:
            return self.transcribe_file_with_local_server(audio_path, config)
        if runtime == "vllm" and not str(config.get("external_cli_command") or "").strip():
            raise STTBackendError(
                "Runtime Voxtral vLLM non connecté directement dans cette version. "
                "Configure une commande external_cli locale qui appelle ton serveur vLLM.",
                code="vllm_adapter_missing",
            )
        return super().transcribe_file(audio_path, options)

    def transcribe_file_with_local_server(self, audio_path, config: dict) -> dict:
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise STTBackendError("fichier audio introuvable", code="invalid_audio_file", details={"audio_path": str(audio_path)})

        server_url = str(config.get("server_url") or "").strip()
        if not is_local_url(server_url):
            raise STTBackendError(
                "Voxtral est configuré avec une URL non locale. Refus par défaut pour préserver la confidentialité.",
                code="non_local_backend",
                details={"server_url": server_url},
            )

        endpoint = build_openai_audio_transcription_url(server_url)
        timeout = int(float(config.get("timeout_seconds") or 300))
        audio_stats = analyze_wav(audio_path)
        fields = {
            "model": str(config.get("model") or "Voxtral-Mini-3B"),
            "language": str(config.get("language") or "fr"),
            "response_format": "verbose_json",
        }
        if bool(config.get("enable_word_timestamps", False)):
            fields["timestamp_granularities[]"] = "word"

        body, content_type = encode_multipart_form(fields, "file", audio_path)
        request = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": content_type,
            },
        )

        started = perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw_text = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise STTBackendError(
                f"Voxtral serveur local HTTP {exc.code}: {details[:600]}",
                code="server_http_error",
                details={"endpoint": endpoint, "status": exc.code, "body": details[:1200]},
            ) from exc
        except urllib.error.URLError as exc:
            raise STTBackendError(
                f"Serveur Voxtral local injoignable : {exc.reason}",
                code="server_unreachable",
                details={"endpoint": endpoint},
            ) from exc

        parsed = parse_server_response(raw_text)
        result = normalize_stt_result(
            {
                **parsed,
                "engine": self.id,
                "model": config.get("model") or parsed.get("model") or "",
                "runtime": "vllm",
                "device": config.get("device") or parsed.get("device") or "",
                "mode": config.get("mode") or parsed.get("mode") or "batch",
                "language": config.get("language") or parsed.get("language") or "fr",
                "duration_seconds": parsed.get("duration_seconds") or audio_stats.get("duration_seconds") or 0.0,
                "processing_seconds": perf_counter() - started,
                "raw": {
                    "audio_path": str(audio_path),
                    "audio_stats": audio_stats,
                    "endpoint": endpoint,
                    "backend_raw": parsed.get("raw") if isinstance(parsed, dict) else parsed,
                },
            }
        )
        if not result["text"]:
            raise STTBackendError("réponse Voxtral vide après normalisation", code="empty_response")
        return result

    def health_check(self) -> dict:
        result = super().health_check()
        server_url = str(self.config.get("server_url") or "").strip()
        runtime = str(self.config.get("runtime") or "auto")
        if server_url and not is_local_url(server_url):
            result["ok"] = False
            result["errors"].append("URL serveur non locale refusée")
        elif server_url and runtime in {"auto", "vllm"}:
            result["status"] = f"runtime={runtime}, serveur local={build_openai_audio_transcription_url(server_url)}"
            result["errors"] = [
                error for error in result["errors"]
                if "commande externe non configurée" not in str(error).lower()
                and "runtime vllm non disponible" not in str(error).lower()
            ]
            if local_server_is_reachable(server_url):
                result["ok"] = True
                result["warnings"].append(
                    "Serveur local Voxtral détecté. La transcription utilisera /v1/audio/transcriptions."
                )
            else:
                result["ok"] = False
                result["errors"].append("serveur local Voxtral injoignable")
        if str(self.config.get("device") or "").lower() == "cuda":
            result["warnings"].append(
                "Attention : Voxtral peut consommer de la VRAM et perturber Gemma 31B si LM Studio utilise déjà fortement la RTX 5090."
            )
        return result


def is_local_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def build_openai_audio_transcription_url(server_url: str) -> str:
    base = str(server_url or "").strip().rstrip("/")
    if not base:
        return ""
    lower = base.lower()
    if lower.endswith("/v1/audio/transcriptions"):
        return base
    if lower.endswith("/v1"):
        return base + "/audio/transcriptions"
    return base + "/v1/audio/transcriptions"


def local_server_is_reachable(server_url: str, timeout_seconds: float = 1.5) -> bool:
    try:
        parsed = urlparse(server_url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not host or not is_local_url(server_url):
            return False
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def encode_multipart_form(fields: dict[str, str], file_field_name: str, file_path: Path) -> tuple[bytes, str]:
    boundary = "----DrFloWSTT" + uuid.uuid4().hex
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )

    mime_type = mimetypes.guess_type(str(file_path))[0] or "audio/wav"
    parts.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            (
                f'Content-Disposition: form-data; name="{file_field_name}"; '
                f'filename="{file_path.name}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {mime_type}\r\n\r\n".encode("ascii"),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def parse_server_response(raw_text: str) -> dict:
    text = str(raw_text or "").strip()
    if not text:
        raise STTBackendError("réponse vide du serveur Voxtral", code="empty_response")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"text": text, "raw": {"response_text": text}}
    if not isinstance(parsed, dict):
        return {"text": str(parsed), "raw": parsed}

    segments = []
    for item in parsed.get("segments") or parsed.get("chunks") or []:
        if not isinstance(item, dict):
            continue
        start = item.get("start")
        end = item.get("end")
        timestamp = item.get("timestamp")
        if isinstance(timestamp, (list, tuple)) and len(timestamp) >= 2:
            start = timestamp[0] if start is None else start
            end = timestamp[1] if end is None else end
        segments.append(
            {
                "start": start,
                "end": end,
                "text": item.get("text") or item.get("transcript") or "",
                "speaker": item.get("speaker") or item.get("speaker_id"),
                "confidence": item.get("confidence") or item.get("avg_logprob"),
            }
        )

    return {
        "text": parsed.get("text") or parsed.get("transcription") or "",
        "segments": segments,
        "word_timestamps": parsed.get("words") or parsed.get("word_timestamps") or [],
        "duration_seconds": parsed.get("duration") or parsed.get("duration_seconds") or 0.0,
        "language": parsed.get("language") or "",
        "model": parsed.get("model") or "",
        "raw": parsed,
    }
