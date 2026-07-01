from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


class DebugLogger:
    def __init__(self, path: str | Path, *, max_detail_string: int = 800):
        self.path = Path(path)
        self.max_detail_string = max_detail_string
        self._lock = threading.Lock()

    def append(
        self,
        level: str,
        source: str,
        event: str,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "at": utc_now_iso(),
            "level": str(level or "info").lower(),
            "source": str(source or "app"),
            "event": str(event or ""),
            "message": str(message or ""),
            "details": self._compact(details or {}),
        }

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

        return entry

    def recent(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        limit = max(1, int(limit or 200))
        with self._lock:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()

        entries: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                entries.append(
                    {
                        "at": "",
                        "level": "warning",
                        "source": "logger",
                        "event": "unreadable_line",
                        "message": line[: self.max_detail_string],
                        "details": {},
                    }
                )
        return entries

    def format_recent_text(self, limit: int = 200) -> str:
        entries = self.recent(limit)
        if not entries:
            return "Aucun log enregistré."

        blocks = []
        for entry in entries:
            header = " | ".join(
                part
                for part in (
                    str(entry.get("at") or ""),
                    str(entry.get("level") or "").upper(),
                    str(entry.get("source") or ""),
                    str(entry.get("event") or ""),
                )
                if part
            )
            details = entry.get("details") or {}
            body = str(entry.get("message") or "")
            if details:
                body = (body + "\n" if body else "") + json.dumps(details, ensure_ascii=False, indent=2)
            blocks.append((header + "\n" + body).strip())

        return "\n\n---\n\n".join(blocks)

    def clear(self) -> None:
        with self._lock:
            try:
                self.path.unlink(missing_ok=True)
            except Exception:
                pass

    def _compact(self, value: Any, depth: int = 0) -> Any:
        if value is None or isinstance(value, (int, float, bool)):
            return value
        if isinstance(value, str):
            return value[: self.max_detail_string] + ("..." if len(value) > self.max_detail_string else "")
        if depth >= 3:
            return "[object]"
        if isinstance(value, list):
            sample = [self._compact(item, depth + 1) for item in value[:8]]
            if len(value) > len(sample):
                sample.append(f"... +{len(value) - len(sample)}")
            return sample
        if isinstance(value, dict):
            out = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= 32:
                    out["..."] = f"+{len(value) - index}"
                    break
                if str(key).lower() in {"result_text", "visible_text", "patient_panel_text", "raw"}:
                    out[str(key) + "_length"] = len(str(item or ""))
                    continue
                out[str(key)] = self._compact(item, depth + 1)
            return out
        return str(value)[: self.max_detail_string]
