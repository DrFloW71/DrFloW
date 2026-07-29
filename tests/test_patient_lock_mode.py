from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import AssistantApp
from patient_safety import PATIENT_SAFETY_OK, PATIENT_SAFETY_UNLOCKED


class ContextManagerStub:
    def __init__(self, context=None):
        self.context = context

    def get_latest(self):
        return self.context


class PatientLockModeTests(unittest.TestCase):
    def build_app(self, *, locked: bool, context=None):
        app = AssistantApp.__new__(AssistantApp)
        app.patient_lock_enabled = locked
        app.context_manager = ContextManagerStub(context)
        app.context_text = object()
        app.get_text = lambda _widget: "Contexte WEDA de test"
        return app

    def test_local_mode_is_unlocked_without_context(self):
        app = self.build_app(locked=False)
        state = app.current_patient_safety_state()
        self.assertEqual(state.level, PATIENT_SAFETY_UNLOCKED)
        self.assertTrue(state.allows_generation)

    def test_unlocked_mode_ignores_visible_weda_context(self):
        app = self.build_app(locked=False, context=SimpleNamespace(patient_id="123"))
        self.assertEqual(app.get_active_weda_context_text(), "")

    def test_unlocked_result_has_no_patient_binding(self):
        context = SimpleNamespace(
            patient_id="123|Patient test",
            patient_identity="Patient test",
            received_at="2026-07-28T08:00:00Z",
        )
        app = self.build_app(locked=False, context=context)
        binding = app.capture_current_patient_binding()
        self.assertEqual(binding["patient_id"], "")
        self.assertEqual(binding["patient_identity"], "")

    def test_connector_mode_uses_context_and_binds_patient(self):
        context = SimpleNamespace(
            patient_id="123|Patient test",
            patient_identity="Patient test",
            patient_name="",
            received_at="2026-07-28T08:00:00Z",
        )
        app = self.build_app(locked=True, context=context)
        self.assertEqual(app.current_patient_safety_state().level, PATIENT_SAFETY_OK)
        self.assertEqual(app.get_active_weda_context_text(), "Contexte WEDA de test")
        self.assertEqual(app.capture_current_patient_binding()["patient_id"], "123")

    def test_recording_buttons_select_the_expected_lock_mode(self):
        for source, expected_lock in (("classic", False), ("connector", True)):
            with self.subTest(source=source), patch("app.SegmentedDictationSession") as session_class:
                session = Mock()
                session_class.return_value = session
                app = SimpleNamespace(
                    session=None,
                    dictation_run_id=0,
                    set_patient_lock_mode=Mock(),
                    transcriber=object(),
                    get_stt_settings=Mock(return_value={}),
                    root=SimpleNamespace(after=Mock()),
                    transcription_status_var=Mock(),
                    on_segment_started=Mock(),
                    on_transcription_result=Mock(),
                    on_session_error=Mock(),
                    set_dictation_buttons_running=Mock(),
                    set_recording_indicator=Mock(),
                    micro_status_var=Mock(),
                    log_debug=Mock(),
                )

                AssistantApp.start_dictation(
                    app,
                    reset_session=True,
                    recording_source=source,
                )

                app.set_patient_lock_mode.assert_called_once_with(
                    expected_lock,
                    source="connector_weda" if expected_lock else "local_recording",
                )
                session.start.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
