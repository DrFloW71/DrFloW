from __future__ import annotations

import math
import os
import wave
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Callable

from stt_engine_manager import STTEngineManager, format_stt_text
from transcription_cleaner import WHISPER_MEDICAL_INITIAL_PROMPT, clean_transcription_text
from whisper_model_manager import WhisperModelManager, WhisperSettings


FORCED_FRENCH_INITIAL_PROMPT = WHISPER_MEDICAL_INITIAL_PROMPT


@dataclass
class TranscriptionResult:
    segment_index: int
    text: str
    elapsed_seconds: float
    model_label: str
    audio_path: str
    audio_stats: dict
    segments_count: int
    retry_without_vad: bool
    empty_reason: str
    stt_result: dict | None = None
    stt_engine: str = "faster-whisper"
    stt_model: str = ""
    stt_runtime: str = "python"
    stt_device: str = ""
    stt_mode: str = "segments"
    stt_warnings: list | None = None
    stt_errors: list | None = None


class Transcriber:
    def __init__(
        self,
        model_manager: WhisperModelManager,
        settings_provider: Callable[[], dict],
        *,
        stt_manager: STTEngineManager | None = None,
    ):
        self.model_manager = model_manager
        self.settings_provider = settings_provider
        self.stt_manager = stt_manager or STTEngineManager(model_manager)

    def transcribe_file(
        self,
        audio_path: str | Path,
        *,
        segment_index: int = 0,
        settings_override: dict | None = None,
    ) -> TranscriptionResult:
        settings_map = self.settings_provider()
        if settings_override:
            settings_map.update(settings_override)
        result = self.stt_manager.transcribe_file(audio_path, settings_map)
        return self._to_transcription_result(result, segment_index=segment_index, audio_path=str(audio_path))

    def transcribe_audio_array(
        self,
        audio,
        *,
        sample_rate: int,
        channels: int = 1,
        segment_index: int = 0,
        settings_override: dict | None = None,
    ) -> TranscriptionResult:
        settings_map = self.settings_provider()
        if settings_override:
            settings_map.update(settings_override)
        result = self.stt_manager.transcribe_audio_array(
            audio,
            sample_rate=sample_rate,
            channels=channels,
            config=settings_map,
        )
        return self._to_transcription_result(result, segment_index=segment_index, audio_path="<memory>")

    def _to_transcription_result(self, stt_result: dict, *, segment_index: int, audio_path: str) -> TranscriptionResult:
        raw = stt_result.get("raw") or {}
        audio_stats = raw.get("audio_stats") or (
            analyze_audio_array([], sample_rate=0) if audio_path == "<memory>" else analyze_wav(audio_path)
        )
        retry_without_vad = bool(raw.get("retry_without_vad", False))
        segments_count = int(raw.get("segments_count") or len(stt_result.get("segments") or []))
        text = clean_transcription_text(format_stt_text(stt_result).strip())
        empty_reason = str(raw.get("empty_reason") or "")
        if not text and not empty_reason:
            empty_reason = build_empty_reason(audio_stats, segments_count, retry_without_vad)
        model_label = str(raw.get("model_label") or "").strip()
        if not model_label:
            model_label = " / ".join(
                part for part in (
                    stt_result.get("engine"),
                    stt_result.get("model"),
                    stt_result.get("device"),
                    stt_result.get("runtime"),
                ) if part
            )

        return TranscriptionResult(
            segment_index=segment_index,
            text=text,
            elapsed_seconds=float(stt_result.get("processing_seconds") or 0.0),
            model_label=model_label or "moteur STT inconnu",
            audio_path=audio_path,
            audio_stats=audio_stats,
            segments_count=segments_count,
            retry_without_vad=retry_without_vad,
            empty_reason=empty_reason,
            stt_result=stt_result,
            stt_engine=str(stt_result.get("engine") or ""),
            stt_model=str(stt_result.get("model") or ""),
            stt_runtime=str(stt_result.get("runtime") or ""),
            stt_device=str(stt_result.get("device") or ""),
            stt_mode=str(stt_result.get("mode") or ""),
            stt_warnings=list(stt_result.get("warnings") or []),
            stt_errors=list(stt_result.get("errors") or []),
        )

    def _run_transcribe(self, model, audio_source, settings_map: dict, *, vad_filter: bool) -> tuple[str, int]:
        condition_on_previous_text = False
        transcribe_kwargs = {
            "language": "fr",
            "task": "transcribe",
            "beam_size": int(settings_map.get("beam_size") or 5),
            "vad_filter": vad_filter,
            "condition_on_previous_text": condition_on_previous_text,
            "initial_prompt": str(settings_map.get("initial_prompt") or FORCED_FRENCH_INITIAL_PROMPT),
        }
        if settings_map.get("temperature") is not None:
            transcribe_kwargs["temperature"] = float(settings_map.get("temperature") or 0.0)
        if settings_map.get("best_of") is not None:
            transcribe_kwargs["best_of"] = int(settings_map.get("best_of") or 1)
        if vad_filter:
            transcribe_kwargs["vad_parameters"] = {
                "min_silence_duration_ms": int(settings_map.get("min_silence_duration_ms") or 500)
            }

        source = str(audio_source) if isinstance(audio_source, (str, Path)) else audio_source
        segments, _info = model.transcribe(
            source,
            **transcribe_kwargs,
        )
        segment_list = list(segments)
        text = " ".join(segment.text.strip() for segment in segment_list if getattr(segment, "text", "").strip())
        return text.strip(), len(segment_list)


