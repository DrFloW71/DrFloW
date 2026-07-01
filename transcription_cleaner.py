from __future__ import annotations

import re
from collections.abc import Iterable


WHISPER_MEDICAL_INITIAL_PROMPT = (
    "Consultation de médecine générale en français. Vocabulaire possible : médecin, patient, "
    "symptômes, traitements, posologies, tension artérielle, saturation, température, douleur, "
    "fièvre, toux, dyspnée, diarrhée, vomissements, HTA, diabète, ECG, CRP, HbA1c, DFG, SpO2."
)

DEFAULT_BLOCKED_LINE_PATTERNS = [
    "Sous-titrage",
    "Société Radio-Canada",
    "ST' 501",
    "Transcription fidèle",
    "mauvais micro",
    "Segment sans texte détecté",
    "silence ou mauvais micro",
    "Merci d’avoir regardé",
    "N’oubliez pas de vous abonner",
    "Thanks for watching",
    "subtitle",
    "subtitles",
    "caption",
    "captions",
]

BUILTIN_ASR_ARTIFACT_PATTERNS = [
    "il y a des technologies",
]

TECHNICAL_BLOCK_RE = re.compile(r"\[\[Segment[\s\S]*?\]\]", re.IGNORECASE)
RMS_PEAK_RE = re.compile(r".*(RMS\s*=|peak\s*=|dur[ée]e\s*=).*", re.IGNORECASE)
SPACE_RE = re.compile(r"[ \t]+")
MULTI_BLANK_RE = re.compile(r"\n{3,}")
BLOOD_PRESSURE_RE = re.compile(r"\b([12]?\d{2})\s*,\s*(\d{2})\b")


def clean_transcription_text(raw_text: str, config: dict | None = None) -> str:
    cleaning_config = config if isinstance(config, dict) else {}
    if cleaning_config.get("enabled", True) is False:
        return str(raw_text or "").strip()

    text = str(raw_text or "").replace("\r", "\n")
    if cleaning_config.get("remove_technical_blocks", True):
        text = TECHNICAL_BLOCK_RE.sub("\n", text)

    blocked_patterns: list[str] = []
    if cleaning_config.get("remove_known_asr_artifacts", True):
        blocked_patterns = list(DEFAULT_BLOCKED_LINE_PATTERNS)
        configured_patterns = cleaning_config.get("blocked_line_patterns")
        if isinstance(configured_patterns, Iterable) and not isinstance(configured_patterns, (str, bytes)):
            blocked_patterns.extend(str(pattern) for pattern in configured_patterns if str(pattern or "").strip())
        blocked_patterns.extend(BUILTIN_ASR_ARTIFACT_PATTERNS)

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = SPACE_RE.sub(" ", raw_line).strip()
        if not line:
            continue
        if should_drop_transcription_line(line, blocked_patterns):
            continue
        line = lightly_normalize_medical_line(line, cleaning_config)
        if not line:
            continue
        lines.append(line)

    cleaned = "\n".join(lines).strip()
    cleaned = MULTI_BLANK_RE.sub("\n\n", cleaned)
    return cleaned


def should_drop_transcription_line(line: str, blocked_patterns: list[str]) -> bool:
    if RMS_PEAK_RE.match(line):
        return True

    normalized = line.casefold()
    return any(pattern.casefold() in normalized for pattern in blocked_patterns if pattern)


def lightly_normalize_medical_line(line: str, config: dict | None = None) -> str:
    cleaning_config = config if isinstance(config, dict) else {}
    text = SPACE_RE.sub(" ", str(line or "")).strip()
    text = re.sub(r"\bGastro(-|\s)?ent[ée]rite,\s+virale\b", "Gastroentérite virale", text)
    text = re.sub(r"\bgastro(-|\s)?ent[ée]rite,\s+virale\b", "gastroentérite virale", text, flags=re.IGNORECASE)
    if cleaning_config.get("normalize_blood_pressure", True):
        text = normalize_blood_pressure(text)
    if re.search(r"\b(gastro|diarrh[ée]e|naus[ée]e|vomissements?)\b", text, re.IGNORECASE):
        text = re.sub(r"\bvomissement\b", "vomissements", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def normalize_blood_pressure(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        systolic = int(match.group(1))
        diastolic = int(match.group(2))
        if 80 <= systolic <= 260 and 30 <= diastolic <= 160:
            return f"{systolic}/{diastolic}"
        return match.group(0)

    return BLOOD_PRESSURE_RE.sub(replace, text)
