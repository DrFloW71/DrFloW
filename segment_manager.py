from __future__ import annotations

import queue
import tempfile
import threading
from pathlib import Path
from typing import Callable

from audio_recorder import AudioRecorder


class SegmentedDictationSession:
    def __init__(
        self,
        *,
        transcriber,
        settings_provider: Callable[[], dict],
        on_status: Callable[[str], None] | None = None,
        on_segment_started: Callable[[int], None] | None = None,
        on_transcription: Callable[[object], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ):
        self.transcriber = transcriber
        self.settings_provider = settings_provider
        self.on_status = on_status or (lambda _message: None)
        self.on_segment_started = on_segment_started or (lambda _index: None)
        self.on_transcription = on_transcription or (lambda _result: None)
        self.on_error = on_error or (lambda _error: None)
        self._stop_event = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        self._record_thread: threading.Thread | None = None
        self._transcribe_thread: threading.Thread | None = None
        self._recorder: AudioRecorder | None = None
        self._checkpoint_lock = threading.Lock()
        self._pending_checkpoint_ids: list[str] = []
        self._temp_dir = Path(tempfile.mkdtemp(prefix="gemma_weda_audio_"))

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._record_thread = threading.Thread(target=self._record_loop, name="weda-dictation-recorder", daemon=True)
        self._transcribe_thread = threading.Thread(
            target=self._transcribe_loop,
            name="weda-dictation-transcriber",
            daemon=True,
        )
        self._transcribe_thread.start()
        self._record_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._recorder:
            self._recorder.stop()

    def is_running(self) -> bool:
        return bool(self._record_thread and self._record_thread.is_alive())

    def request_checkpoint(self, checkpoint_id: str) -> bool:
        if not self.is_running():
            return False
        with self._checkpoint_lock:
            self._pending_checkpoint_ids.append(str(checkpoint_id))
        if self._recorder:
            self._recorder.stop()
        return True

    def _pop_pending_checkpoint_ids(self) -> list[str]:
        with self._checkpoint_lock:
            checkpoint_ids = list(self._pending_checkpoint_ids)
            self._pending_checkpoint_ids.clear()
        return checkpoint_ids

    def _record_loop(self) -> None:
        try:
            settings = self.settings_provider()
            segment_seconds = float(settings.get("segment_seconds") or 15)
            overlap_seconds = float(settings.get("overlap_seconds") or 1)
            sample_rate = int(settings.get("sample_rate") or 16000)
            auto_delete_audio = bool(settings.get("auto_delete_audio", True))
            input_device = settings.get("input_device")
            self._recorder = AudioRecorder(sample_rate=sample_rate, channels=1, device=input_device)
            previous_tail = None
            index = 0
            self.on_status("Écoute en cours")

            while not self._stop_event.is_set():
                index += 1
                self.on_segment_started(index)
                audio = self._recorder.record_array(segment_seconds)
                if self._stop_event.is_set() and audio is None:
                    break

                checkpoint_ids = self._pop_pending_checkpoint_ids()
                combined = self._recorder.concat(previous_tail, audio)
                previous_tail = self._recorder.tail(audio, overlap_seconds)
                path = self._temp_dir / f"segment_{index:04d}.wav"
                self._recorder.write_wav(path, combined)
                self._queue.put((index, path, auto_delete_audio, checkpoint_ids))

            self.on_status("Dictée arrêtée")
        except Exception as exc:
            self.on_error(exc)
        finally:
            self._queue.put(None)

    def _transcribe_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return

            if len(item) == 3:
                index, path, auto_delete_audio = item
                checkpoint_ids = []
            else:
                index, path, auto_delete_audio, checkpoint_ids = item
            try:
                self.on_status(f"Segment {index} en transcription")
                result = self.transcriber.transcribe_file(path, segment_index=index)
                result.checkpoint_ids = checkpoint_ids
                self.on_transcription(result)
            except Exception as exc:
                self.on_error(exc)
            finally:
                if auto_delete_audio:
                    try:
                        Path(path).unlink(missing_ok=True)
                    except Exception:
                        pass
