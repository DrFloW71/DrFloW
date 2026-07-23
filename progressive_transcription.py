from __future__ import annotations

import re
from dataclasses import dataclass


WORD_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+(?:[-’'][0-9A-Za-zÀ-ÖØ-öø-ÿ]+)*", re.UNICODE)


@dataclass(frozen=True)
class AudioWindow:
    index: int
    audio: object
    start_seconds: float
    end_seconds: float
    overlap_seconds: float
    final: bool = False

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)


class ProgressiveAudioWindowBuffer:
    """Build ordered overlapping windows while retaining every newly received sample."""

    def __init__(self, *, sample_rate: int, window_seconds: float, overlap_seconds: float):
        if sample_rate <= 0:
            raise ValueError("sample_rate doit être positif")
        if window_seconds <= 0:
            raise ValueError("window_seconds doit être positif")
        if overlap_seconds < 0 or overlap_seconds >= window_seconds:
            raise ValueError("overlap_seconds doit être compris entre 0 et window_seconds")
        self.sample_rate = int(sample_rate)
        self.window_frames = max(1, round(float(window_seconds) * self.sample_rate))
        self.overlap_frames = max(0, round(float(overlap_seconds) * self.sample_rate))
        self.step_frames = self.window_frames - self.overlap_frames
        self._chunks: list[object] = []
        self._buffer_frames = 0
        self._next_start_frame = 0
        self._index = 0
        self._new_frames_since_emit = 0

    @property
    def buffered_frames(self) -> int:
        return self._buffer_frames

    def add(self, audio) -> list[AudioWindow]:
        import numpy as np

        chunk = np.asarray(audio, dtype="float32")
        if chunk.ndim == 1:
            chunk = chunk.reshape(-1, 1)
        if chunk.size == 0 or chunk.shape[0] == 0:
            return []
        self._chunks.append(chunk.copy())
        frames = int(chunk.shape[0])
        self._buffer_frames += frames
        self._new_frames_since_emit += frames
        windows: list[AudioWindow] = []
        while self._buffer_frames >= self.window_frames:
            data = self._materialize(self.window_frames)
            windows.append(self._make_window(data, final=False))
            self._discard(self.step_frames)
            self._next_start_frame += self.step_frames
            self._new_frames_since_emit = max(0, self._buffer_frames - self.overlap_frames)
        return windows

    def flush(self, *, continue_stream: bool = False) -> AudioWindow | None:
        if self._buffer_frames <= 0 or self._new_frames_since_emit <= 0:
            return None
        frames = self._buffer_frames
        data = self._materialize(self._buffer_frames)
        window = self._make_window(data, final=True)
        self._chunks.clear()
        self._buffer_frames = 0
        self._new_frames_since_emit = 0
        if continue_stream:
            self._next_start_frame += frames
        return window

    def _make_window(self, data, *, final: bool) -> AudioWindow:
        frames = int(data.shape[0])
        self._index += 1
        start = self._next_start_frame / self.sample_rate
        end = (self._next_start_frame + frames) / self.sample_rate
        overlap = 0.0 if self._index == 1 else min(self.overlap_frames, frames) / self.sample_rate
        return AudioWindow(self._index, data, start, end, overlap, final)

    def _materialize(self, frames: int):
        import numpy as np

        if not self._chunks:
            return np.empty((0, 1), dtype="float32")
        return np.concatenate(self._chunks, axis=0)[:frames].copy()

    def _discard(self, frames: int) -> None:
        remaining = int(frames)
        while remaining > 0 and self._chunks:
            chunk = self._chunks[0]
            length = int(chunk.shape[0])
            if length <= remaining:
                self._chunks.pop(0)
                self._buffer_frames -= length
                remaining -= length
            else:
                self._chunks[0] = chunk[remaining:].copy()
                self._buffer_frames -= remaining
                remaining = 0


@dataclass(frozen=True)
class DeduplicationResult:
    text_to_append: str
    removed_words: int = 0
    removed_characters: int = 0


def deduplicate_transcription_overlap(previous_text: str, new_text: str, *, max_words: int = 40) -> DeduplicationResult:
    previous = str(previous_text or "").strip()
    incoming = str(new_text or "").strip()
    if not previous or not incoming:
        return DeduplicationResult(incoming)

    previous_tokens = list(WORD_RE.finditer(previous))
    incoming_tokens = list(WORD_RE.finditer(incoming))
    if not previous_tokens or not incoming_tokens:
        return DeduplicationResult(incoming)

    from medical_transcription import normalize_for_match

    previous_words = [normalize_for_match(match.group(0).replace("’", "'")) for match in previous_tokens]
    incoming_words = [normalize_for_match(match.group(0).replace("’", "'")) for match in incoming_tokens]
    maximum = min(max(1, int(max_words)), len(previous_words), len(incoming_words))
    overlap_words = 0
    for size in range(maximum, 0, -1):
        if previous_words[-size:] != incoming_words[:size]:
            continue
        if size < 3:
            token = incoming_words[0]
            if size == 1 and (len(token) < 6 or token.isdigit()):
                continue
            if size == 2 and any(word.isdigit() for word in incoming_words[:2]):
                continue
        overlap_words = size
        break
    if not overlap_words:
        return DeduplicationResult(incoming)

    cut = incoming_tokens[overlap_words - 1].end()
    while cut < len(incoming) and incoming[cut] in " \t\r\n,;:.!?—–-":
        cut += 1
    appended = incoming[cut:].lstrip()
    return DeduplicationResult(appended, overlap_words, cut)
