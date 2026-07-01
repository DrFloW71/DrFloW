from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from prompt_manager import PromptManager
from secondary_analysis import (
    append_missing_secondary_sections,
    append_missing_tertiary_sections,
    build_secondary_prompt_variables,
    build_tertiary_prompt_variables,
    find_unresolved_variables,
    normalize_secondary_analysis_config,
    normalize_tertiary_analysis_config,
)


class SecondaryAnalysisTests(unittest.TestCase):
    def test_prompt_manager_treats_missing_type_as_generic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompts.json"
            path.write_text(
                '[{"id":"legacy","name":"Ancien","content":"A","is_default":true},'
                '{"id":"secondary","name":"Secondaire","content":"B","prompt_type":"secondary"}]',
                encoding="utf-8",
            )

            manager = PromptManager(path)
            compatible = manager.list_prompts(("secondary", "generic"))

            self.assertEqual([prompt.id for prompt in compatible], ["legacy", "secondary"])
            self.assertEqual(manager.get("legacy").prompt_type, "generic")
            self.assertEqual(manager.get("secondary").prompt_type, "generic")

    def test_prompt_manager_maps_legacy_general_type_to_generic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompts.json"
            path.write_text(
                '[{"id":"old-general","name":"Ancien general","content":"A","prompt_type":"general"}]',
                encoding="utf-8",
            )

            manager = PromptManager(path)

            self.assertEqual(manager.get("old-general").prompt_type, "generic")
            self.assertEqual(manager.list_prompts("generic")[0].id, "old-general")

    def test_secondary_variables_include_result_aliases_and_prompt_metadata(self):
        variables = build_secondary_prompt_variables(
            {"transcription": "texte dicté", "weda_context": "contexte"},
            prompt_1_name="Observation",
            prompt_1_content="Prompt 1",
            prompt_2_name="Actions",
            prompt_2_content="Prompt 2",
            result_1="Résultat primaire",
        )

        self.assertEqual(variables["result_1"], "Résultat primaire")
        self.assertEqual(variables["lmstudio_result"], "Résultat primaire")
        self.assertEqual(variables["prompt_1_name"], "Observation")
        self.assertEqual(variables["prompt_2_content"], "Prompt 2")

    def test_prompt_manager_maps_legacy_tertiary_type_to_common_generic_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = PromptManager(Path(tmp) / "prompts.json")
            prompt = manager.create("Prompt 3", "Analyse finale", prompt_type="tertiary")

            self.assertEqual(prompt.prompt_type, "generic")
            self.assertEqual(manager.list_prompts("tertiary")[0].id, prompt.id)
            self.assertEqual(manager.list_prompts("generic")[0].id, prompt.id)

    def test_tertiary_variables_include_result_2_and_prompt_metadata(self):
        variables = build_tertiary_prompt_variables(
            {"transcription": "texte dicté", "weda_context": "contexte"},
            prompt_1_name="Observation",
            prompt_1_content="Prompt 1",
            prompt_2_name="Actions",
            prompt_2_content="Prompt 2",
            prompt_3_name="Synthèse finale",
            prompt_3_content="Prompt 3",
            result_1="Résultat primaire",
            result_2="Résultat secondaire",
        )

        self.assertEqual(variables["result_1"], "Résultat primaire")
        self.assertEqual(variables["result_2"], "Résultat secondaire")
        self.assertEqual(variables["lmstudio_result_2"], "Résultat secondaire")
        self.assertEqual(variables["prompt_3_name"], "Synthèse finale")
        self.assertEqual(variables["prompt_3_content"], "Prompt 3")

    def test_unresolved_variables_are_reported(self):
        missing = find_unresolved_variables("A {{result_1}} B {{unknown}} C {{unknown}}", {"result_1": "ok"})

        self.assertEqual(missing, ["unknown"])

    def test_secondary_sections_add_result_1_when_prompt_omits_it(self):
        message = append_missing_secondary_sections(
            "Analyse complémentaire.",
            "Analyse complémentaire.",
            {
                "transcription": "Transcription source",
                "weda_context": "Contexte patient",
                "result_1": "Observation produite",
                "current_date": "30/06/2026",
                "patient_identity": "",
            },
        )

        self.assertIn("SOURCES POUR ANALYSE SECONDAIRE", message)
        self.assertIn("RÉSULTAT 1", message)
        self.assertIn("Observation produite", message)

    def test_tertiary_sections_add_result_2_when_prompt_omits_it(self):
        message = append_missing_tertiary_sections(
            "Analyse finale.",
            "Analyse finale.",
            {
                "transcription": "Transcription source",
                "weda_context": "Contexte patient",
                "result_1": "Observation produite",
                "result_2": "Analyse secondaire produite",
                "current_date": "30/06/2026",
                "patient_identity": "",
            },
        )

        self.assertIn("SOURCES POUR ANALYSE TERTIAIRE", message)
        self.assertIn("RÉSULTAT 2", message)
        self.assertIn("Analyse secondaire produite", message)

    def test_secondary_config_defaults_to_disabled_auto_run(self):
        config = normalize_secondary_analysis_config({"enabled": True, "default_prompt_id": ""})

        self.assertTrue(config["enabled"])
        self.assertTrue(config["auto_run_after_primary"])
        self.assertEqual(config["default_prompt_id"], "secondary_analysis_default")

    def test_tertiary_config_defaults_to_disabled_auto_run_after_secondary(self):
        config = normalize_tertiary_analysis_config({"enabled": True, "default_prompt_id": ""})

        self.assertTrue(config["enabled"])
        self.assertTrue(config["auto_run_after_secondary"])
        self.assertTrue(config["include_result_2"])
        self.assertEqual(config["default_prompt_id"], "tertiary_analysis_default")


if __name__ == "__main__":
    unittest.main()
