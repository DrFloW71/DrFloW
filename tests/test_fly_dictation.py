from __future__ import annotations

import sys
import threading
import wave
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np

from app import AssistantApp

from stt_audio_utils import should_skip_audio_for_transcription
from transcriber import Transcriber, analyze_audio_array, prepare_audio_array_for_whisper
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


class FlyDictationFilterTests(unittest.TestCase):
    def test_fly_filter_accepts_valid_short_press_and_preserves_main_settings(self):
        config = {"fly_dictation": {"min_seconds": 0.2}, "audio_filter": {"min_duration_seconds": 0.8}}
        app = types.SimpleNamespace(config=config, get_whisper_settings=Mock(return_value={}))
        settings = AssistantApp.get_fly_whisper_settings(app)
        self.assertEqual(settings["audio_filter"]["min_duration_seconds"], 0.2)
        self.assertEqual(config["audio_filter"]["min_duration_seconds"], 0.8)
        stats = analyze_audio_array(np.full((6400, 1), 0.01, dtype="float32"), sample_rate=16000)
        self.assertFalse(should_skip_audio_for_transcription(stats, settings)[0])
        self.assertTrue(should_skip_audio_for_transcription(stats, config)[0])
        # Vérifier aussi la fusion des réglages et l'appel réel du backend.
        model = types.SimpleNamespace(transcribe=Mock(return_value=(
            [types.SimpleNamespace(start=0.0, end=0.4, text="Bonjour.")],
            types.SimpleNamespace(language="fr"),
        )))
        manager = types.SimpleNamespace(load=Mock(return_value=model), active_label=lambda: "fake-model")
        app.transcriber = Transcriber(manager, settings_provider=lambda: dict(config))
        app._fly_transcription_lock = threading.Lock()
        app.log_debug = Mock()
        result = AssistantApp.transcribe_fly_dictation_audio_buffer(
            app, np.full((6400, 1), 0.01, dtype="float32"),
            sample_rate=16000, channels=1, whisper_settings=settings, fallback_label="full",
        )
        self.assertEqual(result.text, "Bonjour.")
        model.transcribe.assert_called_once()

    def test_silence_result_shows_microphone_guidance_and_does_not_paste(self):
        app = types.SimpleNamespace(
            _fly_busy=True, model_status_var=Mock(), micro_status_var=Mock(),
            fly_dictation_status_var=Mock(), log_debug=Mock(), copy_and_paste_fly_dictation_text=Mock(),
        )
        result = types.SimpleNamespace(
            text="", model_label="fake", elapsed_seconds=0.0,
            empty_reason="audio_silent_or_wrong_input_device", audio_stats={"rms": 0.0005},
        )
        AssistantApp.on_fly_dictation_result(app, result, 5.0)
        self.assertFalse(app._fly_busy)
        self.assertIn("vérifier le menu Micro", app.fly_dictation_status_var.set.call_args.args[0])
        app.copy_and_paste_fly_dictation_text.assert_not_called()

    def test_punctuation_only_is_not_pasted_but_words_and_numbers_are_preserved(self):
        app = types.SimpleNamespace(
            _fly_busy=True, model_status_var=Mock(), fly_dictation_status_var=Mock(),
            log_debug=Mock(), copy_and_paste_fly_dictation_text=Mock(),
        )
        for text in ["...", "…", " . — ! "]:
            result = types.SimpleNamespace(text=text, model_label="fake", elapsed_seconds=0.0)
            AssistantApp.on_fly_dictation_result(app, result, 2.0)
            self.assertEqual(app.log_debug.call_args.args[2], "fly_dictation_nonverbal_result")
        app.copy_and_paste_fly_dictation_text.assert_not_called()
        for text in ["Bonjour.", "120/80", "é"]:
            result = types.SimpleNamespace(text=text, model_label="fake", elapsed_seconds=0.0)
            AssistantApp.on_fly_dictation_result(app, result, 2.0)
            app.copy_and_paste_fly_dictation_text.assert_called_with(text)


class FlyDictationMissingAudioTests(unittest.TestCase):
    def make_app(self, *, frames, duration):
        recorder = types.SimpleNamespace(
            duration_seconds=Mock(return_value=duration),
            stop=Mock(return_value=np.zeros((frames, 1), dtype="float32")),
            sample_rate=16000,
            channels=1,
            device=2,
        )
        app = types.SimpleNamespace(
            _fly_recording=True,
            _fly_recorder=recorder,
            _fly_busy=False,
            set_recording_indicator=Mock(),
            micro_status_var=Mock(),
            fly_dictation_status_var=Mock(),
            get_fly_dictation_settings=Mock(return_value={"min_seconds": 0.2}),
            log_debug=Mock(),
        )
        return app

    def test_long_press_without_frames_is_reported_as_microphone_failure(self):
        app = self.make_app(frames=0, duration=7.0)
        AssistantApp.stop_fly_dictation_recording(app)
        self.assertFalse(app._fly_busy)
        self.assertFalse(app._fly_recording)
        self.assertIsNone(app._fly_recorder)
        self.assertEqual(app.log_debug.call_args.args[2], "fly_dictation_audio_missing")
        self.assertEqual(app.log_debug.call_args.args[4]["frames"], 0)
        app.micro_status_var.set.assert_called_with("Micro: aucune donnée audio")

    def test_short_press_with_frames_still_reports_short_press(self):
        app = self.make_app(frames=160, duration=0.1)
        AssistantApp.stop_fly_dictation_recording(app)
        self.assertFalse(app._fly_busy)
        self.assertEqual(app.log_debug.call_args.args[2], "fly_dictation_too_short")


