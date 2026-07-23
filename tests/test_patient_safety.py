from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from patient_safety import (
    PATIENT_SAFETY_BLOCKED,
    PATIENT_SAFETY_OK,
    PATIENT_SAFETY_WARNING,
    evaluate_patient_context,
    patient_ids_match,
)


class PatientSafetyTests(unittest.TestCase):
    def context(self, *, patient_id="123", minutes_old=2):
        received = datetime.now(timezone.utc) - timedelta(minutes=minutes_old)
        return SimpleNamespace(
            patient_id=patient_id,
            patient_identity="Patient test",
            patient_name="",
            received_at=received.isoformat().replace("+00:00", "Z"),
        )

    def test_fresh_context_with_patient_id_is_ready(self):
        state = evaluate_patient_context(self.context())
        self.assertEqual(state.level, PATIENT_SAFETY_OK)
        self.assertTrue(state.allows_import)

    def test_old_context_remains_valid_without_expiration(self):
        state = evaluate_patient_context(self.context(minutes_old=100000))
        self.assertEqual(state.level, PATIENT_SAFETY_OK)
        self.assertTrue(state.allows_generation)
        self.assertTrue(state.allows_import)

    def test_missing_patient_id_warns_for_generation_and_blocks_import(self):
        state = evaluate_patient_context(self.context(patient_id=""), require_patient_id=False)
        self.assertEqual(state.level, PATIENT_SAFETY_WARNING)
        self.assertTrue(state.allows_generation)
        strict = evaluate_patient_context(self.context(patient_id=""), require_patient_id=True)
        self.assertEqual(strict.level, PATIENT_SAFETY_BLOCKED)

    def test_patient_id_comparison_uses_patdk_prefix(self):
        self.assertTrue(patient_ids_match("123|Nom", "123"))
        self.assertFalse(patient_ids_match("123", "456"))


if __name__ == "__main__":
    unittest.main()
