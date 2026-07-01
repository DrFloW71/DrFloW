from __future__ import annotations

from .external_cli import ExternalCliSTTBackend


class Qwen3ASRBackend(ExternalCliSTTBackend):
    id = "qwen3_asr"
    name = "Qwen3-ASR"
    supports_batch = True
    supports_realtime = False
    supports_diarization = False
    supports_word_timestamps = False
    supports_context_biasing = True
