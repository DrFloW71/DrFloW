from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

try:
    from pypdf import PdfReader
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject
except ImportError:  # pragma: no cover - handled at runtime for clearer UI errors
    PdfReader = None  # type: ignore[assignment]
    ArrayObject = DictionaryObject = IndirectObject = NameObject = object  # type: ignore[misc,assignment]


class PdfFieldExtractionError(RuntimeError):
    pass


class PdfNoFieldsError(PdfFieldExtractionError):
    pass


class PdfEncryptedError(PdfFieldExtractionError):
    pass


@dataclass
class PdfField:
    name: str
    type: str
    value: str | bool | list[str] | None = ""
    options: list[str] | None = None
    page: int | None = None
    label: str = ""
    required: bool = False
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["options"] = data.get("options") or []
        return data


def extract_pdf_fields(pdf_path: str | Path) -> list[dict[str, Any]]:
    return [field.to_dict() for field in PdfFieldExtractor().extract(pdf_path)]


class PdfFieldExtractor:
    def extract(self, pdf_path: str | Path) -> list[PdfField]:
        if PdfReader is None:
            raise PdfFieldExtractionError("La bibliothèque pypdf est manquante.")

        path = Path(pdf_path)
        if not path.exists():
            raise PdfFieldExtractionError(f"PDF introuvable: {path}")

        try:
            reader = PdfReader(str(path))
        except Exception as exc:
            raise PdfFieldExtractionError(f"PDF illisible: {exc}") from exc

        if getattr(reader, "is_encrypted", False):
            raise PdfEncryptedError("PDF protégé ou chiffré.")

        try:
            raw_fields = reader.get_fields() or {}
        except Exception as exc:
            raise PdfFieldExtractionError(f"Extraction des champs impossible: {exc}") from exc

        annotation_map = self._collect_widget_annotations(reader)
        fields: list[PdfField] = []
        seen: set[str] = set()

        for name, raw in raw_fields.items():
            field_name = str(name or self._get_text(raw, "/T") or "").strip()
            if not field_name or field_name in seen:
                continue
            annotation = annotation_map.get(field_name, {})
            merged = self._merge_field_objects(raw, annotation.get("field"))
            field = PdfField(
                name=field_name,
                type=self._infer_field_type(merged),
                value=self._extract_value(merged),
                options=self._extract_options(merged),
                page=annotation.get("page"),
                label=humanize_field_name(field_name),
                required=self._is_required(merged),
                description="",
            )
            fields.append(field)
            seen.add(field_name)

        for field_name, annotation in annotation_map.items():
            if field_name in seen:
                continue
            raw = annotation.get("field") or {}
            fields.append(
                PdfField(
                    name=field_name,
                    type=self._infer_field_type(raw),
                    value=self._extract_value(raw),
                    options=self._extract_options(raw),
                    page=annotation.get("page"),
                    label=humanize_field_name(field_name),
                    required=self._is_required(raw),
                    description="",
                )
            )
            seen.add(field_name)

        fields.sort(key=lambda item: ((item.page or 9999), item.name.lower()))
        if not fields:
            raise PdfNoFieldsError(
                "Aucun champ PDF structuré détecté. Ce PDF nécessite un gabarit manuel, non pris en charge dans cette version."
            )
        return fields

    def _collect_widget_annotations(self, reader) -> dict[str, dict[str, Any]]:
        annotations: dict[str, dict[str, Any]] = {}
        for page_index, page in enumerate(reader.pages, start=1):
            for annotation in self._iter_page_annotations(page):
                field_name = self._qualified_field_name(annotation)
                if not field_name:
                    continue
                annotations.setdefault(field_name, {"field": annotation, "page": page_index})
        return annotations

    def _iter_page_annotations(self, page) -> list[dict[str, Any]]:
        try:
            raw_annotations = page.get("/Annots") or []
        except Exception:
            return []

        annotations = []
        for raw in raw_annotations:
            try:
                annotation = raw.get_object() if hasattr(raw, "get_object") else raw
            except Exception:
                continue
            if not isinstance(annotation, dict):
                continue
            if str(annotation.get("/Subtype") or "") == "/Widget" or annotation.get("/FT") or annotation.get("/Parent"):
                annotations.append(annotation)
        return annotations

    def _qualified_field_name(self, field: dict[str, Any]) -> str:
        parts: list[str] = []
        current = field
        guard = 0
        while current and guard < 12:
            name = self._get_text(current, "/T")
            if name:
                parts.append(name)
            parent = current.get("/Parent") if isinstance(current, dict) else None
            if not parent:
                break
            try:
                current = parent.get_object() if hasattr(parent, "get_object") else parent
            except Exception:
                break
            guard += 1
        return ".".join(reversed([part for part in parts if part])).strip()

    def _merge_field_objects(self, raw: Any, annotation: Any) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for source in (annotation, raw):
            if not source:
                continue
            try:
                obj = source.get_object() if hasattr(source, "get_object") else source
            except Exception:
                obj = source
            if isinstance(obj, dict):
                merged.update(obj)
        return merged

    def _infer_field_type(self, field: dict[str, Any]) -> str:
        ft = str(field.get("/FT") or "")
        name = self._get_text(field, "/T").lower()
        if ft == "/Tx":
            return "date" if "date" in name else "text"
        if ft == "/Btn":
            flags = int(field.get("/Ff") or 0)
            if flags & 32768:
                return "radio"
            if flags & 65536:
                return "button"
            return "checkbox"
        if ft == "/Ch":
            return "choice"
        if ft == "/Sig":
            return "signature"
        return "unknown"

    def _extract_value(self, field: dict[str, Any]) -> str | bool | list[str] | None:
        value = field.get("/V")
        field_type = self._infer_field_type(field)
        if field_type == "checkbox":
            return str(value or "/Off") not in {"", "/Off", "Off", "false", "False"}
        if isinstance(value, ArrayObject):
            return [str(item) for item in value]
        if value is None:
            return False if field_type == "checkbox" else ""
        return self._pdf_value_to_text(value)

    def _extract_options(self, field: dict[str, Any]) -> list[str]:
        options: list[str] = []
        raw_options = field.get("/Opt")
        if raw_options:
            for option in raw_options:
                if isinstance(option, ArrayObject) and option:
                    options.append(self._pdf_value_to_text(option[0]))
                else:
                    options.append(self._pdf_value_to_text(option))

        appearance = field.get("/AP")
        try:
            normal = appearance.get("/N") if appearance else None
            normal = normal.get_object() if hasattr(normal, "get_object") else normal
            if isinstance(normal, dict):
                for key in normal.keys():
                    text = self._pdf_value_to_text(key)
                    if text and text not in {"Off", "/Off"}:
                        options.append(text.lstrip("/"))
        except Exception:
            pass

        return sorted(set(option for option in options if option))

    def _is_required(self, field: dict[str, Any]) -> bool:
        try:
            return bool(int(field.get("/Ff") or 0) & 2)
        except Exception:
            return False

    def _get_text(self, field: dict[str, Any], key: str) -> str:
        return self._pdf_value_to_text(field.get(key))

    def _pdf_value_to_text(self, value: Any) -> str:
        if value is None:
            return ""
        text = str(value)
        return text[1:] if text.startswith("/") else text


def humanize_field_name(name: str) -> str:
    clean = str(name or "").replace(".", " ").replace("_", " ").replace("-", " ")
    clean = " ".join(part for part in clean.split() if part)
    return clean[:1].upper() + clean[1:] if clean else "Champ PDF"
