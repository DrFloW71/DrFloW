from __future__ import annotations

import os
import site
import threading
from dataclasses import dataclass


FRENCH_SAFE_WHISPER_FALLBACK_MODEL = "large-v3"
FRENCH_UNSAFE_WHISPER_MODEL_ALIASES = {
    "faster-distil-whisper-large-v3": FRENCH_SAFE_WHISPER_FALLBACK_MODEL,
    "distil-large-v2": FRENCH_SAFE_WHISPER_FALLBACK_MODEL,
    "distil-large-v3": FRENCH_SAFE_WHISPER_FALLBACK_MODEL,
    "distil-large-v3.5": FRENCH_SAFE_WHISPER_FALLBACK_MODEL,
    "distil-medium.en": "medium",
    "distil-small.en": "small",
}
_DLL_DIRECTORY_HANDLES = []
_DLL_DIRECTORIES_CONFIGURED = False


@dataclass(frozen=True)
class WhisperSettings:
    model_name: str = "medium"
    device: str = "cpu"
    compute_type: str = "int8"
    cpu_threads: int = 16

    @classmethod
    def from_mapping(cls, data: dict) -> "WhisperSettings":
        return cls(
            model_name=canonical_french_whisper_model_name(data.get("model") or data.get("default_model") or "medium"),
            device=str(data.get("device") or "cpu"),
            compute_type=str(data.get("compute_type") or "int8"),
            cpu_threads=int(data.get("cpu_threads") or 16),
        )


class WhisperModelManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._models: dict[WhisperSettings, object] = {}
        self._active_settings: WhisperSettings | None = None

    def load(self, settings: WhisperSettings):
        with self._lock:
            cached_model = self._models.get(settings)
            if cached_model is not None:
                self._active_settings = settings
                return cached_model

            if settings.device == "cuda":
                configure_nvidia_dll_directories()

            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "faster-whisper n’est pas installé. Lance `pip install -r requirements.txt`."
                ) from exc

            kwargs = {
                "device": settings.device,
                "compute_type": settings.compute_type,
            }
            if settings.device == "cpu":
                kwargs["cpu_threads"] = settings.cpu_threads

            model = WhisperModel(settings.model_name, **kwargs)
            self._models[settings] = model
            self._active_settings = settings
            return model

    def active_label(self) -> str:
        if self._active_settings is None:
            return "aucun modèle chargé"
        settings = self._active_settings
        return f"{settings.model_name} / {settings.device} / {settings.compute_type}"

    def unload_all(self) -> None:
        with self._lock:
            self._models.clear()
            self._active_settings = None


def canonical_french_whisper_model_name(value: str, default: str = "medium") -> str:
    requested = str(value or "").strip() or default
    normalized = requested.lower()
    if normalized in FRENCH_UNSAFE_WHISPER_MODEL_ALIASES:
        return FRENCH_UNSAFE_WHISPER_MODEL_ALIASES[normalized]
    if normalized.endswith(".en"):
        base = normalized[:-3]
        return base or default
    return requested


def configure_nvidia_dll_directories() -> list[str]:
    global _DLL_DIRECTORIES_CONFIGURED
    if os.name != "nt" or _DLL_DIRECTORIES_CONFIGURED:
        return []

    _DLL_DIRECTORIES_CONFIGURED = True
    configured = []
    roots = []
    for getter in (site.getsitepackages,):
        try:
            roots.extend(getter())
        except Exception:
            pass
    try:
        roots.append(site.getusersitepackages())
    except Exception:
        pass

    for root in roots:
        nvidia_root = os.path.join(str(root), "nvidia")
        if not os.path.isdir(nvidia_root):
            continue
        for package_name in os.listdir(nvidia_root):
            bin_dir = os.path.join(nvidia_root, package_name, "bin")
            if not os.path.isdir(bin_dir):
                continue
            try:
                handle = os.add_dll_directory(bin_dir)
                _DLL_DIRECTORY_HANDLES.append(handle)
            except (AttributeError, FileNotFoundError, OSError):
                pass
            configured.append(bin_dir)

    if configured:
        current_path = os.environ.get("PATH", "")
        existing = {part.casefold() for part in current_path.split(os.pathsep) if part}
        additions = [path for path in configured if path.casefold() not in existing]
        if additions:
            os.environ["PATH"] = os.pathsep.join(additions + [current_path])

    return configured


def french_whisper_model_substitution_warning(requested: str, effective: str) -> str:
    requested_text = str(requested or "").strip()
    effective_text = str(effective or "").strip()
    if not requested_text or not effective_text or requested_text == effective_text:
        return ""

    normalized = requested_text.lower()
    if normalized == "faster-distil-whisper-large-v3":
        return (
            "Le modèle 'faster-distil-whisper-large-v3' n'est pas un nom valide pour faster-whisper ; "
            f"utilisation de '{effective_text}' pour la transcription française."
        )
    if normalized in FRENCH_UNSAFE_WHISPER_MODEL_ALIASES or normalized.endswith(".en"):
        return (
            f"Le modèle '{requested_text}' est évité pour la dictée médicale française ; "
            f"utilisation de '{effective_text}' pour empêcher le basculement en anglais."
        )
    return f"Modèle Whisper normalisé de '{requested_text}' vers '{effective_text}'."
