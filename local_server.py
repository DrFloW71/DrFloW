from __future__ import annotations

import json
import threading
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


def _json_default(value):
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"Type non sérialisable: {type(value)!r}")


def _as_json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")


class LocalServer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        context_manager,
        import_manager,
        debug_logger=None,
        settings_provider=None,
        connector_start_handler=None,
        connector_stop_handler=None,
        connector_status_provider=None,
        connector_document_now_handler=None,
        connector_document_now_status_provider=None,
        context_refresh_provider=None,
        context_refresh_claim_handler=None,
        context_refresh_ack_handler=None,
        fly_dictation_start_handler=None,
        fly_dictation_stop_handler=None,
        fly_dictation_status_provider=None,
        on_context=None,
        on_import_status=None,
        on_debug_log=None,
    ):
        self.host = host
        self.port = port
        self.context_manager = context_manager
        self.import_manager = import_manager
        self.debug_logger = debug_logger
        self.settings_provider = settings_provider
        self.connector_start_handler = connector_start_handler
        self.connector_stop_handler = connector_stop_handler
        self.connector_status_provider = connector_status_provider
        self.connector_document_now_handler = connector_document_now_handler
        self.connector_document_now_status_provider = connector_document_now_status_provider
        self.context_refresh_provider = context_refresh_provider
        self.context_refresh_claim_handler = context_refresh_claim_handler
        self.context_refresh_ack_handler = context_refresh_ack_handler
        self.fly_dictation_start_handler = fly_dictation_start_handler
        self.fly_dictation_stop_handler = fly_dictation_stop_handler
        self.fly_dictation_status_provider = fly_dictation_status_provider
        self.on_context = on_context
        self.on_import_status = on_import_status
        self.on_debug_log = on_debug_log
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return
        handler = self._make_handler()
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="weda-local-server", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None

    def _make_handler(self):
        state = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def do_OPTIONS(self):
                self._send_json({"ok": True})

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/health":
                    state._log("info", "server", "health", "Healthcheck reçu.")
                    self._send_json({"ok": True, "service": "drflow"})
                    return

                if parsed.path == "/weda/context":
                    context = state.context_manager.get_latest()
                    state._log(
                        "info",
                        "server",
                        "get_weda_context",
                        "Contexte WEDA demandé.",
                        {"has_context": context is not None},
                    )
                    self._send_json({"ok": True, "context": context})
                    return

                if parsed.path == "/weda/context-refresh-request":
                    request = state.context_refresh_provider() if state.context_refresh_provider else None
                    self._send_json({"ok": True, "request": request})
                    return

                if parsed.path == "/settings":
                    settings = state.settings_provider() if state.settings_provider else {}
                    state._log(
                        "info",
                        "server",
                        "get_settings",
                        "Réglages demandés par le pont WEDA.",
                        settings,
                    )
                    self._send_json({"ok": True, "settings": settings})
                    return

                if parsed.path == "/weda/latest-result":
                    request = state.import_manager.get_latest()
                    query = parse_qs(parsed.query)
                    current_patient_id = (query.get("patient_id") or [""])[0]
                    patient_matches = True
                    if request and request.patient_id and current_patient_id:
                        patient_matches = _same_patient_id(request.patient_id, current_patient_id)
                    state._log(
                        "info",
                        "server",
                        "get_latest_result",
                        "Dernier résultat demandé par WEDA.",
                        {
                            "has_request": request is not None,
                            "request_id": request.id if request else "",
                            "request_status": request.status if request else "",
                            "current_patient_id": current_patient_id,
                            "patient_matches": patient_matches,
                        },
                    )
                    self._send_json(
                        {
                            "ok": True,
                            "request": request,
                            "patient_matches": patient_matches,
                        }
                    )
                    return

                if parsed.path == "/debug/logs":
                    query = parse_qs(parsed.query)
                    limit = int((query.get("limit") or ["200"])[0] or 200)
                    entries = state.debug_logger.recent(limit) if state.debug_logger else []
                    text = state.debug_logger.format_recent_text(limit) if state.debug_logger else ""
                    self._send_json({"ok": True, "entries": entries, "text": text})
                    return

                if parsed.path == "/connector/status":
                    query = parse_qs(parsed.query)
                    job_id = (query.get("job_id") or query.get("jobId") or [""])[0]
                    job = state.connector_status_provider(job_id) if state.connector_status_provider else None
                    self._send_json({"ok": True, "job": job})
                    return

                if parsed.path == "/connector/document-now/status":
                    query = parse_qs(parsed.query)
                    job_id = (query.get("job_id") or query.get("jobId") or [""])[0]
                    job = (
                        state.connector_document_now_status_provider(job_id)
                        if state.connector_document_now_status_provider
                        else None
                    )
                    self._send_json({"ok": True, "job": job})
                    return

                if parsed.path == "/fly-dictation/status":
                    fly = state.fly_dictation_status_provider() if state.fly_dictation_status_provider else None
                    self._send_json({"ok": True, "fly_dictation": fly})
                    return

                self._send_json({"ok": False, "error": "Route inconnue"}, status=404)

            def do_POST(self):
                parsed = urlparse(self.path)
                payload = self._read_json()

                if parsed.path == "/weda/context":
                    context = state.context_manager.update_context(payload)
                    state._log(
                        "info",
                        "weda",
                        "context_received",
                        "Contexte patient WEDA reçu.",
                        {
                            "patient_id": context.patient_id,
                            "patient_identity": context.patient_identity,
                            "page_title": context.page_title,
                            "visible_text_length": len(context.visible_text or ""),
                        },
                    )
                    if state.on_context:
                        state.on_context(context)
                    self._send_json({"ok": True, "context": context})
                    return

                if parsed.path == "/weda/context-refresh-claim":
                    result = (
                        state.context_refresh_claim_handler(payload)
                        if state.context_refresh_claim_handler
                        else {"claimed": False, "reason": "handler_unavailable"}
                    )
                    self._send_json({"ok": True, **result})
                    return

                if parsed.path == "/weda/context-refresh-ack":
                    result = (
                        state.context_refresh_ack_handler(payload)
                        if state.context_refresh_ack_handler
                        else {"accepted": False, "reason": "handler_unavailable"}
                    )
                    self._send_json({"ok": True, **result})
                    return

                if parsed.path == "/weda/import-request":
                    request = state.import_manager.prepare_result(
                        str(payload.get("result_text") or payload.get("resultText") or ""),
                        result_html=str(payload.get("result_html") or payload.get("resultHtml") or ""),
                        patient_id=str(payload.get("patient_id") or payload.get("patientId") or ""),
                        patient_identity=str(payload.get("patient_identity") or payload.get("patientIdentity") or ""),
                        destination=str(payload.get("destination") or "active_field"),
                    )
                    state._log(
                        "info",
                        "app",
                        "import_request_prepared_http",
                        "Résultat préparé via HTTP.",
                        {
                            "request_id": request.id,
                            "patient_id": request.patient_id,
                            "patient_identity": request.patient_identity,
                            "destination": request.destination,
                            "result_length": len(request.result_text or ""),
                            "result_html_length": len(request.result_html or ""),
                        },
                    )
                    self._send_json({"ok": True, "request": request})
                    return

                if parsed.path == "/weda/import-status":
                    request = state.import_manager.update_status(payload)
                    state._log(
                        "info",
                        "weda",
                        "import_status",
                        "Statut d’import WEDA reçu.",
                        {
                            "request_id": payload.get("request_id") or payload.get("requestId") or "",
                            "status": payload.get("status") or "",
                            "current_patient_id": payload.get("current_patient_id") or "",
                            "target": payload.get("target") or {},
                            "error": payload.get("error") or "",
                        },
                    )
                    if state.on_import_status:
                        state.on_import_status(request, payload)
                    self._send_json({"ok": True, "request": request})
                    return

                if parsed.path == "/debug/log":
                    entry = state._log(
                        str(payload.get("level") or "info"),
                        str(payload.get("source") or "tampermonkey"),
                        str(payload.get("event") or "event"),
                        str(payload.get("message") or ""),
                        dict(payload.get("details") or {}),
                    )
                    if state.on_debug_log:
                        state.on_debug_log(entry)
                    self._send_json({"ok": True, "entry": entry})
                    return

                if parsed.path == "/connector/start":
                    job = state.connector_start_handler(payload) if state.connector_start_handler else None
                    state._log(
                        "info",
                        "connector",
                        "connector_start_http",
                        "Déclenchement connecteur reçu.",
                        {"job_id": job.get("id", "") if isinstance(job, dict) else ""},
                    )
                    self._send_json({"ok": True, "job": job})
                    return

                if parsed.path == "/connector/stop":
                    job = state.connector_stop_handler(payload) if state.connector_stop_handler else None
                    state._log(
                        "info",
                        "connector",
                        "connector_stop_http",
                        "Arrêt connecteur reçu.",
                        {"job_id": job.get("id", "") if isinstance(job, dict) else ""},
                    )
                    self._send_json({"ok": True, "job": job})
                    return

                if parsed.path == "/connector/document-now":
                    job = (
                        state.connector_document_now_handler(payload)
                        if state.connector_document_now_handler
                        else None
                    )
                    state._log(
                        "info",
                        "connector",
                        "connector_document_now_http",
                        "Déclenchement Document maintenant reçu.",
                        {"job_id": job.get("id", "") if isinstance(job, dict) else ""},
                    )
                    self._send_json({"ok": True, "job": job})
                    return

                if parsed.path == "/fly-dictation/start":
                    fly = state.fly_dictation_start_handler(payload) if state.fly_dictation_start_handler else None
                    state._log(
                        "info",
                        "app",
                        "fly_dictation_start_http",
                        "Démarrage dictée à la volée reçu via HTTP.",
                        {"status": fly.get("status", "") if isinstance(fly, dict) else ""},
                    )
                    self._send_json({"ok": True, "fly_dictation": fly})
                    return

                if parsed.path == "/fly-dictation/stop":
                    fly = state.fly_dictation_stop_handler(payload) if state.fly_dictation_stop_handler else None
                    state._log(
                        "info",
                        "app",
                        "fly_dictation_stop_http",
                        "Arrêt dictée à la volée reçu via HTTP.",
                        {"status": fly.get("status", "") if isinstance(fly, dict) else ""},
                    )
                    self._send_json({"ok": True, "fly_dictation": fly})
                    return

                if parsed.path == "/debug/logs/clear":
                    if state.debug_logger:
                        state.debug_logger.clear()
                    state._log("info", "app", "logs_cleared", "Logs effacés.")
                    if state.on_debug_log:
                        state.on_debug_log(None)
                    self._send_json({"ok": True})
                    return

                self._send_json({"ok": False, "error": "Route inconnue"}, status=404)

            def log_message(self, _format, *_args):
                return

            def _read_json(self) -> dict:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0:
                    return {}
                raw = self.rfile.read(length)
                try:
                    return json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    return {}

            def _send_json(self, payload: dict, *, status: int = 200):
                body = _as_json_bytes(payload)
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.end_headers()
                self.wfile.write(body)

        return Handler

    def _log(
        self,
        level: str,
        source: str,
        event: str,
        message: str = "",
        details: dict | None = None,
    ):
        if not self.debug_logger:
            return None
        try:
            return self.debug_logger.append(level, source, event, message, details or {})
        except Exception:
            return None


def _normalize_patient_id(value: str) -> str:
    text = str(value or "").strip()
    return text.split("|", 1)[0].strip()


def _same_patient_id(expected: str, actual: str) -> bool:
    left = _normalize_patient_id(expected)
    right = _normalize_patient_id(actual)
    return bool(left and right and left == right)
