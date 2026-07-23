from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from transcription_corrections import CorrectionStore, propose_corrections


class CorrectionStoreTests(unittest.TestCase):
    def test_validation_is_persistent_and_increments_identical_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corrections.json"
            store = CorrectionStore(path)
            store.validate(
                "élicouisse", "Eliquis", category="medicament", context_before="prend", context_after="matin"
            )
            store.validate(
                "élicouisse", "Eliquis", category="medicament", context_before="traitement par", context_after="soir"
            )
            reloaded = CorrectionStore(path)
            self.assertEqual(len(reloaded.list_entries()), 1)
            self.assertEqual(reloaded.list_entries()[0].validation_count, 2)
            self.assertEqual(reloaded.hotwords(), ["Eliquis"])

    def test_rejection_and_deactivation_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corrections.json"
            store = CorrectionStore(path)
            store.validate("élicouisse", "Eliquis", category="medicament")
            store.reject("élicouisse", "Eliquis")
            self.assertTrue(store.set_active("élicouisse", "Eliquis", False))
            entry = CorrectionStore(path).list_entries()[0]
            self.assertEqual(entry.rejection_count, 1)
            self.assertFalse(entry.active)

    def test_ambiguous_source_is_never_applied_automatically(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CorrectionStore(Path(tmp) / "corrections.json")
            for _ in range(3):
                store.validate("tensionne", "tension", category="pathologie")
                store.validate("tensionne", "attention", category="pathologie")
            corrected, count = store.apply_conservative("La tensionne est normale")
            self.assertEqual(corrected, "La tensionne est normale")
            self.assertEqual(count, 0)

    def test_numbers_and_negations_are_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CorrectionStore(Path(tmp) / "corrections.json")
            for _ in range(3):
                store.validate("pas de", "présence de", category="pathologie")
                store.validate("500", "1000", category="medicament")
            corrected, count = store.apply_conservative("pas de fièvre, metformine 500 mg")
            self.assertEqual(corrected, "pas de fièvre, metformine 500 mg")
            self.assertEqual(count, 0)

    def test_missing_and_corrupt_files_are_handled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corrections.json"
            self.assertEqual(CorrectionStore(path).list_entries(), [])
            path.write_text("{invalid", encoding="utf-8")
            store = CorrectionStore(path)
            self.assertEqual(store.list_entries(), [])
            self.assertTrue(store.load_error)
            self.assertTrue(list(Path(tmp).glob("*.corrupt.*.bak")))

    def test_legacy_list_is_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corrections.json"
            path.write_text(json.dumps([{"source": "élicouisse", "correction": "Eliquis"}]), encoding="utf-8")
            store = CorrectionStore(path)
            self.assertEqual(len(store.list_entries()), 1)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)

    def test_manual_diff_proposals_do_not_learn_automatically(self):
        proposals = propose_corrections("Le patient prend élicouisse cinq milligrammes", "Le patient prend Eliquis cinq milligrammes")
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].source, "élicouisse")
        self.assertEqual(proposals[0].correction, "Eliquis")


if __name__ == "__main__":
    unittest.main()
