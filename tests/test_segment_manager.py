from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from segment_manager import SegmentedDictationSession


class FakeTranscriber:
    def __init__(self):
        self.calls = []

    def transcribe_file(self, path, *, segment_index: int):
        self.calls.append((Path(path).name, segment_index))
        return SimpleNamespace(text="texte final")


class SegmentedDictationSessionCompletionTests(unittest.TestCase):
    def test_wait_until_finished_waits_for_queued_transcription(self):
        transcriber = FakeTranscriber()
        results = []
        session = SegmentedDictationSession(
            transcriber=transcriber,
            settings_provider=lambda: {},
            on_transcription=results.append,
        )

        with tempfile.TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "segment.wav"
            audio_path.write_bytes(b"fake wav")

            session._finished_event.clear()
            session._queue.put((1, audio_path, False, ["checkpoint-1"]))
            session._queue.put(None)

            thread = threading.Thread(target=session._transcribe_loop)
            thread.start()

            self.assertTrue(session.wait_until_finished(2.0))
            thread.join(2.0)

        self.assertEqual(transcriber.calls, [("segment.wav", 1)])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].checkpoint_ids, ["checkpoint-1"])


if __name__ == "__main__":
    unittest.main()
