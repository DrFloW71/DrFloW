from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from stt_backends.base import format_text_with_speaker_mapping, normalize_stt_result
from stt_engine_manager import STTEngineManager, backend_config_for
from whisper_model_manager import WhisperModelManager


class STTNormalizationTests(unittest.TestCase):
    def test_normalized_result_can_render_speaker_mapping(self):
        result = normalize_stt_result(
            {
                "engine": "voxtral",
                "segments": [
                    {"start": 0, "end": 1.2, "speaker": "SPEAKER_00", "text": "Bonjour"},
                    {"start": 1.3, "end": 2.0, "speaker": "SPEAKER_01", "text": "Je tousse"},
                ],
            }
        )

        rendered = format_text_with_speaker_mapping(result, {"SPEAKER_00": "Médecin", "SPEAKER_01": "Patient"})

        self.assertEqual(result["speakers"], ["SPEAKER_00", "SPEAKER_01"])
        self.assertEqual(rendered, "Médecin : Bonjour\nPatient : Je tousse")


class STTEngineManagerTests(unittest.TestCase):
    def test_top_level_fly_overrides_win_over_main_faster_whisper_context(self):
        config = {
            "engine": "faster-whisper",
            "faster_whisper": {
                "model": "large-v3",
                "initial_prompt": "Prompt principal WEDA très long",
                "hotwords": "Eliquis, metformine",
                "beam_size": 5,
            },
            "model": "large-v3-turbo",
            "initial_prompt": "Dictée courte",
            "hotwords": "",
            "hotwords_count": 0,
            "beam_size": 1,
            "max_new_tokens": 128,
        }

        result = backend_config_for(config, "faster-whisper")

        self.assertEqual(result["model"], "large-v3-turbo")
        self.assertEqual(result["initial_prompt"], "Dictée courte")
        self.assertEqual(result["hotwords"], "")
        self.assertEqual(result["hotwords_count"], 0)
        self.assertEqual(result["beam_size"], 1)
        self.assertEqual(result["max_new_tokens"], 128)

    def test_external_cli_backend_reads_output_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audio_path = tmp_path / "audio.wav"
            script_path = tmp_path / "fake_stt.py"
            write_silent_wav(audio_path)
            script_path.write_text(
                "import json, sys\n"
                "payload = {'text': 'bonjour docteur', 'segments': [{'start': 0, 'end': 1, 'text': 'bonjour docteur'}]}\n"
                "open(sys.argv[2], 'w', encoding='utf-8').write(json.dumps(payload, ensure_ascii=False))\n",
                encoding="utf-8",
            )
            manager = STTEngineManager(WhisperModelManager())
            config = {
                "engine": "qwen3_asr",
                "allow_experimental_engines": True,
                "auto_fallback_to_faster_whisper": False,
                "qwen3_asr": {
                    "enabled": True,
                    "model": "Qwen3-ASR-0.6B",
                    "runtime": "external_cli",
                    "device": "cpu",
                    "language": "fr",
                    "mode": "batch",
                    "external_cli_command": f'"{sys.executable}" "{script_path}" "{{audio_path}}" "{{output_json}}"',
                },
            }

            result = manager.transcribe_file(audio_path, config)

            self.assertEqual(result["engine"], "qwen3_asr")
            self.assertEqual(result["text"], "bonjour docteur")
            self.assertEqual(len(result["segments"]), 1)

    def test_compare_reports_unconfigured_experimental_engine_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "audio.wav"
            write_silent_wav(audio_path)
            manager = STTEngineManager(WhisperModelManager())
            config = {
                "allow_experimental_engines": True,
                "qwen3_asr": {
                    "enabled": False,
                    "model": "Qwen3-ASR-0.6B",
                    "runtime": "auto",
                    "device": "cuda",
                },
            }

            results = manager.compare_file(audio_path, ["qwen3_asr"], config)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["engine"], "qwen3_asr")
            self.assertTrue(results[0]["errors"])

    def test_voxtral_can_use_local_openai_audio_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "audio.wav"
            write_silent_wav(audio_path)
            server = HTTPServer(("127.0.0.1", 0), FakeVoxtralHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                manager = STTEngineManager(WhisperModelManager())
                config = {
                    "engine": "voxtral",
                    "allow_experimental_engines": True,
                    "auto_fallback_to_faster_whisper": False,
                    "voxtral": {
                        "enabled": True,
                        "model": "Voxtral-Mini-3B",
                        "runtime": "auto",
                        "device": "cpu",
                        "language": "fr",
                        "server_url": f"http://127.0.0.1:{server.server_port}",
                    },
                }

                result = manager.transcribe_file(audio_path, config)

                self.assertEqual(result["engine"], "voxtral")
                self.assertEqual(result["runtime"], "vllm")
                self.assertEqual(result["text"], "bonjour via voxtral")
                self.assertEqual(getattr(server, "received_path", ""), "/v1/audio/transcriptions")
            finally:
                server.shutdown()
                server.server_close()


def write_silent_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)


class FakeVoxtralHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.server.received_path = self.path
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        payload = {
            "text": "bonjour via voxtral",
            "segments": [{"start": 0, "end": 1, "text": "bonjour via voxtral"}],
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


if __name__ == "__main__":
    unittest.main()
