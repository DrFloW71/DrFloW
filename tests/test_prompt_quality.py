from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from prompt_manager import PromptManager
from prompt_quality import PromptVersionStore, QualityMetricsStore, unified_text_diff


class PromptQualityTests(unittest.TestCase):
    def test_versions_are_deduplicated_but_changed_content_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PromptVersionStore(Path(tmp) / "versions.jsonl")
            prompt = SimpleNamespace(id="p1", name="Test", prompt_type="generic", content="Version A")
            first = store.record(prompt)
            duplicate = store.record(prompt)
            prompt.content = "Version B"
            second = store.record(prompt)
            self.assertEqual(first.version_id, duplicate.version_id)
            self.assertNotEqual(first.version_id, second.version_id)
            self.assertEqual(len(store.list_versions("p1")), 2)

    def test_prompt_manager_change_callback_records_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            prompt_path = base / "prompts.json"
            prompt_path.write_text(
                '[{"id":"p1","name":"Test","content":"A","is_default":true,"prompt_type":"generic"}]',
                encoding="utf-8",
            )
            store = PromptVersionStore(base / "versions.jsonl")
            manager = PromptManager(prompt_path, on_change=lambda action, prompt: store.record(prompt, source=action))
            manager.update("p1", content="B")
            versions = store.list_versions("p1")
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0].content, "B")
            self.assertEqual(versions[0].source, "update")

    def test_metrics_store_only_numeric_metadata_and_summarizes_corrections(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrics.jsonl"
            store = QualityMetricsStore(path)
            generation = store.record_generation(
                workflow="document_1",
                source="result_1",
                prompt_id="p1",
                prompt_name="Consultation",
                prompt_version="abc",
                status="success",
                elapsed_seconds=2.5,
                input_chars=100,
                result_chars=30,
            )
            store.record_correction(
                workflow="document_1",
                source="result_1",
                generation_id=generation["generation_id"],
                prompt_id="p1",
                prompt_name="Consultation",
                generated_text="Le patient va bien",
                final_text="Le patient va très bien",
            )
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("Le patient", raw)
            summary = store.summary()[0]
            self.assertEqual(summary["successes"], 1)
            self.assertEqual(summary["average_latency"], 2.5)
            self.assertGreater(summary["average_correction_percent"], 0)

    def test_unified_diff_marks_additions_and_removals(self):
        diff = unified_text_diff("A\nB", "A\nC")
        self.assertIn("-B", diff)
        self.assertIn("+C", diff)


if __name__ == "__main__":
    unittest.main()
