from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from medical_transcription import MIN_VALIDATIONS_FOR_AUTOMATIC_CORRECTION, normalize_for_match


SCHEMA_VERSION = 1
MEDICAL_CATEGORIES = {
    "medicament",
    "pathologie",
    "examen",
    "biologie",
    "nom_propre",
    "dispositif",
    "allergie",
}
CRITICAL_WORDS = {
    "oui",
    "non",
    "absence",
    "présence",
    "avec",
    "sans",
    "positif",
    "négatif",
    "droite",
    "droit",
    "gauche",
    "dose",
    "allergie",
    "allergique",
}
TOKEN_RE = re.compile(r"\S+")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class CorrectionEntry:
    source: str
    correction: str
    normalized_source: str
    normalized_correction: str
    context_before: str = ""
    context_after: str = ""
    category: str = "autre"
    validation_count: int = 1
    rejection_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    last_used_at: str | None = None
    active: bool = True
    whisper_model: str = ""
    segment_index: int | None = None
    correction_type: str = "manual"

    @classmethod
    def from_mapping(cls, value: dict) -> "CorrectionEntry":
        now = utc_now_iso()
        source = str(value.get("source") or "").strip()
        correction = str(value.get("correction") or "").strip()
        return cls(
            source=source,
            correction=correction,
            normalized_source=str(value.get("normalized_source") or normalize_for_match(source)),
            normalized_correction=str(value.get("normalized_correction") or normalize_for_match(correction)),
            context_before=str(value.get("context_before") or "").strip(),
            context_after=str(value.get("context_after") or "").strip(),
            category=str(value.get("category") or "autre").strip().lower(),
            validation_count=max(0, int(value.get("validation_count") or 0)),
            rejection_count=max(0, int(value.get("rejection_count") or 0)),
            created_at=str(value.get("created_at") or now),
            updated_at=str(value.get("updated_at") or now),
            last_used_at=value.get("last_used_at"),
            active=bool(value.get("active", True)),
            whisper_model=str(value.get("whisper_model") or ""),
            segment_index=value.get("segment_index"),
            correction_type=str(value.get("correction_type") or "manual"),
        )


@dataclass(frozen=True)
class ProposedCorrection:
    source: str
    correction: str
    context_before: str
    context_after: str


class CorrectionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._entries: list[CorrectionEntry] = []
        self.load_error = ""
        self._load()

    def list_entries(self, *, active_only: bool = False) -> list[CorrectionEntry]:
        with self._lock:
            values = [entry for entry in self._entries if entry.active or not active_only]
            return [CorrectionEntry.from_mapping(asdict(entry)) for entry in values]

    def validate(
        self,
        source: str,
        correction: str,
        *,
        context_before: str = "",
        context_after: str = "",
        category: str = "autre",
        whisper_model: str = "",
        segment_index: int | None = None,
    ) -> CorrectionEntry:
        source = str(source or "").strip()
        correction = str(correction or "").strip()
        if not source or not correction or normalize_for_match(source) == normalize_for_match(correction):
            raise ValueError("La source et la correction doivent être différentes et non vides.")
        normalized_source = normalize_for_match(source)
        normalized_correction = normalize_for_match(correction)
        now = utc_now_iso()
        with self._lock:
            for entry in self._entries:
                if (
                    entry.normalized_source == normalized_source
                    and entry.normalized_correction == normalized_correction
                ):
                    entry.validation_count += 1
                    entry.updated_at = now
                    entry.active = True
                    if context_before:
                        entry.context_before = str(context_before).strip()
                    if context_after:
                        entry.context_after = str(context_after).strip()
                    self._save()
                    return CorrectionEntry.from_mapping(asdict(entry))
            entry = CorrectionEntry(
                source=source,
                correction=correction,
                normalized_source=normalized_source,
                normalized_correction=normalized_correction,
                context_before=str(context_before or "").strip(),
                context_after=str(context_after or "").strip(),
                category=str(category or "autre").strip().lower(),
                validation_count=1,
                rejection_count=0,
                created_at=now,
                updated_at=now,
                whisper_model=str(whisper_model or ""),
                segment_index=segment_index,
            )
            self._entries.append(entry)
            self._save()
            return CorrectionEntry.from_mapping(asdict(entry))

    def reject(self, source: str, correction: str, *, context_before: str = "", context_after: str = "") -> CorrectionEntry:
        normalized_source = normalize_for_match(source)
        normalized_correction = normalize_for_match(correction)
        now = utc_now_iso()
        with self._lock:
            for entry in self._entries:
                if entry.normalized_source == normalized_source and entry.normalized_correction == normalized_correction:
                    entry.rejection_count += 1
                    entry.updated_at = now
                    self._save()
                    return CorrectionEntry.from_mapping(asdict(entry))
            entry = CorrectionEntry(
                source=str(source or "").strip(),
                correction=str(correction or "").strip(),
                normalized_source=normalized_source,
                normalized_correction=normalized_correction,
                context_before=str(context_before or "").strip(),
                context_after=str(context_after or "").strip(),
                validation_count=0,
                rejection_count=1,
                created_at=now,
                updated_at=now,
                active=False,
            )
            self._entries.append(entry)
            self._save()
            return CorrectionEntry.from_mapping(asdict(entry))

    def set_active(self, source: str, correction: str, active: bool) -> bool:
        with self._lock:
            for entry in self._entries:
                if entry.normalized_source == normalize_for_match(source) and entry.normalized_correction == normalize_for_match(correction):
                    entry.active = bool(active)
                    entry.updated_at = utc_now_iso()
                    self._save()
                    return True
        return False

    def hotwords(self) -> list[str]:
        entries = sorted(
            self.list_entries(active_only=True),
            key=lambda entry: (-entry.validation_count, entry.rejection_count, entry.updated_at),
        )
        return [
            entry.correction
            for entry in entries
            if entry.validation_count > entry.rejection_count and entry.category in MEDICAL_CATEGORIES
        ]

    def apply_conservative(self, text: str, *, min_validations: int = MIN_VALIDATIONS_FOR_AUTOMATIC_CORRECTION) -> tuple[str, int]:
        result = str(text or "")
        applied = 0
        entries = self.list_entries(active_only=True)
        sources: dict[str, set[str]] = {}
        for entry in entries:
            sources.setdefault(entry.normalized_source, set()).add(entry.normalized_correction)
        for entry in sorted(entries, key=lambda item: len(item.source), reverse=True):
            if entry.validation_count < int(min_validations) or entry.rejection_count:
                continue
            if len(sources.get(entry.normalized_source, set())) != 1 or not _safe_for_automatic_correction(entry):
                continue
            pattern = re.compile(rf"(?<!\w){re.escape(entry.source)}(?!\w)", re.IGNORECASE)
            result, count = pattern.subn(entry.correction, result)
            if count:
                applied += count
                with self._lock:
                    for stored in self._entries:
                        if stored.normalized_source == entry.normalized_source and stored.normalized_correction == entry.normalized_correction:
                            stored.last_used_at = utc_now_iso()
                self._save()
        return result, applied

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            entries = payload.get("entries", []) if isinstance(payload, dict) else payload
            self._entries = [CorrectionEntry.from_mapping(item) for item in entries if isinstance(item, dict)]
            if not isinstance(payload, dict) or int(payload.get("schema_version") or 0) != SCHEMA_VERSION:
                self._backup("migration")
                self._save()
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self.load_error = str(exc)
            self._backup("corrupt")
            self._entries = []

    def _backup(self, reason: str) -> None:
        if not self.path.exists():
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.path.with_name(f"{self.path.stem}.{reason}.{stamp}.bak")
        try:
            shutil.copy2(self.path, backup)
        except OSError:
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": utc_now_iso(),
            "entries": [asdict(entry) for entry in self._entries],
        }
        handle, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass


def _safe_for_automatic_correction(entry: CorrectionEntry) -> bool:
    source_words = set(normalize_for_match(entry.source).split())
    correction_words = set(normalize_for_match(entry.correction).split())
    if source_words & {normalize_for_match(word) for word in CRITICAL_WORDS}:
        return False
    if correction_words & {normalize_for_match(word) for word in CRITICAL_WORDS}:
        return False
    if re.search(r"\d", entry.source) or re.search(r"\d", entry.correction):
        return False
    if len(entry.normalized_source) < 5:
        return False
    return entry.category in MEDICAL_CATEGORIES


def propose_corrections(raw_text: str, corrected_text: str, *, context_words: int = 5) -> list[ProposedCorrection]:
    raw_tokens = TOKEN_RE.findall(str(raw_text or ""))
    corrected_tokens = TOKEN_RE.findall(str(corrected_text or ""))
    matcher = difflib.SequenceMatcher(a=[normalize_for_match(token) for token in raw_tokens], b=[normalize_for_match(token) for token in corrected_tokens], autojunk=False)
    proposals: list[ProposedCorrection] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace" or i1 == i2 or j1 == j2:
            continue
        proposals.append(
            ProposedCorrection(
                source=" ".join(raw_tokens[i1:i2]),
                correction=" ".join(corrected_tokens[j1:j2]),
                context_before=" ".join(raw_tokens[max(0, i1 - context_words):i1]),
                context_after=" ".join(raw_tokens[i2:i2 + context_words]),
            )
        )
    return proposals


def format_correction_review(raw_text: str, corrected_text: str) -> str:
    proposals = propose_corrections(raw_text, corrected_text)
    if not proposals:
        return "Aucune correction lexicale proposée."
    lines = []
    for index, proposal in enumerate(proposals, 1):
        context = " ".join(part for part in (proposal.context_before, "[…]", proposal.context_after) if part)
        lines.append(f"{index}. {proposal.source}  →  {proposal.correction}\n   Contexte : {context}")
    return "\n\n".join(lines)