class FlyDictationLongAudioTests(unittest.TestCase):
    def make_app(self):
        segments = [
            types.SimpleNamespace(start=0.0, end=20.0, text="Le début est complet."),
            types.SimpleNamespace(start=31.0, end=45.0, text="Après la pause, la dictée continue."),
            types.SimpleNamespace(start=58.0, end=61.0, text="La dernière phrase est conservée."),
        ]
        model = types.SimpleNamespace(
            transcribe=Mock(return_value=(segments, types.SimpleNamespace(language="fr")))
        )
        manager = types.SimpleNamespace(load=Mock(return_value=model), active_label=lambda: "fake-model")
        # Une ancienne limite dans la section principale ne doit pas réapparaître.
        base_settings = {
            "engine": "faster-whisper",
            "faster_whisper": {"max_new_tokens": 128, "without_timestamps": True},
        }
        app = types.SimpleNamespace(
            config={"security": {"auto_delete_audio": True}},
            _fly_transcription_lock=threading.Lock(),
            transcriber=Transcriber(manager, settings_provider=lambda: dict(base_settings)),
            log_debug=Mock(),
        )
        settings = {
            "engine": "faster-whisper", "model": "large-v3-turbo", "device": "cpu",
            "compute_type": "int8", "max_new_tokens": 128, "without_timestamps": True,
            "vad_filter": False,
        }
        return app, model, settings

    def transcribe(self, app, audio, settings, *, sample_rate=16000):
        return AssistantApp.transcribe_fly_dictation_audio_buffer(
            app, audio, sample_rate=sample_rate, channels=1,
            whisper_settings=settings, fallback_label="full",
        )

    def test_long_audio_keeps_all_samples_and_text_after_pauses(self):
        app, model, settings = self.make_app()
        audio = np.full((61 * 16000, 1), 0.01, dtype="float32")
        audio[20 * 16000:31 * 16000] = 0.0

        result = self.transcribe(app, audio, settings)

        np.testing.assert_array_equal(model.transcribe.call_args.args[0], audio[:, 0])
        kwargs = model.transcribe.call_args.kwargs
        self.assertNotIn("max_new_tokens", kwargs)
        self.assertFalse(kwargs["without_timestamps"])
        self.assertEqual(result.text.splitlines(), [
            "Le début est complet.", "Après la pause, la dictée continue.",
            "La dernière phrase est conservée.",
        ])
        self.assertEqual(result.segments_count, 3)
        self.assertEqual(settings["max_new_tokens"], 128)
        self.assertTrue(settings["without_timestamps"])

    def test_short_audio_keeps_fast_decoding(self):
        app, model, settings = self.make_app()
        self.transcribe(app, np.full((10 * 16000, 1), 0.01, dtype="float32"), settings)
        kwargs = model.transcribe.call_args.kwargs
        self.assertEqual(kwargs["max_new_tokens"], 128)
        self.assertTrue(kwargs["without_timestamps"])

    def test_long_audio_protection_uses_sample_duration_at_other_sample_rates(self):
        app, model, settings = self.make_app()
        # Le backend mémoire impose 16 kHz : on contrôle ici les réglages transmis.
        app.transcriber.transcribe_audio_array = Mock(return_value=object())
        self.transcribe(app, np.zeros((11 * 8000, 1), dtype="float32"), settings, sample_rate=8000)
        effective = app.transcriber.transcribe_audio_array.call_args.kwargs["settings_override"]
        self.assertEqual(effective["max_new_tokens"], 0)
        self.assertFalse(effective["without_timestamps"])

    def test_long_audio_protection_survives_wav_fallback(self):
        app, model, settings = self.make_app()
        app.transcriber.transcribe_audio_array = Mock(side_effect=RuntimeError("memory unsupported"))
        audio = np.full((31 * 16000, 1), 0.01, dtype="float32")
        captured_frames = []
        original_transcribe = model.transcribe

        def transcribe_wav(source, **kwargs):
            with wave.open(source, "rb") as wav:
                captured_frames.append(wav.getnframes())
            return original_transcribe(source, **kwargs)

        model.transcribe = Mock(side_effect=transcribe_wav)
        result = self.transcribe(app, audio, settings)

        self.assertEqual(captured_frames, [len(audio)])
        self.assertNotIn("max_new_tokens", model.transcribe.call_args.kwargs)
        self.assertFalse(model.transcribe.call_args.kwargs["without_timestamps"])
        self.assertIn("La dernière phrase est conservée.", result.text)
        self.assertFalse(Path(result.audio_path).exists())


    def test_long_audio_protection_survives_cuda_fallback(self):
        app, _model, settings = self.make_app()
        settings["device"] = "cuda"
        settings["compute_type"] = "float16"
        app.root = types.SimpleNamespace(after=Mock())
        app.fly_dictation_cpu_fallback_settings = types.MethodType(
            AssistantApp.fly_dictation_cpu_fallback_settings, app,
        )
        expected_result = object()
        app.transcriber.transcribe_audio_array = Mock(
            side_effect=[RuntimeError("cublas64_12.dll not found"), expected_result]
        )

        result = self.transcribe(app, np.zeros((31 * 16000, 1), dtype="float32"), settings)

        self.assertIs(result, expected_result)
        self.assertTrue(app._fly_cuda_runtime_failed)
        self.assertEqual(app.transcriber.transcribe_audio_array.call_count, 2)
        effective = app.transcriber.transcribe_audio_array.call_args.kwargs["settings_override"]
        self.assertEqual(effective["device"], "cpu")
        self.assertEqual(effective["compute_type"], "int8")
        self.assertEqual(effective["max_new_tokens"], 0)
        self.assertFalse(effective["without_timestamps"])
        self.assertEqual(settings["device"], "cuda")


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
