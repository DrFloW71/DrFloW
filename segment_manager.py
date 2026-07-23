from __future__ import annotations

import queue
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from audio_recorder import AudioRecorder, StreamingAudioRecorder
from medical_transcription import TRANSCRIPTION_OVERLAP_SECONDS, TRANSCRIPTION_WINDOW_SECONDS
from progressive_transcription import ProgressiveAudioWindowBuffer


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
        self._recorder: StreamingAudioRecorder | None = None
        self._finished_event = threading.Event()
        self._finished_event.set()
        self._checkpoint_lock = threading.Lock()
        self._pending_checkpoint_ids: list[str] = []
        self._checkpoint_event = threading.Event()
        self._temp_dir = Path(tempfile.mkdtemp(prefix="gemma_weda_audio_"))

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._finished_event.clear()
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

    def is_finished(self) -> bool:
        return self._finished_event.is_set()

    def wait_until_finished(self, timeout: float | None = None) -> bool:
        return self._finished_event.wait(timeout)

    def request_checkpoint(self, checkpoint_id: str) -> bool:
        if not self.is_running():
            return False
        with self._checkpoint_lock:
            self._pending_checkpoint_ids.append(str(checkpoint_id))
        self._checkpoint_event.set()
        return True

    def _pop_pending_checkpoint_ids(self) -> list[str]:
        with self._checkpoint_lock:
            checkpoint_ids = list(self._pending_checkpoint_ids)
            self._pending_checkpoint_ids.clear()
        return checkpoint_ids

    def _has_pending_checkpoint_ids(self) -> bool:
        with self._checkpoint_lock:
            return bool(self._pending_checkpoint_ids)

    def _record_loop(self) -> None:
        try:
            settings = self.settings_provider()
            segment_seconds = float(settings.get("segment_seconds") or TRANSCRIPTION_WINDOW_SECONDS)
            overlap_seconds = float(settings.get("overlap_seconds") or TRANSCRIPTION_OVERLAP_SECONDS)
            sample_rate = int(settings.get("sample_rate") or 16000)
            auto_delete_audio = bool(settings.get("auto_delete_audio", True))
            input_device = settings.get("input_device")
            wav_writer = AudioRecorder(sample_rate=sample_rate, channels=1, device=input_device)
            self._recorder = StreamingAudioRecorder(sample_rate=sample_rate, channels=1, device=input_device)
            window_buffer = ProgressiveAudioWindowBuffer(
                sample_rate=sample_rate,
                window_seconds=segment_seconds,
                overlap_seconds=overlap_seconds,
            )
            self._recorder.start()
            self.on_status("Écoute en cours")

            while not self._stop_event.is_set():
                audio = self._recorder.read(timeout=0.25)
                if audio is None:
                    continue
                for window in window_buffer.add(audio):
                    self._enqueue_window(window, wav_writer, auto_delete_audio, window_buffer.buffered_frames)
                if self._checkpoint_event.is_set():
                    if self._has_pending_checkpoint_ids():
                        checkpoint_window = window_buffer.flush(continue_stream=True)
                        if checkpoint_window is not None:
                            self._enqueue_window(checkpoint_window, wav_writer, auto_delete_audio, 0)
                    self._checkpoint_event.clear()

            self._recorder.stop()
            for audio in self._recorder.drain():
                for window in window_buffer.add(audio):
                    self._enqueue_window(window, wav_writer, auto_delete_audio, window_buffer.buffered_frames)
            final_window = window_buffer.flush()
            if final_window is not None:
                self._enqueue_window(final_window, wav_writer, auto_delete_audio, 0)

            self.on_status("Dictée arrêtée")
        except Exception as exc:
            self.on_error(exc)
        finally:
            if self._recorder:
                try:
                    self._recorder.stop()
                except Exception:
                    pass
            self._queue.put(None)

    def _enqueue_window(self, window, wav_writer: AudioRecorder, auto_delete_audio: bool, buffered_frames: int) -> None:
        self.on_segment_started(window.index)
        checkpoint_ids = self._pop_pending_checkpoint_ids()
        path = self._temp_dir / f"segment_{window.index:04d}.wav"
        wav_writer.write_wav(path, window.audio)
        metadata = {
            "window_start_seconds": round(window.start_seconds, 3),
            "window_end_seconds": round(window.end_seconds, 3),
            "window_duration_seconds": round(window.duration_seconds, 3),
            "overlap_seconds": round(window.overlap_seconds, 3),
            "buffered_frames_after_emit": int(buffered_frames),
            "final_window": bool(window.final),
            "queued_at": time.time(),
        }
        self._queue.put((window.index, path, auto_delete_audio, checkpoint_ids, metadata))

    def _transcribe_loop(self) -> None:
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    return

                metadata = {}
                if len(item) == 3:
                    index, path, auto_delete_audio = item
                    checkpoint_ids = []
                elif len(item) == 4:
                    index, path, auto_delete_audio, checkpoint_ids = item
                else:
                    index, path, auto_delete_audio, checkpoint_ids, metadata = item
                try:
                    self.on_status(f"Segment {index} en transcription")
                    result = self.transcriber.transcribe_file(path, segment_index=index)
                    result.checkpoint_ids = checkpoint_ids
                    result.window_metadata = metadata
                    self.on_transcription(result)
                except Exception as exc:
                    self.on_error(exc)
                finally:
                    if auto_delete_audio:
                        try:
                            Path(path).unlink(missing_ok=True)
                        except Exception:
                            pass
        finally:
            self._finished_event.set()
