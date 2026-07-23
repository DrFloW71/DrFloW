from __future__ import annotations

import unittest

from medical_transcription import (
    DEFAULT_MEDICAL_WHISPER_PROMPT,
    build_dynamic_whisper_prompt,
    build_hotword_bundle,
    clean_weda_medical_context,
    extract_weda_hotwords,
)


class MedicalPromptTests(unittest.TestCase):
    def test_default_prompt_is_used_without_context(self):
        final, dynamic = build_dynamic_whisper_prompt("")
        self.assertEqual(final, DEFAULT_MEDICAL_WHISPER_PROMPT)
        self.assertEqual(dynamic, "")

    def test_context_is_cleaned_limited_and_html_free(self):
        final, dynamic = build_dynamic_whisper_prompt(
            "Prompt base",
            "<b>Traitements</b>: Eliquis, ramipril.\nURL: https://weda.test/patient\nMenu Fermer",
            max_dynamic_characters=45,
        )
        self.assertNotIn("<b>", final)
        self.assertNotIn("https://", final)
        self.assertLessEqual(len(dynamic), 45)
        self.assertIn("Contexte patient possible", final)

    def test_context_can_be_disabled(self):
        final, dynamic = build_dynamic_whisper_prompt("Base", "Traitements: Eliquis", include_weda_context=False)
        self.assertEqual((final, dynamic), ("Base", ""))

    def test_repeated_context_chunks_are_removed(self):
        cleaned = clean_weda_medical_context("Diabète type 2. Diabète type 2. Metformine")
        self.assertEqual(cleaned.casefold().count("diabète type 2"), 1)


class HotwordTests(unittest.TestCase):
    def test_extracts_prioritized_medical_sections_and_filters_generic_words(self):
        terms = extract_weda_hotwords(
            "Traitements: Eliquis, Metformine\n"
            "Allergies: pénicilline\n"
            "Antécédents: diabète de type 2\n"
            "Autre: patient, consultation"
        )
        self.assertEqual(terms[:2], ["Eliquis", "Metformine"])
        self.assertIn("pénicilline", terms)
        self.assertNotIn("patient", [term.casefold() for term in terms])

    def test_bundle_deduplicates_case_and_respects_limits(self):
        bundle = build_hotword_bundle(
            ["Eliquis", "NT-proBNP"],
            "Traitements: eliquis, Metformine, Ramipril",
            ["ÉLIQUIS", "Forxiga"],
            max_hotwords=3,
            max_characters=100,
        )
        self.assertEqual(len(bundle.final), 3)
        self.assertEqual(sum(term.casefold() == "eliquis" for term in bundle.final), 1)

    def test_bundle_works_without_weda_context(self):
        bundle = build_hotword_bundle(["créatininémie"], "")
        self.assertEqual(bundle.weda, ())
        self.assertEqual(bundle.final, ("créatininémie",))


if __name__ == "__main__":
    unittest.main()
