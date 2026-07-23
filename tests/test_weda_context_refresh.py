from __future__ import annotations

import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.request import Request, urlopen

from app import AssistantApp
from local_server import LocalServer


class WedaContextRefreshTests(unittest.TestCase):
    def build_app(self):
        return SimpleNamespace(
            _weda_context_refresh_lock=threading.Lock(),
            weda_context_refresh_job=None,
            weda_patient_status_var=Mock(),
            root=Mock(),
            log_debug=Mock(),
        )

    def test_refresh_button_creates_a_real_pending_browser_request(self):
        app = self.build_app()

        job = AssistantApp.request_weda_context_refresh(app)

        self.assertEqual(job["status"], "pending")
        self.assertEqual(app.weda_context_refresh_job["id"], job["id"])
        app.root.after.assert_called_once()
        app.weda_patient_status_var.set.assert_called_with("Patient WEDA: actualisation demandée…")

    def test_only_one_weda_tab_can_claim_the_request(self):
        app = self.build_app()
        app.weda_context_refresh_job = {"id": "request-1", "status": "pending"}

        first = AssistantApp.claim_weda_context_refresh(
            app,
            {
                "request_id": "request-1",
                "responder_id": "visible-tab",
                "page_url": "https://secure.weda.fr/patient",
            },
        )
        second = AssistantApp.claim_weda_context_refresh(
            app,
            {
                "request_id": "request-1",
                "responder_id": "other-tab",
                "page_url": "https://secure.weda.fr/other",
            },
        )

        self.assertTrue(first["claimed"])
        self.assertFalse(second["claimed"])
        self.assertEqual(app.weda_context_refresh_job["responder_id"], "visible-tab")

    def test_success_acknowledgement_completes_the_request(self):
        app = self.build_app()
        app.weda_context_refresh_job = {
            "id": "request-2",
            "status": "collecting",
            "responder_id": "visible-tab",
        }

        result = AssistantApp.acknowledge_weda_context_refresh(
            app,
            {
                "request_id": "request-2",
                "responder_id": "visible-tab",
                "status": "success",
                "visible_text_length": 1234,
                "patient_id_present": True,
            },
        )

        self.assertTrue(result["accepted"])
        self.assertEqual(app.weda_context_refresh_job["status"], "done")
        self.assertEqual(app.weda_context_refresh_job["visible_text_length"], 1234)


class WedaContextRefreshHttpTests(unittest.TestCase):
    def test_http_request_claim_and_ack_routes(self):
        job = {"id": "refresh-http", "status": "pending"}

        def claim(payload):
            job["status"] = "collecting"
            job["responder_id"] = payload.get("responder_id")
            return {"claimed": True, "job": dict(job)}

        def acknowledge(payload):
            job["status"] = "done" if payload.get("status") == "success" else "error"
            return {"accepted": True, "job": dict(job)}

        server = LocalServer(
            host="127.0.0.1",
            port=0,
            context_manager=object(),
            import_manager=object(),
            context_refresh_provider=lambda: dict(job),
            context_refresh_claim_handler=claim,
            context_refresh_ack_handler=acknowledge,
        )
        server.start()
        try:
            port = server._server.server_address[1]
            with urlopen(
                f"http://127.0.0.1:{port}/weda/context-refresh-request",
                timeout=3,
            ) as response:
                pending = json.loads(response.read().decode("utf-8"))

            claimed = self.post_json(
                port,
                "/weda/context-refresh-claim",
                {
                    "request_id": "refresh-http",
                    "responder_id": "tab-http",
                },
            )
            acknowledged = self.post_json(
                port,
                "/weda/context-refresh-ack",
                {
                    "request_id": "refresh-http",
                    "responder_id": "tab-http",
                    "status": "success",
                },
            )
        finally:
            server.stop()

        self.assertEqual(pending["request"]["status"], "pending")
        self.assertTrue(claimed["claimed"])
        self.assertTrue(acknowledged["accepted"])
        self.assertEqual(acknowledged["job"]["status"], "done")

    @staticmethod
    def post_json(port: int, path: str, payload: dict) -> dict:
        request = Request(
            f"http://127.0.0.1:{port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
