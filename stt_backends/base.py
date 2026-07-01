from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from transcription_cleaner import clean_transcription_text


class STTBackendError(RuntimeError):
    def __init__(self, message: str, *, code: str = "stt_error", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class STTBackend(ABC):
    id = ""
    name = ""
    supports_batch = False
    supports_realtime = False
    supports_diarization = False
    supports_word_timestamps = False
    supports_context_biasing = False

    def __init__(self):
        self.config: dict = {}

    def load(self, config: dict) -> None:
        self.config = dict(config or {})

    def unload(self) -> None:
        self.config = {}

    @abstractmethod
    def transcribe_file(self, audio_path: str | Path, options: dict) -> dict:
        raise NotImplementedError

    def transcribe_segments(self, audio_paths: list[str | Path], options: dict) -> dict:
        segments = []
        texts = []
        warnings = []
        errors = []
        started_offset = 0.0
        total_processing = 0.0

        for index, audio_path in enumerate(audio_paths, start=1):
            result = self.transcribe_file(audio_path, {**options, "mode": "segments", "segment_index": index})
            texts.append(str(result.get("text") or "").strip())
            warnings.extend(result.get("warnings") or [])
            errors.extend(result.get("errors") or [])
            total_processing += float(result.get("processing_seconds") or 0.0)
            for segment in result.get("segments") or []:
                copy = dict(segment)
                copy["start"] = float(copy.get("start") or 0.0) + started_offset
                copy["end"] = float(copy.get("end") or 0.0) + started_offset
                segments.append(copy)
            started_offset += float(result.get("duration_seconds") or 0.0)

        return normalize_stt_result(
            {
                "engine": self.id,
                "model": options.get("model"),
                "runtime": options.get("runtime") or "python",
                "device": options.get("device"),
                "mode": "segments",
                "language": options.get("language") or "fr",
                "text": " ".join(text for text in texts if text).strip(),
                "segments": segments,
                "duration_seconds": started_offset,
                "processing_seconds": total_processing,
                "warnings": warnings,
                "errors": errors,
            }
        )

    def health_check(self) -> dict:
        return {
            "engine": self.id,
            "name": self.name,
            "ok": True,
            "status": "available",
            "warnings": [],
            "errors": [],
        }


def normalize_stt_result(raw: dict | None) -> dict:
    raw = dict(raw or {})
    segments = normalize_segments(raw.get("segments") or [])
    text = clean_transcription_text(str(raw.get("text") or "").strip()) or " ".join(
        str(segment.get("text") or "").strip() for segment in segments if str(segment.get("text") or "").strip()
    ).strip()
    text = clean_transcription_text(text)

    return {
        "engine": str(raw.get("engine") or ""),
        "model": str(raw.get("model") or ""),
        "runtime": str(raw.get("runtime") or ""),
        "device": str(raw.get("device") or ""),
        "mode": str(raw.get("mode") or ""),
        "language": str(raw.get("language") or "fr"),
        "text": text,
        "segments": segments,
        "speakers": normalize_speakers(raw.get("speakers") or [], segments),
        "word_timestamps": list(raw.get("word_timestamps") or []),
        "duration_seconds": float(raw.get("duration_seconds") or 0.0),
        "processing_seconds": float(raw.get("processing_seconds") or 0.0),
        "warnings": normalize_messages(raw.get("warnings") or []),
        "errors": normalize_messages(raw.get("errors") or []),
        "raw": raw.get("raw") if raw.get("raw") is not None else {},
    }


def normalize_segments(raw_segments: list) -> list[dict]:
    segments = []
    for item in raw_segments or []:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            continue
        text = clean_transcription_text(str(item.get("text") or "").strip())
        if not text:
            continue
        segments.append(
            {
                "start": none_or_float(item.get("start")),
                "end": none_or_float(item.get("end")),
                "text": text,
                "speaker": item.get("speaker") if item.get("speaker") not in ("", None) else None,
                "confidence": none_or_float(item.get("confidence")),
            }
        )
    return segments


def normalize_speakers(raw_speakers: list, segments: list[dict]) -> list:
    speakers = [str(speaker) for speaker in raw_speakers if str(speaker or "").strip()]
    for segment in segments:
        speaker = segment.get("speaker")
        if speaker and speaker not in speakers:
            speakers.append(str(speaker))
    return speakers


def normalize_messages(values: list | str) -> list[str]:
    if isinstance(values, str):
        return [values] if values else []
    return [str(value) for value in values if str(value or "").strip()]


def none_or_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_cli_output(stdout: str, output_json_path: str | Path | None = None) -> dict:
    output_text = ""
    if output_json_path:
        path = Path(output_json_path)
        if path.exists():
            output_text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not output_text:
        output_text = str(stdout or "").strip()
    if not output_text:
        raise STTBackendError("réponse vide du moteur STT externe", code="empty_response")

    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError:
        return {"text": output_text, "raw": {"stdout": output_text}}

    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        return {"segments": parsed, "raw": parsed}
    return {"text": str(parsed), "raw": parsed}


def format_text_with_speaker_mapping(result: dict, speaker_map: dict[str, str] | None = None) -> str:
    speaker_map = speaker_map or {}
    lines = []
    for segment in result.get("segments") or []:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        speaker = segment.get("speaker")
        if speaker:
            label = speaker_map.get(str(speaker), str(speaker))
            lines.append(f"{label} : {text}")
        else:
            lines.append(text)
    return "\n".join(lines).strip() or str(result.get("text") or "").strip()
