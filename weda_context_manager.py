from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@dataclass
class WedaContext:
    patient_id: str = ""
    patient_identity: str = ""
    patient_name: str = ""
    patient_birthdate: str = ""
    patient_age: str = ""
    patient_sex: str = ""
    page_url: str = ""
    page_title: str = ""
    visible_text: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    received_at: str = field(default_factory=utc_now_iso)

    def to_prompt_text(self) -> str:
        lines = [
            f"Patient: {self.patient_identity}".strip(),
            f"ID WEDA: {self.patient_id}".strip(),
            f"Naissance/âge: {self.patient_birthdate or self.patient_age}".strip(),
            f"Sexe: {self.patient_sex}".strip(),
            f"Page: {self.page_title}".strip(),
            f"URL: {self.page_url}".strip(),
            "",
            self.visible_text.strip(),
        ]
        return "\n".join(line for line in lines if line)


class WedaContextManager:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._latest = self._load()

    def update_context(self, payload: dict[str, Any]) -> WedaContext:
        context = WedaContext(
            patient_id=str(payload.get("patient_id") or payload.get("patientId") or ""),
            patient_identity=str(payload.get("patient_identity") or payload.get("patientIdentity") or ""),
            patient_name=str(payload.get("patient_name") or payload.get("patientName") or ""),
            patient_birthdate=str(payload.get("patient_birthdate") or payload.get("birthdate") or ""),
            patient_age=str(payload.get("patient_age") or payload.get("age") or ""),
            patient_sex=str(payload.get("patient_sex") or payload.get("sex") or ""),
            page_url=str(payload.get("page_url") or payload.get("url") or ""),
            page_title=str(payload.get("page_title") or payload.get("title") or ""),
            visible_text=str(payload.get("visible_text") or payload.get("visibleText") or ""),
            raw=dict(payload),
        )
        with self._lock:
            self._latest = context
            self._save(context)
        return context

    def get_latest(self) -> WedaContext | None:
        with self._lock:
            return self._latest

    def clear(self) -> None:
        with self._lock:
            self._latest = None
            try:
                self.path.unlink(missing_ok=True)
            except Exception:
                pass

    def _load(self) -> WedaContext | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return WedaContext(**data)
        except Exception:
            return None

    def _save(self, context: WedaContext) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(context), ensure_ascii=False, indent=2), encoding="utf-8")
