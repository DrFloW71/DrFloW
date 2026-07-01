from __future__ import annotations

from .base import STTBackend, STTBackendError, normalize_stt_result
from .faster_whisper_backend import FasterWhisperBackend
from .qwen3_asr_backend import Qwen3ASRBackend
from .voxtral_backend import VoxtralBackend

__all__ = [
    "STTBackend",
    "STTBackendError",
    "normalize_stt_result",
    "FasterWhisperBackend",
    "Qwen3ASRBackend",
    "VoxtralBackend",
]
