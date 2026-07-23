from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from transcription_draft import TranscriptionDraftStore


class TranscriptionDraftStoreTests(unittest.TestCase):
    def test_transcription_is_saved_and_restored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "last_transcription.json"
            store = TranscriptionDraftStore(path)
            saved = store.save("Dernière transcription")
            restored = store.load()
            self.assertIsNotNone(saved)
            self.assertIsNotNone(restored)
            self.assertEqual(restored.text, "Dernière transcription")
            self.assertTrue(restored.saved_at)

    def test_empty_transcription_removes_previous_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "last_transcription.json"
            store = TranscriptionDraftStore(path)
            store.save("Texte à supprimer")
            self.assertTrue(path.exists())
            self.assertIsNone(store.save("  "))
            self.assertFalse(path.exists())
            self.assertIsNone(store.load())

    def test_invalid_draft_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "last_transcription.json"
            path.write_text("{invalid", encoding="utf-8")
            self.assertIsNone(TranscriptionDraftStore(path).load())

    def test_invalid_encoding_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "last_transcription.json"
            path.write_bytes(b"\xff\xfe\x00")
            self.assertIsNone(TranscriptionDraftStore(path).load())


if __name__ == "__main__":
    unittest.main()
