from __future__ import annotations

import unittest

from diagnostic_manager import DiagnosticResult, sanitized_diagnostic_report


class DiagnosticManagerTests(unittest.TestCase):
    def test_sanitized_report_contains_only_supplied_technical_results(self):
        report = sanitized_diagnostic_report(
            [
                DiagnosticResult("ok", "Python", "3.13"),
                DiagnosticResult("warning", "Verrou patient", "blocked"),
            ]
        )
        self.assertIn("aucune donnée patient", report)
        self.assertIn("[OK] Python", report)
        self.assertNotIn("patient_identity", report)


if __name__ == "__main__":
    unittest.main()
