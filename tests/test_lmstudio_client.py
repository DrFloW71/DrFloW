import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lmstudio_client import (
    LmStudioCancelled,
    LmStudioClient,
    extract_lmstudio_model_context,
    lmstudio_native_models_url,
)


class LmStudioClientModelContextTests(unittest.TestCase):
    def test_native_models_url_from_openai_chat_url(self):
        self.assertEqual(
            lmstudio_native_models_url("http://localhost:1234/v1/chat/completions"),
            "http://localhost:1234/api/v1/models",
        )

    def test_extract_loaded_context_length(self):
        context = extract_lmstudio_model_context(
            {
                "models": [
                    {
                        "key": "google/gemma",
                        "loaded_instances": [
                            {
                                "config": {
                                    "context_length": 32768,
                                },
                            }
                        ],
                        "max_context_length": 131072,
                    }
                ]
            },
            preferred_model="local-model",
        )

        self.assertIsNotNone(context)
        self.assertEqual(context.context_length, 32768)
        self.assertEqual(context.max_context_length, 131072)
        self.assertEqual(context.source, "loaded_instance.config.context_length")

    def test_streaming_chat_reports_progress(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeStreamingLmStudioHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            progress = []
            client = LmStudioClient(f"http://127.0.0.1:{server.server_port}/v1/chat/completions")
            response = client.chat("bonjour", stop_event=threading.Event(), on_progress=lambda elapsed, chars: progress.append(chars))
            self.assertEqual(response.text, "Bonjour docteur")
            self.assertTrue(progress)
            self.assertEqual(progress[-1], len("Bonjour docteur"))
        finally:
            server.shutdown()
            server.server_close()

    def test_streaming_chat_can_be_cancelled_after_first_chunk(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeStreamingLmStudioHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            stop_event = threading.Event()
            client = LmStudioClient(f"http://127.0.0.1:{server.server_port}/v1/chat/completions")
            with self.assertRaises(LmStudioCancelled):
                client.chat(
                    "bonjour",
                    stop_event=stop_event,
                    on_progress=lambda _elapsed, _chars: stop_event.set(),
                )
        finally:
            server.shutdown()
            server.server_close()


class FakeStreamingLmStudioHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not payload.get("stream"):
            self.send_response(400)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for content in ("Bonjour ", "docteur"):
            event = {"choices": [{"delta": {"content": content}}]}
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, _format, *_args):
        return


if __name__ == "__main__":
    unittest.main()
