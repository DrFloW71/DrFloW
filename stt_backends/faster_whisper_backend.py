from __future__ import annotations

from pathlib import Path
from time import perf_counter

from stt_audio_utils import (
    analyze_audio_array,
    analyze_wav,
    audio_has_probable_signal,
    build_empty_reason,
    format_skipped_audio_log,
    prepare_audio_array_for_whisper,
    should_skip_audio_for_transcription,
)
from transcription_cleaner import WHISPER_MEDICAL_INITIAL_PROMPT, clean_transcription_text
from whisper_model_manager import (
    WhisperModelManager,
    WhisperSettings,
    french_whisper_model_substitution_warning,
)

from .base import STTBackend, normalize_stt_result


FORCED_FRENCH_INITIAL_PROMPT = WHISPER_MEDICAL_INITIAL_PROMPT
FORCED_FRENCH_WARNING = (
    "Attention : le moteur a détecté une langue différente du français malgré le forçage. "
    "Vérifier la transcription."
)


class FasterWhisperBackend(STTBackend):
    id = "faster-whisper"
    name = "faster-whisper"
    supports_batch = True
    supports_realtime = False
    supports_diarization = False
    supports_word_timestamps = False
    supports_context_biasing = True

    def __init__(self, model_manager: WhisperModelManager):
        super().__init__()
        self.model_manager = model_manager
        self._last_model_warning = ""

    def load(self, config: dict) -> None:
        super().load(config)
        settings = WhisperSettings.from_mapping(config or {})
        requested_model = str((config or {}).get("model") or (config or {}).get("default_model") or "").strip()
        self._last_model_warning = french_whisper_model_substitution_warning(requested_model, settings.model_name)
        self.model_manager.load(settings)

    def unload(self) -> None:
        if hasattr(self.model_manager, "unload_all"):
            self.model_manager.unload_all()
        super().unload()

    def transcribe_file(self, audio_path: str | Path, options: dict) -> dict:
        settings_map = dict(options or {})
        audio_stats = analyze_wav(audio_path)
        return self._transcribe(audio_path, settings_map, audio_stats=audio_stats)

    def transcribe_audio_array(
        self,
        audio,
        *,
        sample_rate: int,
        channels: int = 1,
        options: dict | None = None,
    ) -> dict:
        settings_map = dict(options or {})
        if int(sample_rate or 0) != 16000:
            raise RuntimeError("transcription mémoire réservée aux buffers audio 16 kHz")
        audio_stats = analyze_audio_array(audio, sample_rate=sample_rate, channels=channels)
        audio_source = prepare_audio_array_for_whisper(audio, channels=channels)
        return self._transcribe(audio_source, settings_map, audio_stats=audio_stats, audio_path="<memory>")

    def _transcribe(self, audio_source, settings_map: dict, *, audio_stats: dict, audio_path: str | None = None) -> dict:
        settings = WhisperSettings.from_mapping(settings_map)
        requested_model = str(settings_map.get("model") or settings_map.get("default_model") or "").strip()
        model_warning = french_whisper_model_substitution_warning(requested_model, settings.model_name)
        settings_map = {
            **settings_map,
            "model": settings.model_name,
            "default_model": settings.model_name,
        }
        started = perf_counter()
        warnings = [model_warning] if model_warning else []
        should_skip, skip_reason, filter_config = should_skip_audio_for_transcription(audio_stats, settings_map)
        if should_skip:
            segment_index = settings_map.get("segment_index") or "?"
            skipped_log = format_skipped_audio_log(segment_index, audio_stats, skip_reason)
            if filter_config.get("log_skipped_segments", True):
                warnings.append(skipped_log)
            return normalize_stt_result(
                {
                    "engine": self.id,
                    "model": settings.model_name,
                    "runtime": "python",
                    "device": settings.device,
                    "mode": settings_map.get("mode") or "segments",
                    "language": "fr",
                    "text": "",
                    "segments": [],
                    "duration_seconds": float(audio_stats.get("duration_seconds") or 0.0),
                    "processing_seconds": perf_counter() - started,
                    "warnings": warnings,
                    "errors": [],
                    "raw": {
                        "audio_path": str(audio_path or audio_source),
                        "audio_stats": audio_stats,
                        "segments_count": 0,
                        "retry_without_vad": False,
                        "empty_reason": skip_reason,
                        "model_label": settings.model_name,
                        "requested_model": requested_model,
                        "effective_model": settings.model_name,
                        "detected_language": "",
                        "skipped_by_audio_filter": True,
                        "audio_filter": filter_config,
                        "technical_logs": [skipped_log],
                    },
                }
            )

        model = self.model_manager.load(settings)

        vad_filter_enabled = bool_setting(settings_map.get("vad_filter"), True)
        text, segments, segments_count, detected_language = self._run_transcribe(
            model,
            audio_source,
            settings_map,
            vad_filter=vad_filter_enabled,
        )
        retry_without_vad = False

        if not text and vad_filter_enabled and audio_has_probable_signal(audio_stats, settings_map):
            retry_without_vad = True
            warnings.append("Aucun texte avec VAD, retry automatique sans VAD.")
            text, segments, segments_count, detected_language = self._run_transcribe(
                model,
                audio_source,
                settings_map,
                vad_filter=False,
            )

        if detected_language and not is_french_language_code(detected_language):
            warnings.append(FORCED_FRENCH_WARNING)

        text = clean_transcription_text(text, settings_map.get("transcription_cleaning"))
        cleaned_segments = []
        for segment in segments:
            segment_text = clean_transcription_text(segment.get("text", ""), settings_map.get("transcription_cleaning"))
            if not segment_text:
                continue
            cleaned_segments.append({**segment, "text": segment_text})

        empty_reason = "" if text else build_empty_reason(audio_stats, segments_count, retry_without_vad, settings_map)
        if empty_reason:
            warnings.append(empty_reason)

        return normalize_stt_result(
            {
                "engine": self.id,
                "model": settings.model_name,
                "runtime": "python",
                "device": settings.device,
                "mode": settings_map.get("mode") or "segments",
                "language": "fr",
                "text": text.strip(),
                "segments": cleaned_segments,
                "duration_seconds": float(audio_stats.get("duration_seconds") or 0.0),
                "processing_seconds": perf_counter() - started,
                "warnings": warnings,
                "errors": [],
                "raw": {
                    "audio_path": str(audio_path or audio_source),
                    "audio_stats": audio_stats,
                    "segments_count": segments_count,
                    "retry_without_vad": retry_without_vad,
                    "empty_reason": empty_reason,
                    "model_label": self.model_manager.active_label(),
                    "requested_model": requested_model,
                    "effective_model": settings.model_name,
                    "detected_language": detected_language,
                },
            }
        )

    def _run_transcribe(self, model, audio_source, settings_map: dict, *, vad_filter: bool) -> tuple[str, list[dict], int, str]:
        condition_on_previous_text = False
        initial_prompt = str(
            settings_map.get("initial_prompt")
            or settings_map.get("stt_context_bias")
            or FORCED_FRENCH_INITIAL_PROMPT
        )
        vad_parameters = dict(settings_map.get("vad_parameters") or {})
        vad_parameters.setdefault("min_silence_duration_ms", int(settings_map.get("min_silence_duration_ms") or 700))
        vad_parameters.setdefault("speech_pad_ms", int(settings_map.get("speech_pad_ms") or 200))
        transcribe_kwargs = {
            "language": "fr",
            "task": "transcribe",
            "beam_size": int(settings_map.get("beam_size") or 5),
            "vad_filter": vad_filter,
            "condition_on_previous_text": condition_on_previous_text,
            "initial_prompt": initial_prompt,
            "temperature": float(settings_map.get("temperature") if settings_map.get("temperature") is not None else 0.0),
            "no_speech_threshold": float(settings_map.get("no_speech_threshold") or 0.6),
            "log_prob_threshold": float(settings_map.get("log_prob_threshold") if settings_map.get("log_prob_threshold") is not None else -1.0),
            "compression_ratio_threshold": float(settings_map.get("compression_ratio_threshold") or 2.4),
        }
        if settings_map.get("best_of") is not None:
            transcribe_kwargs["best_of"] = int(settings_map.get("best_of") or 1)
        if vad_filter:
            transcribe_kwargs["vad_parameters"] = vad_parameters

        source = str(audio_source) if isinstance(audio_source, (str, Path)) else audio_source
        segments, info = model.transcribe(source, **transcribe_kwargs)
        detected_language = str(getattr(info, "language", "") or "").strip()
        segment_list = list(segments)
        normalized_segments = []
        for segment in segment_list:
            text = str(getattr(segment, "text", "") or "").strip()
            if not text:
                continue
            normalized_segments.append(
                {
                    "start": float(getattr(segment, "start", 0.0) or 0.0),
                    "end": float(getattr(segment, "end", 0.0) or 0.0),
                    "text": text,
                    "speaker": None,
                    "confidence": None,
                }
            )
        text = " ".join(segment["text"] for segment in normalized_segments).strip()
        return text, normalized_segments, len(segment_list), detected_language

    def health_check(self) -> dict:
        return {
            "engine": self.id,
            "name": self.name,
            "ok": True,
            "status": (
                f"{self.model_manager.active_label()} | "
                "Langue forcée : français | Tâche : transcription | "
                "Détection automatique de langue : désactivée"
            ),
            "warnings": [self._last_model_warning] if self._last_model_warning else [],
            "errors": [],
        }


def is_french_language_code(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return not normalized or normalized == "fr" or normalized.startswith("fr-") or normalized == "fra"


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
