from __future__ import annotations

import re
from typing import Mapping


SECONDARY_ANALYSIS_PROMPT_ID = "secondary_analysis_default"
SECONDARY_ANALYSIS_PROMPT_NAME = "Analyse secondaire"
TERTIARY_ANALYSIS_PROMPT_ID = "tertiary_analysis_default"
TERTIARY_ANALYSIS_PROMPT_NAME = "Analyse tertiaire"

DEFAULT_SECONDARY_ANALYSIS_CONFIG = {
    "enabled": False,
    "default_prompt_id": SECONDARY_ANALYSIS_PROMPT_ID,
    "auto_run_after_primary": True,
    "include_transcription": True,
    "include_weda_context": True,
    "include_result_1": True,
    "show_sent_message_2": True,
    "allow_manual_run": True,
}

DEFAULT_SECONDARY_ANALYSIS_PROMPT = """À partir de la transcription initiale, du contexte WEDA éventuel et du premier résultat produit, réalise une deuxième analyse complémentaire.

Règles :
- N’invente aucune information absente des sources.
- Signale les incertitudes.
- Signale les contradictions éventuelles entre la transcription, le contexte WEDA et le résultat 1.
- Ne répète pas inutilement le résultat 1.
- Produis uniquement les éléments utiles pour une relecture médicale.

CONTEXTE WEDA :
{{weda_context}}

TRANSCRIPTION INITIALE :
{{transcription}}

RÉSULTAT 1 :
{{result_1}}"""

DEFAULT_TERTIARY_ANALYSIS_CONFIG = {
    "enabled": False,
    "default_prompt_id": TERTIARY_ANALYSIS_PROMPT_ID,
    "auto_run_after_secondary": True,
    "include_transcription": True,
    "include_weda_context": True,
    "include_result_1": True,
    "include_result_2": True,
    "show_sent_message_3": True,
    "allow_manual_run": True,
}

DEFAULT_TERTIARY_ANALYSIS_PROMPT = """À partir de la transcription initiale, du contexte WEDA éventuel, du résultat 1 et du résultat 2, réalise une troisième analyse complémentaire.

Règles :
- N’invente aucune information absente des sources.
- Appuie-toi prioritairement sur le résultat 2 si celui-ci corrige ou complète le résultat 1.
- Signale les contradictions éventuelles entre les sources.
- Ne répète pas inutilement les résultats précédents.
- Produis uniquement les éléments utiles pour une relecture médicale.

CONTEXTE WEDA :
{{weda_context}}

TRANSCRIPTION INITIALE :
{{transcription}}

RÉSULTAT 1 :
{{result_1}}

RÉSULTAT 2 :
{{result_2}}"""

PROMPT_VARIABLE_RE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


def normalize_secondary_analysis_config(config: Mapping[str, object] | None) -> dict:
    normalized = dict(DEFAULT_SECONDARY_ANALYSIS_CONFIG)
    if isinstance(config, Mapping):
        normalized.update({key: value for key, value in config.items() if key in normalized})
    normalized["enabled"] = bool(normalized.get("enabled"))
    normalized["auto_run_after_primary"] = bool(normalized.get("auto_run_after_primary"))
    normalized["include_transcription"] = bool(normalized.get("include_transcription"))
    normalized["include_weda_context"] = bool(normalized.get("include_weda_context"))
    normalized["include_result_1"] = bool(normalized.get("include_result_1"))
    normalized["show_sent_message_2"] = bool(normalized.get("show_sent_message_2"))
    normalized["allow_manual_run"] = bool(normalized.get("allow_manual_run"))
    normalized["default_prompt_id"] = str(normalized.get("default_prompt_id") or SECONDARY_ANALYSIS_PROMPT_ID)
    return normalized


def normalize_tertiary_analysis_config(config: Mapping[str, object] | None) -> dict:
    normalized = dict(DEFAULT_TERTIARY_ANALYSIS_CONFIG)
    if isinstance(config, Mapping):
        normalized.update({key: value for key, value in config.items() if key in normalized})
    normalized["enabled"] = bool(normalized.get("enabled"))
    normalized["auto_run_after_secondary"] = bool(normalized.get("auto_run_after_secondary"))
    normalized["include_transcription"] = bool(normalized.get("include_transcription"))
    normalized["include_weda_context"] = bool(normalized.get("include_weda_context"))
    normalized["include_result_1"] = bool(normalized.get("include_result_1"))
    normalized["include_result_2"] = bool(normalized.get("include_result_2"))
    normalized["show_sent_message_3"] = bool(normalized.get("show_sent_message_3"))
    normalized["allow_manual_run"] = bool(normalized.get("allow_manual_run"))
    normalized["default_prompt_id"] = str(normalized.get("default_prompt_id") or TERTIARY_ANALYSIS_PROMPT_ID)
    return normalized


