from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class TranscriptionDraft:
    text: str
    saved_at: str


class TranscriptionDraftStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def save(self, text: str) -> TranscriptionDraft | None:
        value = str(text or "").strip()
        if not value:
            self.clear()
            return None
        draft = TranscriptionDraft(
            text=value,
            saved_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary_path.write_text(json.dumps(asdict(draft), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_path.replace(self.path)
        return draft

    def load(self) -> TranscriptionDraft | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        text = str(raw.get("text") or "").strip()
        if not text:
            return None
        return TranscriptionDraft(text=text, saved_at=str(raw.get("saved_at") or ""))

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
        self.path.with_suffix(self.path.suffix + ".tmp").unlink(missing_ok=True)
