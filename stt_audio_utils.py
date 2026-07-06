from __future__ import annotations

import math
import os
import wave
from pathlib import Path


DEFAULT_AUDIO_FILTER_CONFIG = {
    "enabled": True,
    "min_rms_for_transcription": 0.0015,
    "min_peak_for_transcription": 0.02,
    "min_duration_seconds": 0.8,
    "skip_silent_segments": True,
    "log_skipped_segments": True,
}


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
        raise RuntimeError("numpy n'est pas installé. Lance `pip install -r requirements.txt`.") from exc

    data = np.asarray(audio, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    elif int(channels or 1) > 1 and data.size and data.size % int(channels) == 0:
        data = data.reshape(-1, int(channels)).mean(axis=1)
    return np.ascontiguousarray(data.reshape(-1), dtype="float32")


def audio_has_probable_signal(audio_stats: dict, config: dict | None = None) -> bool:
    filter_config = normalize_audio_filter_config(config)
    rms = float(audio_stats.get("rms") or 0.0)
    peak = float(audio_stats.get("peak") or 0.0)
    non_silent_ratio = float(audio_stats.get("non_silent_ratio_0_005") or 0.0)
    return (
        rms >= float(filter_config["min_rms_for_transcription"])
        or peak >= float(filter_config["min_peak_for_transcription"])
        or non_silent_ratio >= 0.01
    )


def normalize_audio_filter_config(config: dict | None = None) -> dict:
    source = config if isinstance(config, dict) else {}
    if isinstance(source.get("audio_filter"), dict):
        source = source.get("audio_filter") or {}
    merged = {**DEFAULT_AUDIO_FILTER_CONFIG, **source}
    return {
        "enabled": bool(merged.get("enabled", True)),
        "min_rms_for_transcription": float(merged.get("min_rms_for_transcription") or 0.0015),
        "min_peak_for_transcription": float(merged.get("min_peak_for_transcription") or 0.02),
        "min_duration_seconds": float(merged.get("min_duration_seconds") or 0.8),
        "skip_silent_segments": bool(merged.get("skip_silent_segments", True)),
        "log_skipped_segments": bool(merged.get("log_skipped_segments", True)),
    }


def should_skip_audio_for_transcription(audio_stats: dict, config: dict | None = None) -> tuple[bool, str, dict]:
    filter_config = normalize_audio_filter_config(config)
    if not filter_config["enabled"]:
        return False, "", filter_config

    duration = float(audio_stats.get("duration_seconds") or 0.0)
    rms = float(audio_stats.get("rms") or 0.0)
    peak = float(audio_stats.get("peak") or 0.0)
    non_silent_ratio = float(audio_stats.get("non_silent_ratio_0_005") or 0.0)

    if duration > 0 and duration < filter_config["min_duration_seconds"]:
        return True, "audio_too_short", filter_config

    if (
        filter_config["skip_silent_segments"]
        and rms < filter_config["min_rms_for_transcription"]
        and peak < filter_config["min_peak_for_transcription"]
        and non_silent_ratio < 0.01
    ):
        return True, "audio_silent_or_wrong_input_device", filter_config

    return False, "", filter_config


def format_skipped_audio_log(segment_index: int | str, audio_stats: dict, reason: str) -> str:
    reason_label = "durée trop courte" if reason == "audio_too_short" else "silence probable"
    duration = float(audio_stats.get("duration_seconds") or 0.0)
    rms = float(audio_stats.get("rms") or 0.0)
    peak = float(audio_stats.get("peak") or 0.0)
    return (
        f"[STT] Segment {segment_index or '?'} ignoré : {reason_label} ; "
        f"durée={duration:.1f}s ; RMS={rms:.6f} ; peak={peak:.6f}"
    )


def build_empty_reason(audio_stats: dict, segments_count: int, retry_without_vad: bool, config: dict | None = None) -> str:
    if int(audio_stats.get("frames") or 0) <= 0:
        return "audio_empty"
    if not audio_has_probable_signal(audio_stats, config):
        return "audio_silent_or_wrong_input_device"
    if retry_without_vad:
        return "no_text_after_retry_without_vad"
    if segments_count <= 0:
        return "no_speech_segment_detected"
    return "speech_segment_without_text"
