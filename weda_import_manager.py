from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@dataclass
class WedaImportRequest:
    id: str
    result_text: str
    patient_id: str = ""
    patient_identity: str = ""
    destination: str = "active_field"
    status: str = "pending"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    last_status_payload: dict[str, Any] = field(default_factory=dict)


class WedaImportManager:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._request = self._load()

    def prepare_result(
        self,
        result_text: str,
        *,
        patient_id: str = "",
        patient_identity: str = "",
        destination: str = "active_field",
    ) -> WedaImportRequest:
        request = WedaImportRequest(
            id=uuid.uuid4().hex,
            result_text=result_text,
            patient_id=patient_id,
            patient_identity=patient_identity,
            destination=destination,
        )
        with self._lock:
            self._request = request
            self._save(request)
        return request

    def get_latest(self) -> WedaImportRequest | None:
        with self._lock:
            return self._request

    def update_status(self, payload: dict[str, Any]) -> WedaImportRequest | None:
        with self._lock:
            if self._request is None:
                return None
            self._request.status = str(payload.get("status") or self._request.status)
            self._request.updated_at = utc_now_iso()
            self._request.last_status_payload = dict(payload)
            self._save(self._request)
            return self._request

    def clear(self) -> None:
        with self._lock:
            self._request = None
            try:
                self.path.unlink(missing_ok=True)
            except Exception:
                pass

    def _load(self) -> WedaImportRequest | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return WedaImportRequest(**data)
        except Exception:
            return None

    def _save(self, request: WedaImportRequest) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(request), ensure_ascii=False, indent=2), encoding="utf-8")
