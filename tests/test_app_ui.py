from __future__ import annotations

import unittest

from app import migrate_main_notebook_tab_order


class MainNotebookTabOrderTests(unittest.TestCase):
    def test_legacy_transcription_tabs_are_merged_at_their_original_position(self):
        order = [
            "Contexte WEDA",
            "Transcription brute Whisper",
            "Transcription corrigée localement",
            "Document 1",
        ]

        self.assertEqual(
            migrate_main_notebook_tab_order(order),
            ["Contexte WEDA", "Transcription", "Document 1"],
        )

    def test_current_transcription_tab_order_is_unchanged(self):
        order = ["Contexte WEDA", "Transcription", "Document 1"]

        self.assertEqual(migrate_main_notebook_tab_order(order), order)


if __name__ == "__main__":
    unittest.main()
