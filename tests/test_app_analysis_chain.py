from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app import AssistantApp


class AnalysisChainTests(unittest.TestCase):
    def test_document_one_send_uses_the_chained_orchestration(self):
        app = SimpleNamespace(send_to_lmstudio=Mock())

        AssistantApp.send_document_to_lmstudio(app, 1)

        app.send_to_lmstudio.assert_called_once_with()

    def test_result_one_automatically_starts_prompt_two(self):
        result_payload = SimpleNamespace(text="Résultat 1", html="<p>Résultat 1</p>")
        app = SimpleNamespace(
            stop_lmstudio_spinner=Mock(),
            apply_abbreviations_to_lmstudio_result=Mock(return_value="Résultat 1"),
            remember_weda_result_payload=Mock(return_value=result_payload),
            record_generation_metric=Mock(),
            set_rich_result_text=Mock(),
            result_text=object(),
            select_tab_containing_widget=Mock(),
            lmstudio_status_var=Mock(),
            log_debug=Mock(),
            is_secondary_auto_run_enabled=Mock(return_value=True),
            run_secondary_analysis=Mock(),
        )
        response = SimpleNamespace(text="Résultat 1", elapsed_seconds=1.25)

        AssistantApp.on_lmstudio_response(app, response, "Message 1")

        app.run_secondary_analysis.assert_called_once_with(
            trigger="auto",
            primary_sent_message="Message 1",
            primary_result="Résultat 1",
        )

    def test_result_two_automatically_starts_prompt_three(self):
        result_payload = SimpleNamespace(text="Résultat 2", html="<p>Résultat 2</p>")
        app = SimpleNamespace(
            secondary_running=True,
            stop_lmstudio_spinner=Mock(),
            apply_abbreviations_to_lmstudio_result=Mock(return_value="Résultat 2"),
            remember_weda_result_payload=Mock(return_value=result_payload),
            record_generation_metric=Mock(),
            set_rich_result_text=Mock(),
            secondary_result_text=object(),
            select_tab_containing_widget=Mock(),
            secondary_status_var=Mock(),
            log_debug=Mock(),
            schedule_tertiary_message_refresh=Mock(),
            is_tertiary_auto_run_enabled=Mock(return_value=True),
            run_tertiary_analysis=Mock(),
        )
        response = SimpleNamespace(text="Résultat 2", elapsed_seconds=2.5)

        AssistantApp.on_secondary_lmstudio_response(
            app,
            response,
            "Message 2",
            "Message 1",
            "Résultat 1",
            "auto",
        )

        self.assertFalse(app.secondary_running)
        app.run_tertiary_analysis.assert_called_once_with(
            trigger="auto",
            sent_message_1="Message 1",
            result_1="Résultat 1",
            sent_message_2="Message 2",
            result_2="Résultat 2",
            prompt_2_status="success",
        )

    def test_connector_shortcut_result_automatically_starts_prompt_two(self):
        result_payload = SimpleNamespace(text="Résultat connecteur", html="<p>Résultat connecteur</p>")
        result_widget = object()
        context_widget = object()
        app = SimpleNamespace(
            record_generation_metric=Mock(),
            set_rich_result_text=Mock(),
            result_text=result_widget,
            lmstudio_status_var=Mock(),
            import_status_var=Mock(),
            history_manager=SimpleNamespace(append=Mock()),
            current_stt_history_payload=Mock(return_value={}),
            model_manager=SimpleNamespace(active_label=Mock(return_value="Moteur STT")),
            prompt_var=Mock(),
            get_clean_transcription_text=Mock(return_value="Transcription"),
            get_text=Mock(return_value="Contexte WEDA"),
            context_text=context_widget,
            is_secondary_auto_run_enabled=Mock(return_value=True),
            log_debug=Mock(),
            run_secondary_analysis=Mock(),
        )
        app.prompt_var.get.return_value = "Prompt 1"
        response = SimpleNamespace(elapsed_seconds=3.0)

        AssistantApp.finalize_connector_primary_result(
            app,
            response=response,
            message="Message connecteur",
            result_payload=result_payload,
            patient_id="patient-test",
            patient_identity="Patient Test",
        )

        app.set_rich_result_text.assert_called_once_with(result_widget, result_payload, source="result_1")
        app.run_secondary_analysis.assert_called_once_with(
            trigger="auto",
            primary_sent_message="Message connecteur",
            primary_result="Résultat connecteur",
        )


if __name__ == "__main__":
    unittest.main()
