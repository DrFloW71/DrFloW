from __future__ import annotations

import types
import unittest
from unittest.mock import Mock, patch

import numpy as np

from audio_recorder import PushToTalkRecorder


class PushToTalkRecorderTests(unittest.TestCase):
    def make_stream(self, *, audio=None, error=None):
        stream = Mock()

        def create_stream(**kwargs):
            def start():
                if error is not None:
                    raise error
                if audio is not None:
                    kwargs["callback"](audio, len(audio), None, None)
            stream.start.side_effect = start
            return stream

        return stream, types.SimpleNamespace(InputStream=Mock(side_effect=create_stream))

    def test_disconnected_device_is_rejected_even_when_stream_start_succeeds(self):
        stream, sd = self.make_stream()
        recorder = PushToTalkRecorder(device="2")
        with patch.dict("sys.modules", {"sounddevice": sd}), patch.object(
            recorder._first_frame, "wait", return_value=False
        ):
            with self.assertRaisesRegex(RuntimeError, "aucune donnée audio"):
                recorder.start()
        stream.close.assert_called_once_with()
        self.assertIsNone(recorder._stream)
        self.assertEqual(recorder.duration_seconds(), 0.0)

    def test_silence_is_valid_audio_and_selected_device_is_preserved(self):
        audio = np.zeros((160, 1), dtype="float32")
        stream, sd = self.make_stream(audio=audio)
        recorder = PushToTalkRecorder(device="2")
        with patch.dict("sys.modules", {"sounddevice": sd}):
            recorder.start()
            result = recorder.stop()
        np.testing.assert_array_equal(result, audio)
        self.assertEqual(sd.InputStream.call_args.kwargs["device"], 2)
        stream.stop.assert_called_once_with()
        stream.close.assert_called_once_with()

    def test_stream_start_failure_closes_device_and_allows_retry(self):
        stream, sd = self.make_stream(error=RuntimeError("device unavailable"))
        recorder = PushToTalkRecorder()
        with patch.dict("sys.modules", {"sounddevice": sd}):
            with self.assertRaisesRegex(RuntimeError, "device unavailable"):
                recorder.start()
        stream.close.assert_called_once_with()
        self.assertIsNone(recorder._stream)
        audio = np.ones((160, 1), dtype="float32")
        _, healthy_sd = self.make_stream(audio=audio)
        with patch.dict("sys.modules", {"sounddevice": healthy_sd}):
            recorder.start()
            np.testing.assert_array_equal(recorder.stop(), audio)

    def test_successful_recording_does_not_mask_a_later_disconnection(self):
        recorder = PushToTalkRecorder()
        _, healthy_sd = self.make_stream(audio=np.zeros((160, 1), dtype="float32"))
        with patch.dict("sys.modules", {"sounddevice": healthy_sd}):
            recorder.start()
            recorder.stop()
        stream, disconnected_sd = self.make_stream()
        with patch.dict("sys.modules", {"sounddevice": disconnected_sd}):
            recorder.FIRST_FRAME_TIMEOUT_SECONDS = 0
            with self.assertRaisesRegex(RuntimeError, "aucune donnée audio"):
                recorder.start()
        stream.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
