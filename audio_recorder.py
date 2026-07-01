from __future__ import annotations

import threading
import time
import wave
from pathlib import Path


class AudioRecorder:
    def __init__(self, *, sample_rate: int = 16000, channels: int = 1, device=None):
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = normalize_input_device(device)

    def record_array(self, seconds: float):
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("sounddevice n’est pas installé. Lance `pip install -r requirements.txt`.") from exc

        frames = max(1, int(float(seconds) * self.sample_rate))
        recording = sd.rec(
            frames,
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            device=self.device,
        )
        sd.wait()
        return recording

    def stop(self) -> None:
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass

    def write_wav(self, path: str | Path, audio) -> Path:
        try:
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("numpy n’est pas installé. Lance `pip install -r requirements.txt`.") from exc

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        clipped = np.clip(audio, -1.0, 1.0)
        pcm16 = (clipped * 32767).astype(np.int16)
        with wave.open(str(destination), "wb") as wav:
            wav.setnchannels(self.channels)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(pcm16.tobytes())
        return destination

    def tail(self, audio, seconds: float):
        try:
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("numpy n’est pas installé. Lance `pip install -r requirements.txt`.") from exc

        frames = max(0, int(float(seconds) * self.sample_rate))
        if frames <= 0 or audio is None or len(audio) == 0:
            return np.empty((0, self.channels), dtype="float32")
        return audio[-frames:].copy()

    def concat(self, left, right):
        try:
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("numpy n’est pas installé. Lance `pip install -r requirements.txt`.") from exc

        if left is None or len(left) == 0:
            return right
        if right is None or len(right) == 0:
            return left
        return np.concatenate([left, right], axis=0)


class PushToTalkRecorder:
    def __init__(self, *, sample_rate: int = 16000, channels: int = 1, device=None):
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = normalize_input_device(device)
        self._lock = threading.Lock()
        self._frames = []
        self._stream = None
        self._started_at = 0.0

    def start(self) -> None:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("sounddevice n’est pas installé. Lance `pip install -r requirements.txt`.") from exc

        if self._stream is not None:
            return

        with self._lock:
            self._frames = []

        def on_audio(indata, _frames, _time_info, _status):
            if indata is None or len(indata) == 0:
                return
            with self._lock:
                self._frames.append(indata.copy())

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            device=self.device,
            callback=on_audio,
        )
        self._started_at = time.perf_counter()
        self._stream.start()

    def stop(self):
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()

        try:
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("numpy n’est pas installé. Lance `pip install -r requirements.txt`.") from exc

        with self._lock:
            frames = list(self._frames)
            self._frames = []

        if not frames:
            return np.empty((0, self.channels), dtype="float32")
        return np.concatenate(frames, axis=0)

    def duration_seconds(self) -> float:
        if not self._started_at:
            return 0.0
        return max(0.0, time.perf_counter() - self._started_at)


def normalize_input_device(device):
    if device in (None, "", "default"):
        return None
    try:
        return int(device)
    except (TypeError, ValueError):
        return device


def list_input_devices() -> list[tuple[str, str]]:
    try:
        import sounddevice as sd
    except Exception:
        return [("Micro par défaut", "")]

    options: list[tuple[str, str]] = [("Micro par défaut", "")]
    try:
        default_input = sd.default.device[0] if sd.default.device else None
    except Exception:
        default_input = None

    try:
        devices = sd.query_devices()
    except Exception:
        return options

    for index, device in enumerate(devices):
        try:
            input_channels = int(device.get("max_input_channels") or 0)
        except Exception:
            input_channels = 0
        if input_channels <= 0:
            continue

        name = str(device.get("name") or f"Micro {index}")
        default_suffix = " (défaut)" if index == default_input else ""
        label = f"{index} - {name}{default_suffix}"
        options.append((label, str(index)))

    return options
