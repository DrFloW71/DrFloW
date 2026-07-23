from __future__ import annotations

from pathlib import Path
from typing import Iterable

from stt_backends import FasterWhisperBackend, Qwen3ASRBackend, VoxtralBackend
from stt_backends.base import STTBackendError, format_text_with_speaker_mapping, normalize_stt_result
from transcription_cleaner import DEFAULT_BLOCKED_LINE_PATTERNS
from whisper_model_manager import WhisperModelManager, canonical_french_whisper_model_name
from medical_transcription import (
    DEFAULT_MEDICAL_WHISPER_PROMPT,
    DEFAULT_WHISPER_BEAM_SIZE,
    DEFAULT_WHISPER_COMPUTE_TYPE,
    DEFAULT_WHISPER_DEVICE,
    DEFAULT_WHISPER_MODEL,
    DEFAULT_WHISPER_TEMPERATURE,
    TRANSCRIPTION_OVERLAP_SECONDS,
    TRANSCRIPTION_WINDOW_SECONDS,
)


FASTER_WHISPER_ENGINE_ID = "faster-whisper"
QWEN3_ASR_ENGINE_ID = "qwen3_asr"
VOXTRAL_ENGINE_ID = "voxtral"

STT_ENGINE_LABELS = {
    FASTER_WHISPER_ENGINE_ID: "faster-whisper",
    QWEN3_ASR_ENGINE_ID: "Qwen3-ASR",
    VOXTRAL_ENGINE_ID: "Voxtral",
}
STT_ENGINE_IDS_BY_LABEL = {label: engine_id for engine_id, label in STT_ENGINE_LABELS.items()}
STT_ENGINE_MODEL_CHOICES = {
    FASTER_WHISPER_ENGINE_ID: ("small", "medium", "large-v3", "large-v3-turbo", "turbo"),
    QWEN3_ASR_ENGINE_ID: ("Qwen3-ASR-0.6B", "Qwen3-ASR-1.7B"),
    VOXTRAL_ENGINE_ID: ("Voxtral-Mini-3B", "Voxtral-Realtime expérimental"),
}
STT_ENGINE_RUNTIME_CHOICES = {
    FASTER_WHISPER_ENGINE_ID: ("python",),
    QWEN3_ASR_ENGINE_ID: ("auto", "transformers", "external_cli", "disabled"),
    VOXTRAL_ENGINE_ID: ("auto", "vllm", "transformers", "external_cli", "disabled"),
}
STT_ENGINE_DEVICE_CHOICES = {
    FASTER_WHISPER_ENGINE_ID: ("cpu", "cuda"),
    QWEN3_ASR_ENGINE_ID: ("cuda", "cpu"),
    VOXTRAL_ENGINE_ID: ("cuda", "cpu"),
}