def build_secondary_prompt_variables(
    base_variables: Mapping[str, object],
    *,
    prompt_1_name: str = "",
    prompt_1_content: str = "",
    prompt_2_name: str = "",
    prompt_2_content: str = "",
    result_1: str = "",
) -> dict[str, str]:
    variables = {str(key): "" if value is None else str(value) for key, value in base_variables.items()}
    result = str(result_1 or "")
    variables.update(
        {
            "prompt_1_name": prompt_1_name or "",
            "prompt_1_content": prompt_1_content or "",
            "prompt_2_name": prompt_2_name or "",
            "prompt_2_content": prompt_2_content or "",
            "result_1": result,
            "lmstudio_result": result,
        }
    )
    return variables


def build_tertiary_prompt_variables(
    base_variables: Mapping[str, object],
    *,
    prompt_1_name: str = "",
    prompt_1_content: str = "",
    prompt_2_name: str = "",
    prompt_2_content: str = "",
    prompt_3_name: str = "",
    prompt_3_content: str = "",
    result_1: str = "",
    result_2: str = "",
) -> dict[str, str]:
    variables = build_secondary_prompt_variables(
        base_variables,
        prompt_1_name=prompt_1_name,
        prompt_1_content=prompt_1_content,
        prompt_2_name=prompt_2_name,
        prompt_2_content=prompt_2_content,
        result_1=result_1,
    )
    result = str(result_2 or "")
    variables.update(
        {
            "prompt_3_name": prompt_3_name or "",
            "prompt_3_content": prompt_3_content or "",
            "result_2": result,
            "lmstudio_result_2": result,
        }
    )
    return variables


def find_unresolved_variables(template: str, variables: Mapping[str, object]) -> list[str]:
    available = {str(key) for key in variables}
    found = []
    for name in PROMPT_VARIABLE_RE.findall(template or ""):
        if name not in available and name not in found:
            found.append(name)
    return found


def prompt_contains_variable(prompt_content: str, variable_name: str) -> bool:
    pattern = r"{{\s*" + re.escape(variable_name) + r"\s*}}"
    return re.search(pattern, prompt_content or "", flags=re.IGNORECASE) is not None


def append_missing_secondary_sections(prompt_content: str, message: str, variables: Mapping[str, str]) -> str:
    sections: list[tuple[str, str]] = []

    for variable_name, title in (
        ("current_date", "DATE DU JOUR"),
        ("patient_identity", "PATIENT"),
        ("weda_context", "CONTEXTE WEDA"),
        ("transcription", "TRANSCRIPTION INITIALE"),
        ("result_1", "RÉSULTAT 1"),
    ):
        value = str(variables.get(variable_name) or "").strip()
        if value and not prompt_contains_variable(prompt_content, variable_name):
            sections.append((title, value))

    if not sections:
        return message.strip()

    source_block = "\n\n".join(f"{title} :\n{content}" for title, content in sections)
    return (message.rstrip() + "\n\n---\nSOURCES POUR ANALYSE SECONDAIRE\n\n" + source_block).strip()


def append_missing_tertiary_sections(prompt_content: str, message: str, variables: Mapping[str, str]) -> str:
    sections: list[tuple[str, str]] = []

    for variable_name, title in (
        ("current_date", "DATE DU JOUR"),
        ("patient_identity", "PATIENT"),
        ("weda_context", "CONTEXTE WEDA"),
        ("transcription", "TRANSCRIPTION INITIALE"),
        ("result_1", "RÉSULTAT 1"),
        ("result_2", "RÉSULTAT 2"),
    ):
        value = str(variables.get(variable_name) or "").strip()
        if value and not prompt_contains_variable(prompt_content, variable_name):
            sections.append((title, value))

    if not sections:
        return message.strip()

    source_block = "\n\n".join(f"{title} :\n{content}" for title, content in sections)
    return (message.rstrip() + "\n\n---\nSOURCES POUR ANALYSE TERTIAIRE\n\n" + source_block).strip()
