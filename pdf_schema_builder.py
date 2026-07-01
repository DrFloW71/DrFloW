from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


BOOLEAN_TRUE_VALUES = {"true", "vrai", "oui", "yes", "1", "on", "x", "checked", "coché", "coche"}
BOOLEAN_FALSE_VALUES = {"false", "faux", "non", "no", "0", "off", "", "unchecked", "décoché", "decoche"}


@dataclass
class PdfValidationIssue:
    field: str
    level: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "level": self.level, "message": self.message}


@dataclass
class JsonObjectParseResult:
    values: dict[str, Any]
    recovered_partial: bool = False
    warning: str = ""


def build_json_schema(fields: list[dict[str, Any]]) -> dict[str, Any]:
    properties: dict[str, Any] = {}

    for field in fields:
        name = str(field.get("name") or "").strip()
        if not name:
            continue
        field_type = normalize_field_type(field.get("type"))
        json_type = "boolean" if field_type == "checkbox" else "string"
        property_schema: dict[str, Any] = {
            "type": json_type,
            "description": field_description(field),
        }
        options = [str(option) for option in field.get("options") or [] if str(option)]
        if options and json_type == "string":
            property_schema["enum"] = options + [""]
        properties[name] = property_schema

    return {
        "type": "object",
        "properties": properties,
        "required": [],
        "additionalProperties": False,
    }


def parse_json_object(text: str) -> dict[str, Any]:
    return parse_json_object_result(text).values


def parse_json_object_result(text: str) -> JsonObjectParseResult:
    raw = strip_json_fences(text)
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("La réponse JSON doit être un objet.")
        return JsonObjectParseResult(value)
    except json.JSONDecodeError as first_error:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            recovered = parse_partial_json_object(raw)
            if recovered:
                return JsonObjectParseResult(
                    recovered,
                    recovered_partial=True,
                    warning="Réponse Gemma JSON incomplète : champs complets récupérés, champs manquants laissés vides.",
                )
            raise ValueError("Réponse Gemma non JSON ou JSON tronqué avant le premier objet complet.") from first_error
        try:
            value = json.loads(raw[start:end + 1])
        except json.JSONDecodeError as second_error:
            recovered = parse_partial_json_object(raw[start:])
            if recovered:
                return JsonObjectParseResult(
                    recovered,
                    recovered_partial=True,
                    warning="Réponse Gemma JSON incomplète : champs complets récupérés, champs manquants laissés vides.",
                )
            raise ValueError(f"Réponse Gemma JSON invalide : {second_error.msg}.") from second_error
        if not isinstance(value, dict):
            raise ValueError("La réponse JSON doit être un objet.")
        return JsonObjectParseResult(value)


def validate_pdf_field_values(
    raw_values: dict[str, Any],
    fields: list[dict[str, Any]],
    *,
    max_text_length: int = 800,
) -> tuple[dict[str, str | bool], list[dict[str, str]]]:
    field_map = {str(field.get("name") or ""): field for field in fields if field.get("name")}
    values: dict[str, str | bool] = {}
    issues: list[PdfValidationIssue] = []

    for key, value in raw_values.items():
        if key not in field_map:
            issues.append(PdfValidationIssue(str(key), "warning", "Champ inconnu ignoré."))
            continue
        field = field_map[key]
        field_type = normalize_field_type(field.get("type"))
        if field_type == "checkbox":
            if value is None or (not isinstance(value, bool) and clean_text_value(value) == ""):
                continue
            converted = coerce_boolean(value)
            if converted is None:
                issues.append(PdfValidationIssue(key, "warning", "Valeur booléenne invalide ignorée."))
                continue
            values[key] = converted
            continue

        text = clean_text_value(value)
        if not text:
            continue
        if len(text) > max_text_length:
            issues.append(PdfValidationIssue(key, "warning", f"Valeur longue ({len(text)} caractères), à vérifier."))
        options = [str(option) for option in field.get("options") or [] if str(option)]
        if options and text and text not in options:
            issues.append(PdfValidationIssue(key, "warning", "Valeur hors liste d’options PDF."))
        values[key] = text

    return values, [issue.to_dict() for issue in issues]


def build_preview_rows(
    fields: list[dict[str, Any]],
    values: dict[str, str | bool],
    issues: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    issue_map: dict[str, list[str]] = {}
    for issue in issues or []:
        issue_map.setdefault(str(issue.get("field") or ""), []).append(str(issue.get("message") or ""))

    rows = []
    for field in fields:
        name = str(field.get("name") or "")
        value = values.get(name, "")
        issue_text = "; ".join(issue_map.get(name, []))
        status = issue_text or ("Manquant" if is_empty_value(value) and field.get("required") else "OK")
        rows.append(
            {
                "name": name,
                "label": str(field.get("label") or name),
                "type": str(field.get("type") or "text"),
                "value": "true" if value is True else "false" if value is False else str(value or ""),
                "status": status,
            }
        )
    return rows


def strip_json_fences(text: str) -> str:
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def parse_partial_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "")
    start = raw.find("{")
    if start < 0:
        return {}

    decoder = json.JSONDecoder()
    index = start + 1
    values: dict[str, Any] = {}

    while index < len(raw):
        index = skip_json_whitespace(raw, index)
        if index >= len(raw) or raw[index] == "}":
            break
        if raw[index] == ",":
            index += 1
            continue
        if raw[index] != '"':
            break

        try:
            key, index = decoder.raw_decode(raw, index)
        except json.JSONDecodeError:
            break
        if not isinstance(key, str):
            break

        index = skip_json_whitespace(raw, index)
        if index >= len(raw) or raw[index] != ":":
            break
        index += 1
        index = skip_json_whitespace(raw, index)
        if index >= len(raw):
            break

        try:
            value, index = decoder.raw_decode(raw, index)
        except json.JSONDecodeError:
            break

        values[key] = value
        index = skip_json_whitespace(raw, index)
        if index < len(raw) and raw[index] == ",":
            index += 1
            continue
        if index < len(raw) and raw[index] == "}":
            break

    return values


def skip_json_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def clean_text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return re.sub(r"\s+", " ", str(value)).strip()


def coerce_boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    text = clean_text_value(value).lower()
    if text in BOOLEAN_TRUE_VALUES:
        return True
    if text in BOOLEAN_FALSE_VALUES:
        return False
    return None


def is_empty_value(value: Any) -> bool:
    return value is None or value is False or clean_text_value(value) == ""


def normalize_field_type(value: Any) -> str:
    text = str(value or "text").strip().lower()
    return text or "text"


def field_description(field: dict[str, Any]) -> str:
    return str(
        field.get("description")
        or field.get("label")
        or field.get("name")
        or "Champ PDF"
    )