def analyze_wav(audio_path: str | Path) -> dict:
    path = Path(audio_path)
    stats = {
        "path": str(path),
        "file_bytes": 0,
        "duration_seconds": 0.0,
        "frames": 0,
        "sample_rate": 0,
        "channels": 0,
        "sample_width": 0,
        "rms": 0.0,
        "peak": 0.0,
        "mean_abs": 0.0,
        "dbfs": None,
        "non_silent_ratio_0_005": 0.0,
    }

    try:
        stats["file_bytes"] = os.path.getsize(path)
    except OSError:
        pass

    try:
        import numpy as np
    except ImportError:
        stats["analysis_error"] = "numpy_missing"
        return stats

    try:
        with wave.open(str(path), "rb") as wav:
            frames = wav.getnframes()
            sample_rate = wav.getframerate()
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            raw = wav.readframes(frames)

        stats.update(
            {
                "duration_seconds": round(frames / sample_rate, 3) if sample_rate else 0.0,
                "frames": frames,
                "sample_rate": sample_rate,
                "channels": channels,
                "sample_width": sample_width,
            }
        )

        if not raw or sample_width != 2:
            return stats

        data = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
        if channels > 1 and len(data) >= channels:
            data = data.reshape(-1, channels).mean(axis=1)

        if data.size == 0:
            return stats

        abs_data = np.abs(data)
        rms = float(np.sqrt(np.mean(np.square(data))))
        peak = float(np.max(abs_data))
        mean_abs = float(np.mean(abs_data))
        stats.update(
            {
                "rms": round(rms, 6),
                "peak": round(peak, 6),
                "mean_abs": round(mean_abs, 6),
                "dbfs": round(20 * math.log10(max(rms, 1e-12)), 1),
                "non_silent_ratio_0_005": round(float(np.mean(abs_data > 0.005)), 6),
            }
        )
    except Exception as exc:
        stats["analysis_error"] = str(exc)

    return stats


def analyze_audio_array(audio, *, sample_rate: int, channels: int = 1) -> dict:
    stats = {
        "path": "<memory>",
        "file_bytes": 0,
        "duration_seconds": 0.0,
        "frames": 0,
        "sample_rate": int(sample_rate or 0),
        "channels": int(channels or 1),
        "sample_width": 4,
        "rms": 0.0,
        "peak": 0.0,
        "mean_abs": 0.0,
        "dbfs": None,
        "non_silent_ratio_0_005": 0.0,
    }

    try:
        import numpy as np
    except ImportError:
        stats["analysis_error"] = "numpy_missing"
        return stats

    try:
        data = np.asarray(audio, dtype="float32")
        stats["file_bytes"] = int(data.nbytes)
        if data.size == 0:
            return stats

        frames = int(data.shape[0]) if data.ndim > 0 else int(data.size)
        sample_rate_value = int(sample_rate or 0)
        stats.update(
            {
                "duration_seconds": round(frames / sample_rate_value, 3) if sample_rate_value else 0.0,
                "frames": frames,
            }
        )

        if data.ndim > 1:
            mono = data.mean(axis=1)
            stats["channels"] = int(data.shape[1])
        else:
            mono = data.reshape(-1)

        if mono.size == 0:
            return stats

        abs_data = np.abs(mono)
        rms = float(np.sqrt(np.mean(np.square(mono))))
        peak = float(np.max(abs_data))
        mean_abs = float(np.mean(abs_data))
        stats.update(
            {
                "rms": round(rms, 6),
                "peak": round(peak, 6),
                "mean_abs": round(mean_abs, 6),
                "dbfs": round(20 * math.log10(max(rms, 1e-12)), 1),
                "non_silent_ratio_0_005": round(float(np.mean(abs_data > 0.005)), 6),
            }
        )
    except Exception as exc:
        stats["analysis_error"] = str(exc)

    return stats


def prepare_audio_array_for_whisper(audio, *, channels: int = 1):
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy n’est pas installé. Lance `pip install -r requirements.txt`.") from exc

    data = np.asarray(audio, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    elif int(channels or 1) > 1 and data.size and data.size % int(channels) == 0:
        data = data.reshape(-1, int(channels)).mean(axis=1)
    return np.ascontiguousarray(data.reshape(-1), dtype="float32")


def audio_has_probable_signal(audio_stats: dict) -> bool:
    rms = float(audio_stats.get("rms") or 0.0)
    peak = float(audio_stats.get("peak") or 0.0)
    non_silent_ratio = float(audio_stats.get("non_silent_ratio_0_005") or 0.0)
    return rms >= 0.0015 or peak >= 0.02 or non_silent_ratio >= 0.01


def build_empty_reason(audio_stats: dict, segments_count: int, retry_without_vad: bool) -> str:
    if int(audio_stats.get("frames") or 0) <= 0:
        return "audio_empty"
    if not audio_has_probable_signal(audio_stats):
        return "audio_silent_or_wrong_input_device"
    if retry_without_vad:
        return "no_text_after_retry_without_vad"
    if segments_count <= 0:
        return "no_speech_segment_detected"
    return "speech_segment_without_text"
