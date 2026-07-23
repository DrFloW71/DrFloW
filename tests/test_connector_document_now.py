from __future__ import annotations

import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.request import Request, urlopen

from app import AssistantApp
from local_server import LocalServer
from rich_text_formatter import RichTextPayload


class ConnectorDocumentNowTests(unittest.TestCase):
    def test_success_is_ready_only_after_clipboard_copy(self):
        job = {"id": "job-1", "snapshot_id": "snapshot-1", "status": "generating"}
        app = SimpleNamespace(
            get_document_now_connector_job=Mock(return_value=job),
            copy_rich_result_source=Mock(return_value=True),
            set_document_now_connector_job=Mock(),
            document_now_status_var=Mock(),
            log_debug=Mock(),
        )
        payload = RichTextPayload(text="Document prêt", html="<p>Document prêt</p>")

        copied = AssistantApp.finalize_document_now_connector_result(
            app,
            "snapshot-1",
            payload,
            elapsed_seconds=1.5,
        )

        self.assertTrue(copied)
        app.copy_rich_result_source.assert_called_once_with("document_now")
        updates = app.set_document_now_connector_job.call_args.args[0]
        self.assertEqual(updates["status"], "ready")
        self.assertTrue(updates["clipboard_copied"])

    def test_clipboard_failure_is_reported_as_error(self):
        job = {"id": "job-2", "snapshot_id": "snapshot-2", "status": "generating"}
        app = SimpleNamespace(
            get_document_now_connector_job=Mock(return_value=job),
            copy_rich_result_source=Mock(return_value=False),
            set_document_now_connector_job=Mock(),
            document_now_status_var=Mock(),
            log_debug=Mock(),
        )

        copied = AssistantApp.finalize_document_now_connector_result(
            app,
            "snapshot-2",
            RichTextPayload(text="Document", html="<p>Document</p>"),
            elapsed_seconds=2.0,
        )

        self.assertFalse(copied)
        updates = app.set_document_now_connector_job.call_args.args[0]
        self.assertEqual(updates["status"], "error")
        self.assertFalse(updates["clipboard_copied"])

    def test_active_dictation_requests_a_snapshot_without_stopping(self):
        session = SimpleNamespace(
            is_running=Mock(return_value=True),
            request_checkpoint=Mock(return_value=True),
        )
        app = SimpleNamespace(
            document_now_running=False,
            document_now_pending_checkpoints={},
            context_manager=SimpleNamespace(get_latest=Mock(return_value=None)),
            session=session,
            set_document_now_connector_job=Mock(),
            document_now_status_var=Mock(),
            log_debug=Mock(),
            get_clean_transcription_text=Mock(return_value="Transcription en cours"),
            transcription_status_var=Mock(),
        )

        AssistantApp.request_connector_document_now_checkpoint(app, "job-3")

        session.request_checkpoint.assert_called_once()
        checkpoint_id = session.request_checkpoint.call_args.args[0]
        self.assertEqual(
            app.document_now_pending_checkpoints[checkpoint_id]["connector_job_id"],
            "job-3",
        )
        self.assertEqual(
            app.document_now_pending_checkpoints[checkpoint_id]["trigger"],
            "connector_weda",
        )


class ConnectorDocumentNowHttpTests(unittest.TestCase):
    def test_http_routes_start_and_report_document_now_job(self):
        jobs = {}

        def start_handler(payload):
            job = {
                "id": "http-job",
                "status": "generating",
                "patient_id": payload.get("patient_id", ""),
            }
            jobs[job["id"]] = job
            return job

        server = LocalServer(
            host="127.0.0.1",
            port=0,
            context_manager=object(),
            import_manager=object(),
            connector_document_now_handler=start_handler,
            connector_document_now_status_provider=lambda job_id: jobs.get(job_id),
        )
        server.start()
        try:
            port = server._server.server_address[1]
            request = Request(
                f"http://127.0.0.1:{port}/connector/document-now",
                data=json.dumps({"patient_id": "patient-test"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=3) as response:
                started = json.loads(response.read().decode("utf-8"))

            with urlopen(
                f"http://127.0.0.1:{port}/connector/document-now/status?job_id=http-job",
                timeout=3,
            ) as response:
                status = json.loads(response.read().decode("utf-8"))
        finally:
            server.stop()

        self.assertEqual(started["job"]["status"], "generating")
        self.assertEqual(started["job"]["patient_id"], "patient-test")
        self.assertEqual(status["job"]["id"], "http-job")


if __name__ == "__main__":
    unittest.main()
