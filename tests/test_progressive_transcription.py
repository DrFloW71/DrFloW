from __future__ import annotations

import unittest

import numpy as np

from progressive_transcription import ProgressiveAudioWindowBuffer, deduplicate_transcription_overlap


class ProgressiveAudioWindowBufferTests(unittest.TestCase):
    def build_windows(self, seconds: int, *, sample_rate: int = 10):
        samples = np.arange(seconds * sample_rate, dtype="float32").reshape(-1, 1)
        buffer = ProgressiveAudioWindowBuffer(sample_rate=sample_rate, window_seconds=30, overlap_seconds=2)
        windows = []
        for start in range(0, len(samples), 37):
            windows.extend(buffer.add(samples[start:start + 37]))
        final = buffer.flush()
        if final:
            windows.append(final)
        return samples, windows

    def assert_all_samples_covered(self, samples, windows):
        covered = set()
        for window in windows:
            covered.update(int(value) for value in window.audio.reshape(-1))
        self.assertEqual(covered, set(range(len(samples))))
        self.assertEqual([window.index for window in windows], list(range(1, len(windows) + 1)))

    def test_less_than_window_is_flushed(self):
        samples, windows = self.build_windows(12)
        self.assertEqual(len(windows), 1)
        self.assertTrue(windows[0].final)
        self.assert_all_samples_covered(samples, windows)

    def test_exact_window_does_not_duplicate_overlap_at_flush(self):
        samples, windows = self.build_windows(30)
        self.assertEqual(len(windows), 1)
        self.assertFalse(windows[0].final)
        self.assertEqual(windows[0].duration_seconds, 30)
        self.assert_all_samples_covered(samples, windows)

    def test_31_seconds_has_overlapped_final_window(self):
        samples, windows = self.build_windows(31)
        self.assertEqual([round(window.duration_seconds) for window in windows], [30, 3])
        self.assertEqual(windows[1].start_seconds, 28)
        self.assert_all_samples_covered(samples, windows)

    def test_60_seconds_preserves_order_overlap_and_tail(self):
        samples, windows = self.build_windows(60)
        self.assertEqual([window.start_seconds for window in windows], [0, 28, 56])
        self.assertEqual([window.end_seconds for window in windows], [30, 58, 60])
        self.assert_all_samples_covered(samples, windows)

    def test_several_minutes_have_no_missing_samples(self):
        samples, windows = self.build_windows(301)
        self.assertGreater(len(windows), 10)
        self.assert_all_samples_covered(samples, windows)

    def test_checkpoint_flush_can_continue_without_losing_samples(self):
        samples = np.arange(450, dtype="float32").reshape(-1, 1)
        buffer = ProgressiveAudioWindowBuffer(sample_rate=10, window_seconds=30, overlap_seconds=2)
        windows = buffer.add(samples[:120])
        checkpoint = buffer.flush(continue_stream=True)
        self.assertIsNotNone(checkpoint)
        windows.append(checkpoint)
        windows.extend(buffer.add(samples[120:]))
        final = buffer.flush()
        if final:
            windows.append(final)
        self.assertEqual([window.start_seconds for window in windows], [0, 12, 40])
        self.assert_all_samples_covered(samples, windows)


class OverlapDeduplicationTests(unittest.TestCase):
    def assert_append(self, previous: str, incoming: str, expected: str):
        self.assertEqual(deduplicate_transcription_overlap(previous, incoming).text_to_append, expected)

    def test_real_repetition_is_removed(self):
        self.assert_append(
            "Le patient prend de la metformine matin et soir.",
            "de la metformine matin et soir. Depuis trois jours il a mal.",
            "Depuis trois jours il a mal.",
        )

    def test_case_punctuation_and_accents_are_tolerated(self):
        self.assert_append(
            "Traitement par HÉMOGLOBINE glyquée",
            "hémoglobine glyquee, contrôlée hier.",
            "contrôlée hier.",
        )

    def test_negation_is_preserved(self):
        self.assert_append("Le patient signale pas de fièvre", "pas de fièvre mais des frissons", "mais des frissons")

    def test_laterality_difference_is_not_removed(self):
        incoming = "douleur du genou gauche depuis hier"
        self.assert_append("douleur du genou droit", incoming, incoming)

    def test_numbers_are_not_fuzzily_deduplicated(self):
        incoming = "metformine 1000 mg matin et soir"
        self.assert_append("metformine 500 mg matin et soir", incoming, incoming)

    def test_no_overlap(self):
        self.assert_append("Pas de toux.", "Le sommeil est bon.", "Le sommeil est bon.")


if __name__ == "__main__":
    unittest.main()