DEFAULT_STT_CONFIG = {
    "stt": {
        "default_engine": FASTER_WHISPER_ENGINE_ID,
        "allow_experimental_engines": True,
        "keep_audio_for_benchmark": False,
        "auto_fallback_to_faster_whisper": True,
        "show_engine_warnings": True,
        "speaker_map": {},
        "stt_context_bias": (
            "HTA, diabète de type 2, fibrillation auriculaire, insuffisance cardiaque, "
            "Eliquis, Kardégic, metformine, Forxiga, Ozempic, HbA1c, DFG, BNP, SpO2."
        ),
    },
    "faster_whisper": {
        "enabled": True,
        "model": DEFAULT_WHISPER_MODEL,
        "device": DEFAULT_WHISPER_DEVICE,
        "compute_type": DEFAULT_WHISPER_COMPUTE_TYPE,
        "language": "fr",
        "task": "transcribe",
        "force_language": True,
        "disable_language_detection": True,
        "segment_seconds": TRANSCRIPTION_WINDOW_SECONDS,
        "overlap_seconds": TRANSCRIPTION_OVERLAP_SECONDS,
        "temperature": DEFAULT_WHISPER_TEMPERATURE,
        "beam_size": DEFAULT_WHISPER_BEAM_SIZE,
        "vad_filter": True,
        "vad_parameters": {
            "min_silence_duration_ms": 700,
            "speech_pad_ms": 200,
        },
        "min_silence_duration_ms": 700,
        "speech_pad_ms": 200,
        "condition_on_previous_text": False,
        "no_speech_threshold": 0.6,
        "log_prob_threshold": -1.0,
        "compression_ratio_threshold": 2.4,
        "initial_prompt": DEFAULT_MEDICAL_WHISPER_PROMPT,
    },
    "audio_filter": {
        "enabled": True,
        "min_rms_for_transcription": 0.0015,
        "min_peak_for_transcription": 0.02,
        "min_duration_seconds": 0.8,
        "skip_silent_segments": True,
        "log_skipped_segments": True,
    },
    "transcription_cleaning": {
        "enabled": True,
        "remove_technical_blocks": True,
        "remove_known_asr_artifacts": True,
        "normalize_blood_pressure": True,
        "blocked_line_patterns": DEFAULT_BLOCKED_LINE_PATTERNS,
    },
    "qwen3_asr": {
        "enabled": False,
        "model": "Qwen3-ASR-0.6B",
        "runtime": "auto",
        "device": "cuda",
        "language": "fr",
        "mode": "batch",
        "timeout_seconds": 300,
        "external_cli_command": "",
    },
    "voxtral": {
        "enabled": False,
        "model": "Voxtral-Mini-3B",
        "runtime": "auto",
        "device": "cuda",
        "language": "fr",
        "mode": "batch",
        "enable_diarization": False,
        "enable_word_timestamps": False,
        "enable_context_biasing": True,
        "timeout_seconds": 300,
        "server_url": "http://127.0.0.1:8000",
        "external_cli_command": "",
    },
}


