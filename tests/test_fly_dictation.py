from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

import numpy as np

from stt_audio_utils import should_skip_audio_for_transcription
from transcriber import analyze_audio_array, prepare_audio_array_for_whisper
from whisper_model_manager import WhisperModelManager, WhisperSettings, canonical_french_whisper_model_name


class FlyDictationAudioTests(unittest.TestCase):
    def test_audio_array_analysis_uses_memory_buffer(self):
        audio = np.full((1600, 1), 0.01, dtype="float32")

        stats = analyze_audio_array(audio, sample_rate=16000, channels=1)

        self.assertEqual(stats["path"], "<memory>")
        self.assertEqual(stats["frames"], 1600)
        self.assertEqual(stats["sample_rate"], 16000)
        self.assertGreater(stats["file_bytes"], 0)
        self.assertGreater(stats["rms"], 0)
        self.assertGreater(stats["non_silent_ratio_0_005"], 0)

    def test_audio_array_is_prepared_as_mono_float32(self):
        left = np.full(1600, 0.02, dtype="float32")
        right = np.full(1600, 0.04, dtype="float32")
        stereo = np.column_stack([left, right])

        prepared = prepare_audio_array_for_whisper(stereo, channels=2)

        self.assertEqual(prepared.shape, (1600,))
        self.assertEqual(prepared.dtype, np.float32)
        self.assertTrue(prepared.flags["C_CONTIGUOUS"])
        self.assertAlmostEqual(float(prepared[0]), 0.03, places=6)

    def test_audio_filter_keeps_low_level_probable_signal(self):
        should_skip, reason, _config = should_skip_audio_for_transcription(
            {
                "duration_seconds": 2.0,
                "rms": 0.0013,
                "peak": 0.018,
                "non_silent_ratio_0_005": 0.02,
            },
            {
                "audio_filter": {
                    "enabled": True,
                    "min_rms_for_transcription": 0.0015,
                    "min_peak_for_transcription": 0.02,
                    "min_duration_seconds": 0.8,
                    "skip_silent_segments": True,
                }
            },
        )

        self.assertFalse(should_skip)
        self.assertEqual(reason, "")


class WhisperModelManagerCacheTests(unittest.TestCase):
    def test_french_whisper_model_aliases_are_sanitized(self):
        self.assertEqual(canonical_french_whisper_model_name("faster-distil-whisper-large-v3"), "large-v3")
        self.assertEqual(canonical_french_whisper_model_name("distil-large-v3"), "large-v3")
        self.assertEqual(canonical_french_whisper_model_name("tiny.en"), "tiny")
        self.assertEqual(WhisperSettings.from_mapping({"model": "distil-large-v3"}).model_name, "large-v3")

    def test_manager_keeps_distinct_models_cached(self):
        created = []

        class FakeWhisperModel:
            def __init__(self, model_name, **kwargs):
                self.model_name = model_name
                self.kwargs = kwargs
                created.append(self)

        fake_module = types.SimpleNamespace(WhisperModel=FakeWhisperModel)
        manager = WhisperModelManager()
        settings_a = WhisperSettings(model_name="medium", device="cpu", compute_type="int8", cpu_threads=4)
        settings_b = WhisperSettings(model_name="large-v3", device="cpu", compute_type="int8", cpu_threads=4)

        with patch.dict(sys.modules, {"faster_whisper": fake_module}):
            model_a_first = manager.load(settings_a)
            model_a_second = manager.load(settings_a)
            model_b = manager.load(settings_b)
            model_a_third = manager.load(settings_a)

        self.assertIs(model_a_first, model_a_second)
        self.assertIs(model_a_first, model_a_third)
        self.assertIsNot(model_a_first, model_b)
        self.assertEqual(len(created), 2)


if __name__ == "__main__":
    unittest.main()
