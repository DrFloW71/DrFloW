from __future__ import annotations

import difflib
import hashlib
import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def content_hash(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class PromptVersion:
    version_id: str
    at: str
    prompt_id: str
    prompt_name: str
    prompt_type: str
    content: str
    content_hash: str
    source: str

    @property
    def label(self) -> str:
        return f"{self.at.replace('T', ' ')[:19]} • {self.content_hash[:8]} • {self.source}"


class PromptVersionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def record(self, prompt, *, source: str = "save") -> PromptVersion:
        prompt_id = str(getattr(prompt, "id", "") or "")
        prompt_name = str(getattr(prompt, "name", "") or "Prompt sans nom")
        prompt_type = str(getattr(prompt, "prompt_type", "") or "generic")
        content = str(getattr(prompt, "content", "") or "")
        digest = content_hash(content)

        with self._lock:
            existing = self._read_unlocked()
            latest = next((item for item in reversed(existing) if item.prompt_id == prompt_id), None)
            if latest and latest.content_hash == digest and latest.prompt_name == prompt_name:
                return latest
            version = PromptVersion(
                version_id=uuid.uuid4().hex,
                at=utc_now_iso(),
                prompt_id=prompt_id,
                prompt_name=prompt_name,
                prompt_type=prompt_type,
                content=content,
                content_hash=digest,
                source=str(source or "save"),
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(version), ensure_ascii=False) + "\n")
            return version

    def snapshot(self, prompts: Iterable, *, source: str = "snapshot") -> list[PromptVersion]:
        return [self.record(prompt, source=source) for prompt in prompts]

    def list_versions(self, prompt_id: str | None = None) -> list[PromptVersion]:
        with self._lock:
            versions = self._read_unlocked()
        if prompt_id is None:
            return versions
        return [item for item in versions if item.prompt_id == prompt_id]

    def _read_unlocked(self) -> list[PromptVersion]:
        if not self.path.exists():
            return []
        versions: list[PromptVersion] = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                raw = json.loads(line)
                versions.append(PromptVersion(**raw))
            except (json.JSONDecodeError, TypeError):
                continue
        return versions


class QualityMetricsStore:
    """Stores numeric metadata only; patient text and identifiers are never persisted."""

    SAFE_KEYS = {
        "at",
        "event",
        "generation_id",
        "workflow",
        "source",
        "prompt_id",
        "prompt_name",
        "prompt_version",
        "status",
        "elapsed_seconds",
        "input_chars",
        "result_chars",
        "error_type",
        "generated_chars",
        "final_chars",
        "word_changes",
        "correction_ratio",
    }

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def record_generation(
        self,
        *,
        workflow: str,
        source: str,
        prompt_id: str = "",
        prompt_name: str = "",
        prompt_version: str = "",
        status: str,
        elapsed_seconds: float | None = None,
        input_chars: int = 0,
        result_chars: int = 0,
        error_type: str = "",
    ) -> dict[str, Any]:
        entry = {
            "at": utc_now_iso(),
            "event": "generation",
            "generation_id": uuid.uuid4().hex,
            "workflow": str(workflow or "unknown"),
            "source": str(source or ""),
            "prompt_id": str(prompt_id or ""),
            "prompt_name": str(prompt_name or ""),
            "prompt_version": str(prompt_version or ""),
            "status": str(status or "unknown"),
            "elapsed_seconds": round(float(elapsed_seconds), 3) if elapsed_seconds is not None else None,
            "input_chars": max(0, int(input_chars or 0)),
            "result_chars": max(0, int(result_chars or 0)),
            "error_type": str(error_type or ""),
        }
        self._append(entry)
        return entry

    def record_correction(
        self,
        *,
        workflow: str,
        source: str,
        generation_id: str,
        prompt_id: str,
        prompt_name: str,
        generated_text: str,
        final_text: str,
    ) -> dict[str, Any]:
        generated = str(generated_text or "")
        final = str(final_text or "")
        ratio = difflib.SequenceMatcher(None, generated, final).ratio() if generated or final else 1.0
        word_changes = _word_change_count(generated, final)
        entry = {
            "at": utc_now_iso(),
            "event": "correction",
            "generation_id": str(generation_id or ""),
            "workflow": str(workflow or "unknown"),
            "source": str(source or ""),
            "prompt_id": str(prompt_id or ""),
            "prompt_name": str(prompt_name or ""),
            "generated_chars": len(generated),
            "final_chars": len(final),
            "word_changes": word_changes,
            "correction_ratio": round(max(0.0, min(1.0, 1.0 - ratio)), 4),
            "status": "measured",
        }
        self._append(entry)
        return entry

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        out = []
        for line in lines:
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(raw, dict):
                out.append({key: value for key, value in raw.items() if key in self.SAFE_KEYS})
        return out

    def summary(self) -> list[dict[str, Any]]:
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for entry in self.entries():
            key = (str(entry.get("workflow") or "unknown"), str(entry.get("prompt_name") or "sans nom"))
            group = groups.setdefault(
                key,
                {
                    "workflow": key[0],
                    "prompt_name": key[1],
                    "generations": 0,
                    "successes": 0,
                    "errors": 0,
                    "latencies": [],
                    "corrections": [],
                },
            )
            if entry.get("event") == "generation":
                group["generations"] += 1
                if entry.get("status") == "success":
                    group["successes"] += 1
                elif entry.get("status") in {"error", "cancelled"}:
                    group["errors"] += 1
                if isinstance(entry.get("elapsed_seconds"), (int, float)):
                    group["latencies"].append(float(entry["elapsed_seconds"]))
            elif entry.get("event") == "correction" and isinstance(entry.get("correction_ratio"), (int, float)):
                group["corrections"].append(float(entry["correction_ratio"]))

        summaries = []
        for group in groups.values():
            latencies = group.pop("latencies")
            corrections = group.pop("corrections")
            group["average_latency"] = round(sum(latencies) / len(latencies), 2) if latencies else None
            group["average_correction_percent"] = (
                round(100.0 * sum(corrections) / len(corrections), 1) if corrections else None
            )
            summaries.append(group)
        return sorted(summaries, key=lambda item: (item["workflow"], item["prompt_name"].lower()))

    def _append(self, raw: dict[str, Any]) -> None:
        entry = {key: value for key, value in raw.items() if key in self.SAFE_KEYS}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def unified_text_diff(left: str, right: str, *, left_label: str = "A", right_label: str = "B") -> str:
    return "\n".join(
        difflib.unified_diff(
            str(left or "").splitlines(),
            str(right or "").splitlines(),
            fromfile=left_label,
            tofile=right_label,
            lineterm="",
        )
    ) or "Aucune différence."


def _word_change_count(left: str, right: str) -> int:
    matcher = difflib.SequenceMatcher(None, str(left or "").split(), str(right or "").split())
    return sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in matcher.get_opcodes() if op != "equal")