class STTEngineManager:
    def __init__(self, whisper_model_manager: WhisperModelManager):
        self.backends = {
            FASTER_WHISPER_ENGINE_ID: FasterWhisperBackend(whisper_model_manager),
            QWEN3_ASR_ENGINE_ID: Qwen3ASRBackend(),
            VOXTRAL_ENGINE_ID: VoxtralBackend(),
        }

    def available_engines(self) -> dict[str, str]:
        return dict(STT_ENGINE_LABELS)

    def backend(self, engine_id: str):
        normalized = normalize_engine_id(engine_id)
        if normalized not in self.backends:
            raise STTBackendError(f"moteur STT inconnu : {engine_id}", code="unknown_engine")
        return self.backends[normalized]

    def load(self, config: dict) -> dict:
        engine_id = active_engine_id(config)
        backend_config = backend_config_for(config, engine_id)
        backend = self.backend(engine_id)
        backend.load(backend_config)
        return backend.health_check()

    def unload(self, engine_id: str = "") -> dict:
        target = normalize_engine_id(engine_id) if engine_id else FASTER_WHISPER_ENGINE_ID
        backend = self.backend(target)
        backend.unload()
        return backend.health_check()

    def health_check(self, config: dict, engine_id: str = "") -> dict:
        target = normalize_engine_id(engine_id) if engine_id else active_engine_id(config)
        backend = self.backend(target)
        backend.load(backend_config_for(config, target))
        return backend.health_check()

    def transcribe_file(self, audio_path: str | Path, config: dict) -> dict:
        engine_id = active_engine_id(config)
        return self._transcribe_with_fallback(audio_path, config, engine_id)

    def transcribe_audio_array(self, audio, *, sample_rate: int, channels: int = 1, config: dict) -> dict:
        engine_id = active_engine_id(config)
        if engine_id == FASTER_WHISPER_ENGINE_ID:
            backend = self.backend(FASTER_WHISPER_ENGINE_ID)
            backend_config = backend_config_for(config, FASTER_WHISPER_ENGINE_ID)
            backend.load(backend_config)
            return backend.transcribe_audio_array(audio, sample_rate=sample_rate, channels=channels, options=backend_config)
        raise STTBackendError(
            "La transcription mémoire n'est disponible que pour faster-whisper. Utilise un fichier WAV pour ce moteur.",
            code="memory_transcription_unavailable",
            details={"engine": engine_id},
        )

    def compare_file(self, audio_path: str | Path, engine_ids: Iterable[str], config: dict) -> list[dict]:
        results = []
        for engine_id in engine_ids:
            target = normalize_engine_id(engine_id)
            try:
                local_config = {
                    **config,
                    "engine": target,
                    "auto_fallback_to_faster_whisper": False,
                }
                result = self._transcribe_once(audio_path, local_config, target)
            except Exception as exc:
                result = normalize_stt_result(
                    {
                        "engine": target,
                        "model": backend_config_for(config, target).get("model", ""),
                        "runtime": backend_config_for(config, target).get("runtime", ""),
                        "device": backend_config_for(config, target).get("device", ""),
                        "mode": backend_config_for(config, target).get("mode", "batch"),
                        "language": backend_config_for(config, target).get("language", "fr"),
                        "text": "",
                        "warnings": [],
                        "errors": [str(exc)],
                    }
                )
            results.append(result)
        return results

    def _transcribe_with_fallback(self, audio_path: str | Path, config: dict, engine_id: str) -> dict:
        try:
            return self._transcribe_once(audio_path, config, engine_id)
        except Exception as exc:
            if engine_id != FASTER_WHISPER_ENGINE_ID and bool(config.get("auto_fallback_to_faster_whisper", True)):
                fallback_config = {**config, "engine": FASTER_WHISPER_ENGINE_ID}
                fallback = self._transcribe_once(audio_path, fallback_config, FASTER_WHISPER_ENGINE_ID)
                fallback["warnings"].append(f"Fallback automatique vers faster-whisper après échec {engine_id}: {exc}")
                fallback["errors"].append(f"{engine_id}: {exc}")
                fallback["raw"] = {
                    **(fallback.get("raw") or {}),
                    "fallback_from": engine_id,
                    "fallback_reason": str(exc),
                }
                return fallback
            raise

    def _transcribe_once(self, audio_path: str | Path, config: dict, engine_id: str) -> dict:
        target = normalize_engine_id(engine_id)
        if target != FASTER_WHISPER_ENGINE_ID:
            if not bool(config.get("allow_experimental_engines", True)):
                raise STTBackendError("moteurs expérimentaux désactivés", code="experimental_engines_disabled")
            if not bool(backend_config_for(config, target).get("enabled", False)):
                raise STTBackendError(f"{STT_ENGINE_LABELS.get(target, target)} est désactivé.", code="engine_disabled")

        backend_config = backend_config_for(config, target)
        backend = self.backend(target)
        backend.load(backend_config)
        return backend.transcribe_file(audio_path, backend_config)


def ensure_stt_config(config: dict) -> bool:
    changed = False
    for section, defaults in DEFAULT_STT_CONFIG.items():
        target = config.setdefault(section, {})
        for key, value in defaults.items():
            if key not in target:
                target[key] = value
                changed = True

    whisper = config.setdefault("whisper", {})
    faster = config.setdefault("faster_whisper", {})
    mapping = {
        "default_model": "model",
        "device": "device",
        "compute_type": "compute_type",
        "language": "language",
        "task": "task",
        "segment_seconds": "segment_seconds",
        "overlap_seconds": "overlap_seconds",
        "vad_filter": "vad_filter",
        "min_silence_duration_ms": "min_silence_duration_ms",
        "condition_on_previous_text": "condition_on_previous_text",
        "initial_prompt": "initial_prompt",
        "temperature": "temperature",
        "beam_size": "beam_size",
        "no_speech_threshold": "no_speech_threshold",
        "log_prob_threshold": "log_prob_threshold",
        "compression_ratio_threshold": "compression_ratio_threshold",
    }
    for legacy_key, new_key in mapping.items():
        if legacy_key in whisper and faster.get(new_key) in (None, ""):
            faster[new_key] = whisper[legacy_key]
            changed = True
    return changed


