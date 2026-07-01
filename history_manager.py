from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class HistoryManager:
    def __init__(self, path: str | Path, *, enabled: bool = True):
        self.path = Path(path)
        self.enabled = enabled

    def append(self, entry: dict[str, Any]) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            **entry,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def purge(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except Exception:
            pass
