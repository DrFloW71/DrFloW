from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser


DEFAULT_WHISPER_MODEL = "large-v3"
DEFAULT_WHISPER_LANGUAGE = "fr"
DEFAULT_WHISPER_DEVICE = "cuda"
DEFAULT_WHISPER_COMPUTE_TYPE = "float16"
DEFAULT_WHISPER_BEAM_SIZE = 5
DEFAULT_WHISPER_TEMPERATURE = 0.0

TRANSCRIPTION_WINDOW_SECONDS = 30
TRANSCRIPTION_OVERLAP_SECONDS = 2

MAX_DYNAMIC_PROMPT_CHARACTERS = 800
MAX_HOTWORDS = 80
MAX_HOTWORD_LENGTH = 60
MAX_HOTWORDS_CHARACTERS = 2000
MIN_VALIDATIONS_FOR_AUTOMATIC_CORRECTION = 3

DEFAULT_MEDICAL_WHISPER_PROMPT = (
    "Consultation de médecine générale en français entre un médecin et un patient. "
    "Transcription fidèle du dialogue médical : symptômes, évolution, négations, antécédents, "
    "traitements, posologies, allergies, examen clinique, résultats biologiques, dates, "
    "valeurs numériques et conseils donnés."
)

DEFAULT_PERMANENT_MEDICAL_HOTWORDS = (
    "hémoglobine glyquée",
    "NT-proBNP",
    "microalbuminurie",
    "créatininémie",
    "automesure tensionnelle",
    "anticoagulant",
    "frottis cervico-utérin",
    "auscultation cardio-pulmonaire",
)

GENERIC_HOTWORDS = {
    "patient",
    "consultation",
    "médecin",
    "traitement",
    "douleur",
    "maladie",
    "ordonnance",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)


def strip_html(value: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(str(value or ""))
        parser.close()
        text = " ".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return html.unescape(text)


def normalize_for_match(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def clean_weda_medical_context(value: str, *, max_characters: int = MAX_DYNAMIC_PROMPT_CHARACTERS) -> str:
    text = strip_html(value)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"https?://\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b(?:Patient|ID WEDA|PatDk|Naissance/âge|Naissance|Sexe|URL|Page)\s*:\s*[^\n]+",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b(?:imprimer|fermer|retour accueil|menu|déconnexion)\b", " ", text, flags=re.IGNORECASE)
    chunks = re.split(r"[\r\n]+|(?<=[.;])\s+", text)
    kept: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        cleaned = re.sub(r"\s+", " ", chunk).strip(" -–—;,.\t")
        if len(cleaned) < 3:
            continue
        key = normalize_for_match(cleaned)
        if key in seen:
            continue
        seen.add(key)
        kept.append(cleaned)
    result = ", ".join(kept)
    limit = max(0, int(max_characters))
    if limit and len(result) > limit:
        result = result[:limit].rsplit(" ", 1)[0].rstrip(" ,;.")
    return result


def build_dynamic_whisper_prompt(
    base_prompt: str,
    weda_context: str = "",
    *,
    include_weda_context: bool = True,
    max_dynamic_characters: int = MAX_DYNAMIC_PROMPT_CHARACTERS,
) -> tuple[str, str]:
    base = re.sub(r"\s+", " ", str(base_prompt or DEFAULT_MEDICAL_WHISPER_PROMPT)).strip()
    if not include_weda_context:
        return base, ""
    dynamic = clean_weda_medical_context(weda_context, max_characters=max_dynamic_characters)
    if not dynamic:
        return base, ""
    return f"{base}\n\nContexte patient possible : {dynamic}.", dynamic


def _category_priority(label: str) -> int:
    normalized = normalize_for_match(label)
    if any(word in normalized for word in ("medicament", "dci", "traitement")):
        return 0
    if "allerg" in normalized:
        return 1
    if any(word in normalized for word in ("antecedent", "patholog", "chronique")):
        return 2
    if any(word in normalized for word in ("specialiste", "chirurg", "intervention")):
        return 3
    if any(word in normalized for word in ("examen", "biolog", "dispositif")):
        return 4
    return 5


def extract_weda_hotwords(value: str) -> list[str]:
    text = strip_html(value).replace("\u00a0", " ")
    candidates: list[tuple[int, int, str]] = []
    order = 0
    for raw_line in re.split(r"[\r\n]+", text):
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        label, separator, content = line.partition(":")
        if separator and normalize_for_match(label) in {
            "patient",
            "id weda",
            "patdk",
            "naissance/age",
            "naissance",
            "sexe",
            "url",
            "page",
        }:
            continue
        priority = _category_priority(label) if separator else 5
        source = content if separator else line
        for raw_term in re.split(r"[,;|•]+", source):
            term = re.sub(r"\([^)]*\b(?:né|née|date|depuis)\b[^)]*\)", "", raw_term, flags=re.IGNORECASE)
            term = re.sub(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", " ", term)
            term = re.sub(r"\s+", " ", term).strip(" -–—.;:")
            words = term.split()
            normalized = normalize_for_match(term)
            if not term or len(term) > MAX_HOTWORD_LENGTH or len(words) > 7:
                continue
            if normalized in {normalize_for_match(word) for word in GENERIC_HOTWORDS}:
                continue
            if len(term) < 3 or term.isdigit():
                continue
            candidates.append((priority, order, term))
            order += 1
    candidates.sort(key=lambda item: (item[0], item[1]))
    return _deduplicate_terms([item[2] for item in candidates])


def parse_permanent_hotwords(value) -> list[str]:
    if isinstance(value, str):
        terms = re.split(r"[\r\n,;]+", value)
    elif isinstance(value, (list, tuple, set)):
        terms = [str(item) for item in value]
    else:
        terms = []
    return _deduplicate_terms([re.sub(r"\s+", " ", term).strip() for term in terms if str(term).strip()])


def _deduplicate_terms(terms: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for term in terms:
        cleaned = str(term or "").strip()
        key = normalize_for_match(cleaned)
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


@dataclass(frozen=True)
class HotwordBundle:
    permanent: tuple[str, ...]
    weda: tuple[str, ...]
    corrections: tuple[str, ...]
    final: tuple[str, ...]

    @property
    def faster_whisper_value(self) -> str:
        return ", ".join(self.final)


def build_hotword_bundle(
    permanent,
    weda_context: str = "",
    corrections=(),
    *,
    include_weda: bool = True,
    max_hotwords: int = MAX_HOTWORDS,
    max_hotword_length: int = MAX_HOTWORD_LENGTH,
    max_characters: int = MAX_HOTWORDS_CHARACTERS,
) -> HotwordBundle:
    permanent_terms = parse_permanent_hotwords(permanent)
    weda_terms = extract_weda_hotwords(weda_context) if include_weda else []
    correction_terms = parse_permanent_hotwords(corrections)
    final: list[str] = []
    seen: set[str] = set()
    characters = 0
    for term in [*permanent_terms, *weda_terms, *correction_terms]:
        cleaned = term[: max(1, int(max_hotword_length))].strip()
        key = normalize_for_match(cleaned)
        if not cleaned or key in seen:
            continue
        added = len(cleaned) + (2 if final else 0)
        if len(final) >= max(0, int(max_hotwords)) or characters + added > max(0, int(max_characters)):
            break
        seen.add(key)
        final.append(cleaned)
        characters += added
    return HotwordBundle(tuple(permanent_terms), tuple(weda_terms), tuple(correction_terms), tuple(final))