def normalize_engine_id(value: str) -> str:
    text = str(value or "").strip()
    if text in STT_ENGINE_LABELS:
        return text
    if text in STT_ENGINE_IDS_BY_LABEL:
        return STT_ENGINE_IDS_BY_LABEL[text]
    normalized = text.lower().replace(" ", "_").replace("-", "_")
    if normalized in {"faster_whisper", "whisper"}:
        return FASTER_WHISPER_ENGINE_ID
    if normalized in {"qwen3_asr", "qwen_asr", "qwen3"}:
        return QWEN3_ASR_ENGINE_ID
    if normalized == "voxtral":
        return VOXTRAL_ENGINE_ID
    return FASTER_WHISPER_ENGINE_ID


def active_engine_id(config: dict) -> str:
    return normalize_engine_id(config.get("engine") or config.get("default_engine") or config.get("stt", {}).get("default_engine"))


def backend_config_for(config: dict, engine_id: str) -> dict:
    target = normalize_engine_id(engine_id)
    stt = dict(config.get("stt", {}))
    common = {
        "engine": target,
        "allow_experimental_engines": config.get(
            "allow_experimental_engines",
            stt.get("allow_experimental_engines", True),
        ),
        "auto_fallback_to_faster_whisper": config.get(
            "auto_fallback_to_faster_whisper",
            stt.get("auto_fallback_to_faster_whisper", True),
        ),
        "show_engine_warnings": config.get("show_engine_warnings", stt.get("show_engine_warnings", True)),
        "stt_context_bias": config.get("stt_context_bias", stt.get("stt_context_bias", "")),
    }

    if target == FASTER_WHISPER_ENGINE_ID:
        legacy = dict(config.get("whisper", {}))
        faster = dict(config.get("faster_whisper", {}))
        merged = {
            **legacy,
            **faster,
            **common,
            "audio_filter": dict(config.get("audio_filter", {})),
            "transcription_cleaning": dict(config.get("transcription_cleaning", {})),
            "model": canonical_french_whisper_model_name(
                config.get("model") or faster.get("model") or legacy.get("default_model") or DEFAULT_WHISPER_MODEL
            ),
            "device": config.get("device") or faster.get("device") or legacy.get("device") or DEFAULT_WHISPER_DEVICE,
            "compute_type": config.get("compute_type") or faster.get("compute_type") or legacy.get("compute_type") or DEFAULT_WHISPER_COMPUTE_TYPE,
            "language": "fr",
            "task": "transcribe",
            "force_language": True,
            "disable_language_detection": True,
            "condition_on_previous_text": bool_setting(
                config.get("condition_on_previous_text", faster.get("condition_on_previous_text", False)),
                False,
            ),
            "runtime": "python",
            "mode": config.get("mode") or "segments",
        }
        # `settings_override` is passed at the top level by short workflows
        # such as fly dictation. Those values must win over the persisted
        # main-transcription section (notably its longer prompt and hotwords).
        for key in (
            "beam_size",
            "best_of",
            "temperature",
            "vad_filter",
            "vad_parameters",
            "min_silence_duration_ms",
            "speech_pad_ms",
            "without_timestamps",
            "initial_prompt",
            "hotwords",
            "hotwords_count",
            "max_new_tokens",
            "no_speech_threshold",
            "log_prob_threshold",
            "compression_ratio_threshold",
        ):
            if key in config and config[key] is not None:
                merged[key] = config[key]
        return merged

    section = dict(config.get(target, {}))
    return {
        **section,
        **common,
        "model": config.get("model") or section.get("model") or "",
        "runtime": config.get("runtime") or section.get("runtime") or "auto",
        "device": config.get("device") or section.get("device") or "cuda",
        "mode": config.get("mode") or section.get("mode") or "batch",
        "language": config.get("language") or section.get("language") or "fr",
    }


def format_stt_text(result: dict, speaker_map: dict[str, str] | None = None) -> str:
    return format_text_with_speaker_mapping(result, speaker_map)


def bool_setting(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "oui", "on"}:
        return True
    if normalized in {"0", "false", "no", "non", "off", ""}:
        return False
    return default
