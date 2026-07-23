from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

from stt_backends.faster_whisper_backend import (
    FORCED_FRENCH_WARNING,
    FasterWhisperBackend,
    fit_whisper_context_bias,
)


class FasterWhisperBackendLanguageTests(unittest.TestCase):
    def test_combined_prompt_and_hotwords_are_kept_below_model_limit(self):
        model = SimpleNamespace(hf_tokenizer=FakeTokenizer())
        prompt, hotwords, diagnostics = fit_whisper_context_bias(
            model,
            " ".join(f"prompt{i}" for i in range(300)),
            ", ".join(f"hotword{i}" for i in range(300)),
        )

        self.assertLessEqual(diagnostics["initial_prompt_tokens"] + diagnostics["hotwords_tokens"], 240)
        self.assertLessEqual(diagnostics["initial_prompt_tokens"], 160)
        self.assertTrue(diagnostics["trimmed"])
        self.assertTrue(prompt)
        self.assertTrue(hotwords)
    def test_transcribe_forces_french_transcription_even_if_config_disagrees(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "audio.wav"
            write_silent_wav(audio_path)
            model = FakeWhisperModel(language="en")
            backend = FasterWhisperBackend(FakeWhisperModelManager(model))

            result = backend.transcribe_file(
                audio_path,
                {
                    "model": "distil-large-v3",
                    "language": "en",
                    "task": "translate",
                    "condition_on_previous_text": True,
                    "vad_filter": True,
                    "min_silence_duration_ms": 500,
                    "audio_filter": {"enabled": False},
                },
            )

            kwargs = model.calls[0]
            self.assertEqual(kwargs["language"], "fr")
            self.assertEqual(kwargs["task"], "transcribe")
            self.assertFalse(kwargs["condition_on_previous_text"])
            self.assertEqual(kwargs["vad_parameters"], {"min_silence_duration_ms": 500, "speech_pad_ms": 200})
            self.assertEqual(kwargs["temperature"], 0.0)
            self.assertEqual(kwargs["no_speech_threshold"], 0.6)
            self.assertEqual(kwargs["log_prob_threshold"], -1.0)
            self.assertEqual(kwargs["compression_ratio_threshold"], 2.4)
            self.assertEqual(result["model"], "large-v3")
            self.assertEqual(result["raw"]["requested_model"], "distil-large-v3")
            self.assertEqual(result["raw"]["effective_model"], "large-v3")
            self.assertEqual(result["language"], "fr")
            self.assertTrue(any("distil-large-v3" in warning for warning in result["warnings"]))
            self.assertIn(FORCED_FRENCH_WARNING, result["warnings"])

    def test_invalid_faster_distil_alias_is_never_sent_to_faster_whisper(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "audio.wav"
            write_silent_wav(audio_path)
            model = FakeWhisperModel(language="fr")
            manager = FakeWhisperModelManager(model)
            backend = FasterWhisperBackend(manager)

            result = backend.transcribe_file(audio_path, {
                "model": "faster-distil-whisper-large-v3",
                "vad_filter": False,
                "audio_filter": {"enabled": False},
            })

            self.assertEqual(manager.loaded_settings[-1].model_name, "large-v3")
            self.assertEqual(result["model"], "large-v3")
            self.assertEqual(result["raw"]["requested_model"], "faster-distil-whisper-large-v3")
            self.assertEqual(result["raw"]["effective_model"], "large-v3")
            self.assertTrue(any("faster-distil-whisper-large-v3" in warning for warning in result["warnings"]))

    def test_non_distil_defaults_condition_on_previous_text_to_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "audio.wav"
            write_silent_wav(audio_path)
            model = FakeWhisperModel(language="fr")
            backend = FasterWhisperBackend(FakeWhisperModelManager(model))

            backend.transcribe_file(audio_path, {
                "model": "large-v3",
                "vad_filter": False,
                "condition_on_previous_text": "false",
                "audio_filter": {"enabled": False},
            })

            self.assertFalse(model.calls[0]["condition_on_previous_text"])
            self.assertEqual(model.calls[0]["language"], "fr")
            self.assertEqual(model.calls[0]["task"], "transcribe")

    def test_without_timestamps_option_is_forwarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "audio.wav"
            write_silent_wav(audio_path)
            model = FakeWhisperModel(language="fr")
            backend = FasterWhisperBackend(FakeWhisperModelManager(model))

            backend.transcribe_file(audio_path, {
                "model": "large-v3-turbo",
                "vad_filter": False,
                "without_timestamps": True,
                "audio_filter": {"enabled": False},
            })

            self.assertTrue(model.calls[0]["without_timestamps"])

    def test_max_new_tokens_limits_short_workflow_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "audio.wav"
            write_silent_wav(audio_path)
            model = FakeWhisperModel(language="fr")
            backend = FasterWhisperBackend(FakeWhisperModelManager(model))

            backend.transcribe_file(audio_path, {
                "model": "large-v3-turbo",
                "vad_filter": False,
                "max_new_tokens": 128,
                "audio_filter": {"enabled": False},
            })

            self.assertEqual(model.calls[0]["max_new_tokens"], 128)

    def test_silent_segment_is_skipped_before_model_transcribe(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "audio.wav"
            write_silent_wav(audio_path)
            model = FakeWhisperModel(language="fr")
            manager = FakeWhisperModelManager(model)
            backend = FasterWhisperBackend(manager)

            result = backend.transcribe_file(audio_path, {
                "model": "large-v3",
                "vad_filter": True,
                "segment_index": 2,
                "audio_filter": {
                    "enabled": True,
                    "min_rms_for_transcription": 0.0015,
                    "min_peak_for_transcription": 0.02,
                    "min_duration_seconds": 0.1,
                    "skip_silent_segments": True,
                    "log_skipped_segments": True,
                },
            })

            self.assertEqual(model.calls, [])
            self.assertEqual(manager.loaded_settings, [])
            self.assertEqual(result["text"], "")
            self.assertTrue(result["raw"]["skipped_by_audio_filter"])
            self.assertEqual(result["raw"]["empty_reason"], "audio_silent_or_wrong_input_device")
            self.assertTrue(any("Segment 2 ignoré" in warning for warning in result["warnings"]))

    def test_hotwords_are_forwarded_when_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "audio.wav"
            write_silent_wav(audio_path)
            model = FakeWhisperModel(language="fr")
            backend = FasterWhisperBackend(FakeWhisperModelManager(model))
            result = backend.transcribe_file(audio_path, {
                "model": "large-v3",
                "vad_filter": False,
                "hotwords": "Eliquis, metformine",
                "hotwords_count": 2,
                "audio_filter": {"enabled": False},
            })
            self.assertEqual(model.calls[0]["hotwords"], "Eliquis, metformine")
            self.assertTrue(result["raw"]["hotwords_supported"])
            self.assertEqual(result["raw"]["hotwords_count"], 2)

    def test_unsupported_hotwords_retry_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "audio.wav"
            write_silent_wav(audio_path)
            model = FakeWhisperModelWithoutHotwords(language="fr")
            backend = FasterWhisperBackend(FakeWhisperModelManager(model))
            result = backend.transcribe_file(audio_path, {
                "model": "large-v3",
                "vad_filter": False,
                "hotwords": "Eliquis",
                "hotwords_count": 1,
                "audio_filter": {"enabled": False},
            })
            self.assertEqual(len(model.calls), 2)
            self.assertNotIn("hotwords", model.calls[-1])
            self.assertFalse(result["raw"]["hotwords_supported"])
            self.assertTrue(any("ne prend pas en charge" in warning for warning in result["warnings"]))


class FakeSegment:
    start = 0.0
    end = 1.0
    text = "Bonjour docteur"


class FakeWhisperModel:
    def __init__(self, *, language: str):
        self.language = language
        self.calls: list[dict] = []

    def transcribe(self, _source, **kwargs):
        self.calls.append(dict(kwargs))
        return [FakeSegment()], SimpleNamespace(language=self.language)


class FakeWhisperModelWithoutHotwords(FakeWhisperModel):
    def transcribe(self, _source, **kwargs):
        self.calls.append(dict(kwargs))
        if "hotwords" in kwargs:
            raise TypeError("unexpected keyword argument 'hotwords'")
        return [FakeSegment()], SimpleNamespace(language=self.language)


class FakeWhisperModelManager:
    def __init__(self, model):
        self.model = model
        self.loaded_settings = []

    def load(self, settings):
        self.loaded_settings.append(settings)
        return self.model

    def active_label(self):
        return "fake-model"


class FakeTokenizer:
    def encode(self, value, add_special_tokens=False):
        del add_special_tokens
        return SimpleNamespace(ids=str(value).split())

    def decode(self, values, skip_special_tokens=True):
        del skip_special_tokens
        return " ".join(values)


def write_silent_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)


if __name__ == "__main__":
    unittest.main()
