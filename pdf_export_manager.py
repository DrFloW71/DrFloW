from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path


class PdfExportError(RuntimeError):
    pass


class PdfExportManager:
    def __init__(self, outputs_dir: str | Path):
        self.outputs_dir = Path(outputs_dir)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

    def build_output_path(
        self,
        *,
        template_name: str,
        patient_identity: str = "",
        timestamp: datetime | None = None,
    ) -> Path:
        stamp = (timestamp or datetime.now()).strftime("%Y-%m-%d_%H-%M")
        patient = sanitize_filename(patient_identity).strip("_")
        template = sanitize_filename(template_name or "modele").strip("_") or "modele"
        if patient:
            filename = f"{stamp}_{patient}_{template}.pdf"
        else:
            filename = f"{stamp}_pdf_rempli_{template}.pdf"
        return self.unique_path(self.outputs_dir / filename)

    def unique_path(self, path: str | Path) -> Path:
        candidate = Path(path)
        if not candidate.exists():
            return candidate
        stem = candidate.stem
        suffix = candidate.suffix
        parent = candidate.parent
        index = 2
        while True:
            next_path = parent / f"{stem}_{index}{suffix}"
            if not next_path.exists():
                return next_path
            index += 1

    def open_file(self, path: str | Path) -> None:
        target = Path(path)
        if not target.exists():
            raise PdfExportError(f"PDF final introuvable: {target}")
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
        except AttributeError as exc:
            raise PdfExportError("Ouverture automatique indisponible sur ce système.") from exc
        except OSError as exc:
            raise PdfExportError(f"Ouverture du PDF impossible: {exc}") from exc


def sanitize_filename(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^\w\s.-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s.]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text[:90].strip("_") or "pdf"
