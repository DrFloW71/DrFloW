from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pdf_field_extractor import PdfFieldExtractor


TEMPLATES_INDEX = "templates.json"
TEMPLATE_PDF_NAME = "original.pdf"
TEMPLATE_METADATA_NAME = "metadata.json"
TEMPLATE_FIELDS_NAME = "fields.json"


class PdfTemplateError(RuntimeError):
    pass


class PdfTemplateManager:
    def __init__(self, templates_dir: str | Path):
        self.templates_dir = Path(templates_dir)
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.templates_dir / TEMPLATES_INDEX
        if not self.index_path.exists():
            self._save_index([])

    def import_template(
        self,
        pdf_path: str | Path,
        *,
        name: str,
        description: str = "",
        default_prompt_id: str = "pdf_form_fill",
    ) -> dict[str, Any]:
        source = Path(pdf_path)
        if not source.exists():
            raise PdfTemplateError(f"PDF introuvable: {source}")

        fields = PdfFieldExtractor().extract(source)
        template_id = self._unique_template_id(slugify(name or source.stem))
        template_dir = self.template_dir(template_id)
        template_dir.mkdir(parents=True, exist_ok=False)

        now = utc_now_iso()
        metadata = {
            "id": template_id,
            "name": (name or source.stem).strip(),
            "original_filename": source.name,
            "created_at": now,
            "updated_at": now,
            "field_count": len(fields),
            "description": description.strip(),
            "default_prompt_id": default_prompt_id or "pdf_form_fill",
        }

        shutil.copy2(source, template_dir / TEMPLATE_PDF_NAME)
        self._write_json(template_dir / TEMPLATE_METADATA_NAME, metadata)
        self._write_json(template_dir / TEMPLATE_FIELDS_NAME, [field.to_dict() for field in fields])
        self._upsert_index(metadata)
        return metadata

    def list_templates(self) -> list[dict[str, Any]]:
        templates = []
        for item in self._load_index():
            metadata = self.get_template(str(item.get("id") or ""), missing_ok=True)
            if metadata:
                templates.append(metadata)
        templates.sort(key=lambda item: str(item.get("name") or "").lower())
        return templates

    def get_template(self, template_id: str, *, missing_ok: bool = False) -> dict[str, Any] | None:
        path = self.template_dir(template_id) / TEMPLATE_METADATA_NAME
        if not path.exists():
            if missing_ok:
                return None
            raise PdfTemplateError(f"Modèle PDF introuvable: {template_id}")
        metadata = self._read_json(path, {})
        metadata["template_path"] = str(self.template_pdf_path(template_id))
        metadata["fields_path"] = str(self.fields_path(template_id))
        return metadata

    def load_fields(self, template_id: str) -> list[dict[str, Any]]:
        path = self.fields_path(template_id)
        if not path.exists():
            raise PdfTemplateError(f"Champs introuvables pour le modèle: {template_id}")
        fields = self._read_json(path, [])
        return fields if isinstance(fields, list) else []

    def save_fields(self, template_id: str, fields: list[dict[str, Any]]) -> None:
        self._ensure_template_exists(template_id)
        self._write_json(self.fields_path(template_id), fields)
        metadata = self.get_template(template_id) or {}
        metadata["field_count"] = len(fields)
        metadata["updated_at"] = utc_now_iso()
        self._save_metadata(template_id, metadata)

    def update_field(self, template_id: str, field_name: str, patch: dict[str, Any]) -> list[dict[str, Any]]:
        fields = self.load_fields(template_id)
        updated = False
        for field in fields:
            if str(field.get("name") or "") != field_name:
                continue
            for key in ("label", "description", "required", "type"):
                if key in patch:
                    field[key] = patch[key]
            updated = True
            break
        if not updated:
            raise PdfTemplateError(f"Champ introuvable: {field_name}")
        self.save_fields(template_id, fields)
        return fields

    def rename_template(self, template_id: str, new_name: str) -> dict[str, Any]:
        metadata = self.get_template(template_id) or {}
        metadata["name"] = new_name.strip() or metadata.get("name") or template_id
        metadata["updated_at"] = utc_now_iso()
        self._save_metadata(template_id, metadata)
        self._upsert_index(metadata)
        return metadata

    def update_template_metadata(self, template_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        metadata = self.get_template(template_id) or {}
        for key in ("name", "description", "default_prompt_id"):
            if key in patch:
                metadata[key] = str(patch[key] or "").strip()
        metadata["updated_at"] = utc_now_iso()
        self._save_metadata(template_id, metadata)
        self._upsert_index(metadata)
        return metadata

    def delete_template(self, template_id: str) -> None:
        self._ensure_template_exists(template_id)
        shutil.rmtree(self.template_dir(template_id))
        self._save_index([item for item in self._load_index() if item.get("id") != template_id])

    def template_pdf_path(self, template_id: str) -> Path:
        return self.template_dir(template_id) / TEMPLATE_PDF_NAME

    def fields_path(self, template_id: str) -> Path:
        return self.template_dir(template_id) / TEMPLATE_FIELDS_NAME

    def template_dir(self, template_id: str) -> Path:
        safe_id = slugify(template_id)
        return self.templates_dir / safe_id

    def _ensure_template_exists(self, template_id: str) -> None:
        if not self.template_dir(template_id).exists():
            raise PdfTemplateError(f"Modèle PDF introuvable: {template_id}")

    def _save_metadata(self, template_id: str, metadata: dict[str, Any]) -> None:
        clean = dict(metadata)
        clean.pop("template_path", None)
        clean.pop("fields_path", None)
        self._write_json(self.template_dir(template_id) / TEMPLATE_METADATA_NAME, clean)

    def _upsert_index(self, metadata: dict[str, Any]) -> None:
        index = [item for item in self._load_index() if item.get("id") != metadata.get("id")]
        index.append(
            {
                "id": metadata.get("id"),
                "name": metadata.get("name"),
                "updated_at": metadata.get("updated_at"),
                "field_count": metadata.get("field_count", 0),
            }
        )
        self._save_index(index)

    def _load_index(self) -> list[dict[str, Any]]:
        data = self._read_json(self.index_path, [])
        return data if isinstance(data, list) else []

    def _save_index(self, index: list[dict[str, Any]]) -> None:
        self._write_json(self.index_path, index)

    def _unique_template_id(self, base_id: str) -> str:
        base = base_id or "modele_pdf"
        candidate = base
        index = 2
        while self.template_dir(candidate).exists():
            candidate = f"{base}_{index}"
            index += 1
        return candidate

    def _read_json(self, path: Path, fallback):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return fallback

    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def slugify(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s-]+", "_", text)
    text = text.strip("_")
    return text or "modele_pdf"


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
