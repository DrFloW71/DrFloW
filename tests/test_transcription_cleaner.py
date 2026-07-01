from __future__ import annotations

import unittest

from transcription_cleaner import clean_transcription_text


class TranscriptionCleanerTests(unittest.TestCase):
    def test_removes_technical_blocks_prompt_echoes_and_caption_hallucinations(self):
        raw = """Gastroentérite, virale, diarrhée, vomissement.
[[Segment 2 sans texte détecté - silence ou mauvais micro ; durée=16.0s ; RMS=0.000282 ; peak=0.014771]]
Sous-titrage ST' 501
Transcription fidèle d’un échange oral entre médecine et patient, en français.
Ça fait 5 jours, la pression artérielle est à 120, 80.
Sous-titrage Société Radio-Canada
Et puis, sinon, il y a des technologies.
Depuis six mois, les deux nous font mal."""

        self.assertEqual(
            clean_transcription_text(raw),
            "\n".join(
                [
                    "Gastroentérite virale, diarrhée, vomissements.",
                    "Ça fait 5 jours, la pression artérielle est à 120/80.",
                    "Depuis six mois, les deux nous font mal.",
                ]
            ),
        )

    def test_keeps_valid_line_when_previous_line_is_artifact(self):
        raw = "Sous-titrage Société Radio-Canada\nÇa fait 5 jours, la pression artérielle est à 120, 80."

        self.assertEqual(
            clean_transcription_text(raw),
            "Ça fait 5 jours, la pression artérielle est à 120/80.",
        )


if __name__ == "__main__":
    unittest.main()
