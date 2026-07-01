from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:  # pragma: no cover - handled at runtime for clearer UI errors
    PdfReader = None  # type: ignore[assignment]
    PdfWriter = None  # type: ignore[assignment]


class PdfFillError(RuntimeError):
    pass


@dataclass
class PdfFillResult:
    output_path: Path
    warnings: list[str]
    filled_fields: list[str]
    ignored_fields: list[str]


class PdfFillManager:
    def fill_pdf(
        self,
        template_pdf_path: str | Path,
        values: dict[str, Any],
        output_path: str | Path,
        *,
        fields: list[dict[str, Any]] | None = None,
        max_text_length: int = 800,
    ) -> PdfFillResult:
        if PdfReader is None or PdfWriter is None:
            raise PdfFillError("La bibliothèque pypdf est manquante.")

        source = Path(template_pdf_path)
        destination = Path(output_path)
        if not source.exists():
            raise PdfFillError(f"PDF modèle introuvable: {source}")
        if destination.resolve() == source.resolve():
            raise PdfFillError("Refus d’écraser le PDF modèle.")

        try:
            reader = PdfReader(str(source))
        except Exception as exc:
            raise PdfFillError(f"PDF modèle illisible: {exc}") from exc
        if getattr(reader, "is_encrypted", False):
            raise PdfFillError("PDF modèle protégé ou chiffré.")

        try:
            known_fields = set((reader.get_fields() or {}).keys())
        except Exception:
            known_fields = set()
        metadata_by_name = {
            str(field.get("name") or ""): field
            for field in fields or []
            if field.get("name")
        }
        if metadata_by_name:
            known_fields.update(metadata_by_name.keys())

        clean_values: dict[str, Any] = {}
        warnings: list[str] = []
        ignored: list[str] = []
        for name, value in values.items():
            if known_fields and name not in known_fields:
                ignored.append(name)
                warnings.append(f"Champ inconnu ignoré: {name}")
                continue
            metadata = metadata_by_name.get(name, {})
            field_type = str(metadata.get("type") or "").lower()
            prepared = self._prepare_value(value, metadata)
            if self._is_empty_value(prepared):
                ignored.append(name)
                continue
            if isinstance(prepared, str) and len(prepared) > max_text_length:
                warnings.append(f"Valeur longue pour {name}: {len(prepared)} caractères")
            if field_type == "checkbox" and isinstance(prepared, bool):
                prepared = self._checkbox_pdf_value(prepared, metadata)
            clean_values[name] = prepared

        if not clean_values:
            warnings.append("Aucun champ à remplir.")

        writer = PdfWriter()
        writer.clone_document_from_reader(reader)
        try:
            writer.set_need_appearances_writer(True)
        except Exception as exc:
            warnings.append(f"NeedAppearances non activé: {exc}")

        if clean_values:
            try:
                writer.update_page_form_field_values(
                    list(writer.pages),
                    clean_values,
                    auto_regenerate=True,
                )
            except Exception as exc:
                raise PdfFillError(f"Remplissage PDF impossible: {exc}") from exc

        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as handle:
            writer.write(handle)

        return PdfFillResult(
            output_path=destination,
            warnings=warnings,
            filled_fields=list(clean_values.keys()),
            ignored_fields=ignored,
        )

    def _prepare_value(self, value: Any, metadata: dict[str, Any]) -> Any:
        field_type = str(metadata.get("type") or "").lower()
        if field_type == "checkbox":
            if isinstance(value, bool):
                return value
            text = str(value or "").strip().lower()
            return text in {"true", "vrai", "oui", "yes", "1", "on", "x", "coché", "coche", "checked"}
        if value is None:
            return ""
        return str(value).strip()

    def _checkbox_pdf_value(self, value: bool, metadata: dict[str, Any]) -> str:
        if not value:
            return "/Off"
        options = [str(option).lstrip("/") for option in metadata.get("options") or [] if str(option).strip()]
        return "/" + (options[0] if options else "Yes")

    def _is_empty_value(self, value: Any) -> bool:
        return value is None or value is False or str(value).strip() == ""
