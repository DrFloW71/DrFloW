from __future__ import annotations

import csv
import html
import io
import json
import re
import tempfile
import threading
import time
import tkinter as tk
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    pystray = None
    Image = None
    ImageDraw = None
    ImageFont = None

from audio_recorder import AudioRecorder, PushToTalkRecorder, list_input_devices
from clipboard_tools import clear_text_clipboard, copy_rich_text_to_clipboard, copy_text_to_clipboard, read_text_from_clipboard
from debug_logger import DebugLogger
from diagnostic_manager import run_drflow_diagnostics, sanitized_diagnostic_report
from history_manager import HistoryManager
from lmstudio_client import LmStudioCancelled, LmStudioClient, fetch_lmstudio_model_context
from local_server import LocalServer
from patient_safety import (
    PATIENT_SAFETY_BLOCKED,
    PATIENT_SAFETY_OK,
    evaluate_patient_context,
    normalize_patient_id,
    patient_ids_match,
)
from pdf_export_manager import PdfExportManager
from pdf_fill_manager import PdfFillManager
from pdf_schema_builder import (
    build_json_schema,
    build_preview_rows,
    parse_json_object,
    parse_json_object_result,
    validate_pdf_field_values,
)
from pdf_template_manager import PdfTemplateManager
from prompt_manager import PromptManager
from prompt_quality import PromptVersionStore, QualityMetricsStore, content_hash, unified_text_diff
from rich_text_formatter import RichTextPayload, combine_weda_rich_text_payloads, format_weda_rich_text
from secondary_analysis import (
    DEFAULT_SECONDARY_ANALYSIS_CONFIG,
    DEFAULT_SECONDARY_ANALYSIS_PROMPT,
    DEFAULT_TERTIARY_ANALYSIS_CONFIG,
    DEFAULT_TERTIARY_ANALYSIS_PROMPT,
    SECONDARY_ANALYSIS_PROMPT_ID,
    SECONDARY_ANALYSIS_PROMPT_NAME,
    TERTIARY_ANALYSIS_PROMPT_ID,
    TERTIARY_ANALYSIS_PROMPT_NAME,
    append_missing_secondary_sections,
    append_missing_tertiary_sections,
    build_secondary_prompt_variables,
    build_tertiary_prompt_variables,
    find_unresolved_variables,
    normalize_secondary_analysis_config,
    normalize_tertiary_analysis_config,
)
from segment_manager import SegmentedDictationSession
from medical_transcription import (
    DEFAULT_MEDICAL_WHISPER_PROMPT,
    DEFAULT_PERMANENT_MEDICAL_HOTWORDS,
    MAX_DYNAMIC_PROMPT_CHARACTERS,
    MAX_HOTWORDS,
    MAX_HOTWORDS_CHARACTERS,
    MAX_HOTWORD_LENGTH,
    MIN_VALIDATIONS_FOR_AUTOMATIC_CORRECTION,
    TRANSCRIPTION_OVERLAP_SECONDS,
    TRANSCRIPTION_WINDOW_SECONDS,
    build_dynamic_whisper_prompt,
    build_hotword_bundle,
    parse_permanent_hotwords,
)
from progressive_transcription import deduplicate_transcription_overlap
from stt_engine_manager import (
    FASTER_WHISPER_ENGINE_ID,
    QWEN3_ASR_ENGINE_ID,
    STT_ENGINE_DEVICE_CHOICES,
    STT_ENGINE_LABELS,
    STT_ENGINE_MODEL_CHOICES,
    STT_ENGINE_RUNTIME_CHOICES,
    STTEngineManager,
    VOXTRAL_ENGINE_ID,
    backend_config_for,
    ensure_stt_config,
    format_stt_text,
    normalize_engine_id,
)
from transcriber import Transcriber
from transcription_cleaner import clean_transcription_text
from transcription_draft import TranscriptionDraftStore
from transcription_corrections import CorrectionStore, format_correction_review, propose_corrections
from weda_context_manager import WedaContextManager
from weda_import_manager import WedaImportManager
from whisper_model_manager import WhisperModelManager, WhisperSettings, canonical_french_whisper_model_name


BASE_DIR = Path(__file__).resolve().parent
APP_NAME = "DrFloW"
APP_SUBTITLE = "Assistant local de consultation médicale :)"
APP_WINDOW_TITLE = f"{APP_NAME} - {APP_SUBTITLE}"
DEFAULT_WHISPER_INITIAL_PROMPT = DEFAULT_MEDICAL_WHISPER_PROMPT
ABBREVIATIONS_PATH = BASE_DIR / "abbreviations.csv"
MESSAGE_ATTACHMENT_MAX_CHARS_PER_FILE = 30000
MESSAGE_ATTACHMENT_MAX_TOTAL_CHARS = 90000
LMSTUDIO_MAIN_SPINNER_KEY = "main"
LMSTUDIO_RESULT_RETRY_SPINNER_KEY = "main_retry"
LMSTUDIO_SECONDARY_RETRY_SPINNER_KEY = "secondary_retry"
LMSTUDIO_TERTIARY_RETRY_SPINNER_KEY = "tertiary_retry"
PDF_FILL_SPINNER_KEY = "pdf_fill"
LMSTUDIO_SPINNER_FRAMES = ("◐", "◓", "◑", "◒")
LMSTUDIO_CONTEXT_ESTIMATED_CHARS_PER_TOKEN = 3.0
LMSTUDIO_CONTEXT_SAFETY_MARGIN_TOKENS = 512
LMSTUDIO_CONTEXT_RESPONSE_RESERVE_TOKENS = 2048
LMSTUDIO_CONTEXT_MIN_INPUT_TOKENS = 512
TEXT_SEARCH_MATCH_TAG = "drflow_search_match"
TEXT_SEARCH_CURRENT_TAG = "drflow_search_current"
LEGACY_TRANSCRIPTION_TAB_LABELS = {
    "Transcription brute Whisper",
    "Transcription corrigée localement",
}
DICTATION_TRANSCRIPTION_FLUSH_TIMEOUT_SECONDS = 180.0
FLY_DICTATION_CLIPBOARD_RESTORE_DELAY_MS = 150
WEDA_CONTEXT_REFRESH_TIMEOUT_MS = 30000
MESSAGE_ATTACHMENT_TEXT_SUFFIXES = {
    ".csv",
    ".json",
    ".log",
    ".md",
    ".rtf",
    ".text",
    ".txt",
    ".xml",
}
SOURCE_USAGE_GUIDANCE = (
    "Mode d’emploi des sources :\n"
    "- La TRANSCRIPTION DU JOUR est la source principale de l’oral dicté ou échangé aujourd’hui.\n"
    "- Le CONTEXTE WEDA correspond aux dernières consultations et aux données médicales connues du dossier "
    "(antécédents, traitements, examens, courriers, éléments de suivi).\n"
    "- Le contexte ne doit pas modifier la transcription fidèle. Il sert uniquement à préciser une information, "
    "lever une ambiguïté, retrouver un terme médical, ou rédiger un document médical cohérent.\n"
    "- En cas de contradiction, privilégier la transcription du jour pour les éléments actuels et éviter toute invention."
)
DEFAULT_MESSAGE_COMPOSITION_CONFIG = {
    "include_prompt": True,
    "include_weda_context": True,
    "include_transcription": True,
}
DEFAULT_MEDICAL_TRANSCRIPTION_CONFIG = {
    "include_weda_context_in_whisper_prompt": True,
    "use_dynamic_weda_hotwords": True,
    "apply_validated_corrections": False,
    "max_dynamic_prompt_characters": MAX_DYNAMIC_PROMPT_CHARACTERS,
    "max_hotwords": MAX_HOTWORDS,
    "max_hotword_length": MAX_HOTWORD_LENGTH,
    "max_hotwords_characters": MAX_HOTWORDS_CHARACTERS,
    "min_validations_for_automatic_correction": MIN_VALIDATIONS_FOR_AUTOMATIC_CORRECTION,
    "permanent_hotwords": list(DEFAULT_PERMANENT_MEDICAL_HOTWORDS),
}


def migrate_main_notebook_tab_order(labels) -> list[str]:
    migrated_order = []
    for label in labels:
        normalized_label = str(label)
        if normalized_label in LEGACY_TRANSCRIPTION_TAB_LABELS:
            normalized_label = "Transcription"
        if normalized_label not in migrated_order:
            migrated_order.append(normalized_label)
    return migrated_order


DEFAULT_PDF_FORM_FILL_PROMPT = """Tu dois remplir au mieux les champs d’un PDF médical structuré à partir des seules informations disponibles.

Objectif :
- Produire uniquement un objet JSON valide.
- Les noms, libellés et descriptions des champs PDF donnent les consignes de remplissage.
- N’invente aucune information absente de la source PDF sélectionnée.
- Si une information est absente, incertaine ou ambiguë, omets le champ ou laisse une chaîne vide.
- Pour les cases à cocher, utilise true uniquement si la case doit clairement être cochée ; sinon omets le champ ou utilise false.
- Respecte exactement les noms techniques des champs.
- Ne mets aucun commentaire hors JSON.

SOURCE PDF SÉLECTIONNÉE :
{{lmstudio_result}}

CHAMPS PDF DISPONIBLES :
{{pdf_fields}}

SCHÉMA JSON ATTENDU :
{{pdf_schema}}"""
DOCUMENT_NOW_PROMPT_ID = "document_now_default"
DOCUMENT_NOW_PROMPT_NAME = "Document maintenant"
DOCUMENT_NOW_SPINNER_KEY = "document_now"
DEFAULT_DOCUMENT_NOW_PROMPT = """Tu rédiges un document médical intermédiaire pendant une consultation en cours.

Utilise uniquement le snapshot de transcription ci-dessous, créé au checkpoint {{checkpoint_id}}.
Ce document intermédiaire ne doit pas conclure la consultation complète : la transcription principale continuera après ce snapshot.
N’invente aucune information absente des sources.
Rédige un document directement utilisable, clair, concis et structuré selon le besoin médical implicite.
Si le snapshot est insuffisant, indique seulement les éléments disponibles et ce qui reste à préciser.

DATE :
{{date_today}}

PATIENT :
{{patient_details}}

CONTEXTE WEDA :
{{weda_context}}

SNAPSHOT DE TRANSCRIPTION :
{{snapshot_transcription}}"""
DEFAULT_DOCUMENT_NOW_PROMPT_PREFIX = ""
PDF_SOURCE_CHOICES = (
    "Contexte + transcription",
    "Transcription seule",
    "Résultat 1",
    "Résultat 2",
    "Résultat 3",
    "Document maintenant",
    "Résultat 1 + Résultat 2",
    "Résultat 1 + Résultat 2 + Résultat 3",
)
RESULT_DESTINATION_CHOICES = (
    "WEDA consultation",
    "WEDA courrier",
    "Presse-papiers",
    "PDF structuré",
)
RICH_RESULT_BOLD_TAG = "drflow_rich_bold"
RICH_RESULT_UNDERLINE_TAG = "drflow_rich_underline"
RICH_RESULT_ITALIC_TAG = "drflow_rich_italic"
RICH_RESULT_STRIKE_TAG = "drflow_rich_strike"
RICH_RESULT_TK_TAGS = (
    RICH_RESULT_BOLD_TAG,
    RICH_RESULT_UNDERLINE_TAG,
    RICH_RESULT_ITALIC_TAG,
    RICH_RESULT_STRIKE_TAG,
)
RICH_RESULT_HTML_TO_TK_TAG = {
    "strong": RICH_RESULT_BOLD_TAG,
    "b": RICH_RESULT_BOLD_TAG,
    "u": RICH_RESULT_UNDERLINE_TAG,
    "em": RICH_RESULT_ITALIC_TAG,
    "i": RICH_RESULT_ITALIC_TAG,
    "s": RICH_RESULT_STRIKE_TAG,
    "strike": RICH_RESULT_STRIKE_TAG,
    "del": RICH_RESULT_STRIKE_TAG,
}
RICH_RESULT_TK_TAG_TO_HTML = (
    (RICH_RESULT_BOLD_TAG, "strong"),
    (RICH_RESULT_UNDERLINE_TAG, "u"),
    (RICH_RESULT_ITALIC_TAG, "em"),
    (RICH_RESULT_STRIKE_TAG, "s"),
)
WHISPER_MODEL_CHOICES = (
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3",
    "large-v3-turbo",
    "turbo",
)
WHISPER_DEVICE_CHOICES = ("cpu", "cuda")
WHISPER_COMPUTE_CHOICES = ("int8", "int8_float16", "float16", "float32")
DEFAULT_FLY_WHISPER_INITIAL_PROMPT = (
    "Dictée médicale courte en français. Respecter les termes médicaux, médicaments, posologies, "
    "unités et abréviations usuelles. Ne pas traduire. Ne pas produire d’anglais."
)
CUDA_RUNTIME_ERROR_PATTERNS = (
    "cublas",
    "cudnn",
    "cufft",
    "curand",
    "cusolver",
    "cusparse",
    "cudart",
    "cuda driver",
    "cuda runtime",
)
MATERIAL_DARK_THEME = {
    "background": "#06111f",
    "surface": "#0b1b2f",
    "surface_low": "#0f2238",
    "surface_high": "#14324e",
    "surface_hover": "#1b4366",
    "primary": "#7dd3fc",
    "primary_high": "#38bdf8",
    "primary_container": "#0f4c75",
    "on_primary": "#001d35",
    "outline": "#2a4f70",
    "outline_soft": "#1d3a56",
    "text": "#e5f2ff",
    "muted_text": "#a8bdd4",
    "disabled_text": "#5e748c",
    "selection": "#1e6091",
    "success": "#34d399",
    "warning": "#fbbf24",
    "danger": "#f87171",
    "danger_container": "#6f1d2a",
}


class RichHtmlToTkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.active_tags: list[str] = []
        self.segments: list[tuple[str, tuple[str, ...]]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        name = tag.lower()
        if name == "br":
            self._append_text("\n")
            return

        mapped = RICH_RESULT_HTML_TO_TK_TAG.get(name)
        if mapped:
            self.active_tags.append(mapped)

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag.lower() == "br":
            self._append_text("\n")

    def handle_endtag(self, tag: str) -> None:
        mapped = RICH_RESULT_HTML_TO_TK_TAG.get(tag.lower())
        if not mapped:
            return

        for index in range(len(self.active_tags) - 1, -1, -1):
            if self.active_tags[index] == mapped:
                del self.active_tags[index]
                break

    def handle_data(self, data: str) -> None:
        self._append_text(data)

    def _append_text(self, value: str) -> None:
        if value:
            self.segments.append((value, tuple(dict.fromkeys(self.active_tags))))


def load_json(path: Path, fallback: dict | list):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def save_json(path: Path, data: dict | list) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_abbreviations_csv(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    entries: list[tuple[str, str]] = []
    errors: list[str] = []
    reader = csv.reader(io.StringIO(text or ""))
    for line_number, row in enumerate(reader, start=1):
        if not row or not any(str(cell).strip() for cell in row):
            continue
        first = str(row[0]).strip()
        if first.startswith("#"):
            continue
        if len(row) >= 2 and first.lower() == "find" and str(row[1]).strip().lower() == "replace":
            continue
        if len(row) < 2:
            errors.append(f"Ligne {line_number}: format attendu find,replace")
            continue
        find = first
        replace = str(row[1]).strip()
        if not find or not replace:
            errors.append(f"Ligne {line_number}: find et replace doivent être non vides")
            continue
        entries.append((find, replace))
    return entries, errors


def apply_safe_abbreviation_substitutions_to_text(text: str, entries: list[tuple[str, str]]) -> tuple[str, int]:
    result = text or ""
    count = 0
    for find, replace in sorted(entries, key=lambda item: len(item[0]), reverse=True):
        pattern = re.compile(r"(?<!\w)" + re.escape(find) + r"(?!\w)", flags=re.IGNORECASE)

        def repl(match: re.Match[str]) -> str:
            nonlocal count
            if match.group(0) == replace:
                return match.group(0)
            count += 1
            return replace

        result = pattern.sub(repl, result)
    return result, count


def truncate_message_attachment_text(text: str, max_chars: int = MESSAGE_ATTACHMENT_MAX_CHARS_PER_FILE) -> tuple[str, bool]:
    clean = normalize_attachment_text(text)
    if len(clean) <= max_chars:
        return clean, False
    head_length = int(max_chars * 0.7)
    tail_length = max_chars - head_length
    return (
        clean[:head_length].rstrip()
        + "\n\n[... fichier tronqué avant envoi à Gemma ...]\n\n"
        + clean[-tail_length:].lstrip()
    ), True


def normalize_attachment_text(text: str) -> str:
    return (
        str(text or "")
        .replace("\r", "\n")
        .replace("\u00a0", " ")
        .replace("\x00", "")
        .replace("\t", " ")
        .strip()
    )


def decode_text_attachment_bytes(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_pdf_attachment_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise RuntimeError("La bibliothèque pypdf est manquante pour lire les PDF.") from exc

    reader = PdfReader(str(path))
    page_texts = []
    for page_index, page in enumerate(reader.pages, start=1):
        text = normalize_attachment_text(page.extract_text() or "")
        if text:
            page_texts.append(f"Page {page_index}\n{text}")
    return "\n\n".join(page_texts).strip()


def read_message_attachment_file(path: Path) -> dict:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = extract_pdf_attachment_text(path)
        kind = "PDF"
    elif suffix in MESSAGE_ATTACHMENT_TEXT_SUFFIXES:
        text = decode_text_attachment_bytes(path.read_bytes())
        kind = "texte"
    else:
        raw = path.read_bytes()
        text = decode_text_attachment_bytes(raw)
        if "\ufffd" in text[:2000]:
            raise RuntimeError("format non supporté ou fichier non textuel")
        kind = "texte"

    clean, truncated = truncate_message_attachment_text(text)
    if not clean:
        raise RuntimeError("aucun texte exploitable extrait")
    return {
        "path": str(path),
        "name": path.name,
        "kind": kind,
        "text": clean,
        "chars": len(clean),
        "truncated": truncated,
    }


def is_cuda_runtime_error(error: Exception | str) -> bool:
    message = str(error or "").casefold()
    return any(pattern in message for pattern in CUDA_RUNTIME_ERROR_PATTERNS)


@dataclass
class DocumentNowSnapshot:
    id: str
    created_at: str
    transcript_text: str
    transcript_duration_seconds: float | None
    transcript_segment_count: int | None
    weda_context: str | None
    patient_details: str | None
    date_today: str
    document_type: str | None
    prompt_id: str | None
    prompt_name: str | None
    prompt_content: str | None
    sent_message: str | None
    result: str | None
    status: str
    error: str | None


class AssistantApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.base_window_title = APP_WINDOW_TITLE
        self.root.title(self.base_window_title)
        self.main_thread_id = threading.get_ident()
        self.config = load_json(BASE_DIR / "config.json", {})
        self.ensure_stt_config()
        self.ensure_medical_transcription_config()
        self.ensure_message_composition_config()
        self.ensure_pdf_config()
        self.ensure_secondary_analysis_config()
        self.ensure_tertiary_analysis_config()
        self.root.geometry(self.get_saved_window_geometry())
        self.configure_material_theme()
        self.data_dir = BASE_DIR / "data"
        self.prompt_version_store = PromptVersionStore(self.data_dir / "prompt_versions.jsonl")
        self.quality_metrics_store = QualityMetricsStore(self.data_dir / "quality_metrics.jsonl")

        def version_callback(action, prompt):
            self.prompt_version_store.record(prompt, source=action)

        self.prompt_manager = PromptManager(BASE_DIR / "prompts.json", on_change=version_callback)
        self.ensure_pdf_form_fill_prompt()
        self.ensure_secondary_analysis_prompt()
        self.ensure_tertiary_analysis_prompt()
        self.ensure_document_now_prompt()
        self.whisper_initial_prompt_manager = PromptManager(
            BASE_DIR / "whisper_initial_prompts.json",
            on_change=version_callback,
        )
        self.ensure_whisper_initial_prompts()
        self.prompt_version_store.snapshot(self.prompt_manager.list_prompts(), source="startup")
        self.prompt_version_store.snapshot(self.whisper_initial_prompt_manager.list_prompts(), source="startup_whisper")
        pdf_config = self.config.get("pdf", {})
        self.pdf_template_manager = PdfTemplateManager(self.resolve_app_path(pdf_config.get("templates_dir"), "data/pdf_templates"))
        self.pdf_fill_manager = PdfFillManager()
        self.pdf_export_manager = PdfExportManager(self.resolve_app_path(pdf_config.get("outputs_dir"), "data/pdf_outputs"))
        self.context_manager = WedaContextManager(self.data_dir / "weda_context.json")
        self.import_manager = WedaImportManager(self.data_dir / "import_request.json")
        self.rich_result_payloads: dict[str, RichTextPayload] = {}
        self.result_patient_bindings: dict[str, dict] = {}
        self.pending_result_patient_bindings: dict[str, dict] = {}
        self.generated_result_originals: dict[str, str] = {}
        self.result_generation_metadata: dict[str, dict] = {}
        self.debug_logger = DebugLogger(self.data_dir / "debug.log.jsonl")
        self.history_manager = HistoryManager(
            self.data_dir / "history.jsonl",
            enabled=bool(self.config.get("ui", {}).get("save_history", True)),
        )
        self.transcription_draft_store = TranscriptionDraftStore(self.data_dir / "last_transcription.json")
        self.correction_store = CorrectionStore(self.data_dir / "transcription_corrections.json")
        self.model_manager = WhisperModelManager()
        self.stt_engine_manager = STTEngineManager(self.model_manager)
        self.transcriber = Transcriber(self.model_manager, self.get_stt_settings, stt_manager=self.stt_engine_manager)
        self.session: SegmentedDictationSession | None = None
        self.server: LocalServer | None = None
        self.prompt_name_to_id: dict[str, str] = {}
        self.secondary_prompt_name_to_id: dict[str, str] = {}
        self.tertiary_prompt_name_to_id: dict[str, str] = {}
        self.document_now_prompt_name_to_id: dict[str, str] = {}
        self.pdf_prompt_name_to_id: dict[str, str] = {}
        self.pdf_template_name_to_id: dict[str, str] = {}
        self.whisper_initial_prompt_name_to_id: dict[str, str] = {}
        self._window_geometry_save_job = None
        self._message_refresh_job = None
        self._secondary_message_refresh_job = None
        self._tertiary_message_refresh_job = None
        self._document_now_message_refresh_job = None
        self.message_attachments: list[dict] = []
        self._message_source_widgets = []
        self._secondary_message_source_widgets = []
        self._tertiary_message_source_widgets = []
        self._document_now_message_source_widgets = []
        self.secondary_running = False
        self.tertiary_running = False
        self.document_now_running = False
        self.document_now_snapshots: dict[str, DocumentNowSnapshot] = {}
        self.document_now_current_snapshot: DocumentNowSnapshot | None = None
        self.document_now_pending_checkpoints: dict[str, dict] = {}
        self._weda_context_refresh_lock = threading.Lock()
        self.weda_context_refresh_job: dict | None = None
        self._document_now_connector_lock = threading.Lock()
        self.document_now_connector_job: dict | None = None
        self._connector_lock = threading.Lock()
        self.connector_job: dict | None = None
        self.dictation_run_id = 0
        self._recording_indicator_active = False
        self._recording_indicator_source = ""
        self.tray_icon = None
        self.tray_thread: threading.Thread | None = None
        self.tray_hidden = False
        self.tray_available = False
        self.tray_images: dict[str, object] = {}
        self._closing = False
        self.last_stt_result: dict = {}
        self.last_whisper_diagnostics: dict = {}
        self.pending_transcription_corrections = []
        self.last_stt_audio_path = ""
        self.stt_benchmark_results: list[dict] = []
        self.lmstudio_spinner_vars: dict[str, tk.StringVar] = {}
        self.lmstudio_spinner_jobs: dict[str, str] = {}
        self.lmstudio_spinner_frame_indexes: dict[str, int] = {}
        self.lmstudio_context_window_tokens = 0
        self.lmstudio_context_window_model = ""
        self.lmstudio_context_window_source = ""
        self.active_lmstudio_requests: dict[str, dict] = {}
        self._active_lmstudio_requests_lock = threading.Lock()
        self._lmstudio_progress_job = None
        self.diagnostic_window: tk.Toplevel | None = None
        self.quality_window: tk.Toplevel | None = None
        self._main_notebook_drag_index: int | None = None
        self._main_notebook_drag_active = False
        self._main_notebook_drag_start_x = 0
        self._main_notebook_drag_start_y = 0

        whisper_config = self.config.get("whisper", {})
        stt_config = self.config.get("stt", {})
        active_stt_engine = normalize_engine_id(stt_config.get("default_engine") or FASTER_WHISPER_ENGINE_ID)
        active_stt_backend_config = backend_config_for(self.config, active_stt_engine)
        connector_config = self.config.get("connector", {})
        fly_dictation_config = self.config.get("fly_dictation", {})
        message_composition_config = self.config.get("message_composition", {})
        benchmark_engines_config = stt_config.get("benchmark_engines", {})
        if not isinstance(benchmark_engines_config, dict):
            benchmark_engines_config = {}
        result_destination = str(self.config.get("ui", {}).get("result_destination") or "WEDA consultation")
        if result_destination not in RESULT_DESTINATION_CHOICES:
            result_destination = "WEDA consultation"
        pdf_source = str(self.config.get("pdf", {}).get("preferred_source") or "Résultat 1 + Résultat 2")
        if pdf_source not in PDF_SOURCE_CHOICES:
            pdf_source = "Résultat 1 + Résultat 2"
        self.model_var = tk.StringVar(
            value=canonical_french_whisper_model_name(whisper_config.get("default_model") or "medium")
        )
        self.device_var = tk.StringVar(value=str(whisper_config.get("device") or "cpu"))
        self.compute_var = tk.StringVar(value=str(whisper_config.get("compute_type") or "int8"))
        self.stt_engine_var = tk.StringVar(value=STT_ENGINE_LABELS.get(active_stt_engine, STT_ENGINE_LABELS[FASTER_WHISPER_ENGINE_ID]))
        self.stt_model_var = tk.StringVar(value=str(active_stt_backend_config.get("model") or "medium"))
        self.stt_runtime_var = tk.StringVar(value=str(active_stt_backend_config.get("runtime") or "python"))
        self.stt_device_var = tk.StringVar(value=str(active_stt_backend_config.get("device") or "cpu"))
        self.stt_external_cli_var = tk.StringVar(value=str(active_stt_backend_config.get("external_cli_command") or ""))
        self.stt_server_url_var = tk.StringVar(value=str(active_stt_backend_config.get("server_url") or ""))
        self.stt_allow_experimental_var = tk.BooleanVar(value=bool(stt_config.get("allow_experimental_engines", True)))
        self.stt_keep_audio_var = tk.BooleanVar(value=bool(stt_config.get("keep_audio_for_benchmark", False)))
        self.stt_auto_fallback_var = tk.BooleanVar(value=bool(stt_config.get("auto_fallback_to_faster_whisper", True)))
        self.stt_show_warnings_var = tk.BooleanVar(value=bool(stt_config.get("show_engine_warnings", True)))
        self.stt_compare_faster_var = tk.BooleanVar(value=bool(benchmark_engines_config.get(FASTER_WHISPER_ENGINE_ID, True)))
        self.stt_compare_qwen_var = tk.BooleanVar(value=bool(benchmark_engines_config.get(QWEN3_ASR_ENGINE_ID, False)))
        self.stt_compare_voxtral_var = tk.BooleanVar(value=bool(benchmark_engines_config.get(VOXTRAL_ENGINE_ID, False)))
        self.micro_device_options = list_input_devices()
        self.micro_device_values = {label: value for label, value in self.micro_device_options}
        self.micro_device_var = tk.StringVar(
            value=self.micro_device_label_for_value(str(whisper_config.get("input_device") or ""))
        )
        self.prompt_var = tk.StringVar(value="")
        secondary_config = normalize_secondary_analysis_config(self.config.get("secondary_analysis", {}))
        tertiary_config = normalize_tertiary_analysis_config(self.config.get("tertiary_analysis", {}))
        self.secondary_enabled_var = tk.BooleanVar(value=bool(secondary_config.get("enabled")))
        self.secondary_prompt_var = tk.StringVar(value="")
        self.tertiary_enabled_var = tk.BooleanVar(value=bool(tertiary_config.get("enabled")))
        self.tertiary_prompt_var = tk.StringVar(value="")
        self.document_now_prompt_var = tk.StringVar(value="")
        self.whisper_initial_prompt_var = tk.StringVar(value="")
        medical_transcription_config = self.config.get("medical_transcription", {})
        self.whisper_include_weda_context_var = tk.BooleanVar(
            value=bool(medical_transcription_config.get("include_weda_context_in_whisper_prompt", True))
        )
        self.whisper_use_dynamic_hotwords_var = tk.BooleanVar(
            value=bool(medical_transcription_config.get("use_dynamic_weda_hotwords", True))
        )
        self.whisper_apply_corrections_var = tk.BooleanVar(
            value=bool(medical_transcription_config.get("apply_validated_corrections", False))
        )
        self.include_prompt_var = tk.BooleanVar(value=bool(message_composition_config.get("include_prompt", True)))
        self.include_context_var = tk.BooleanVar(value=bool(message_composition_config.get("include_weda_context", True)))
        self.include_transcription_var = tk.BooleanVar(
            value=bool(message_composition_config.get("include_transcription", True))
        )
        self.context_delay_seconds_var = tk.StringVar(value=str(self.get_context_capture_delay_seconds()))
        self.connector_enabled_var = tk.BooleanVar(value=bool(connector_config.get("enabled", False)))
        self.connector_start_key_var = tk.StringVar(value=str(connector_config.get("start_key") or "PageUp"))
        self.connector_stop_key_var = tk.StringVar(value=str(connector_config.get("stop_key") or "PageDown"))
        self.connector_document_now_key_var = tk.StringVar(
            value=str(connector_config.get("document_now_key") or "F8")
        )
        self.fly_dictation_enabled_var = tk.BooleanVar(value=bool(fly_dictation_config.get("enabled", True)))
        self.fly_dictation_key_var = tk.StringVar(value=str(fly_dictation_config.get("key") or "²"))
        self.fly_dictation_model_var = tk.StringVar(
            value=canonical_french_whisper_model_name(
                fly_dictation_config.get("model")
                or fly_dictation_config.get("default_model")
                or whisper_config.get("default_model")
                or "medium"
            )
        )
        self.fly_dictation_device_var = tk.StringVar(
            value=str(fly_dictation_config.get("device") or whisper_config.get("device") or "cpu")
        )
        self.fly_dictation_compute_var = tk.StringVar(
            value=str(fly_dictation_config.get("compute_type") or whisper_config.get("compute_type") or "int8")
        )
        self.result_destination_var = tk.StringVar(value=result_destination)
        self.pdf_template_var = tk.StringVar(value="")
        self.pdf_prompt_var = tk.StringVar(value="")
        self.pdf_source_var = tk.StringVar(value=pdf_source)
        self.pdf_field_name_var = tk.StringVar(value="")
        self.pdf_field_label_var = tk.StringVar(value="")
        self.pdf_field_description_var = tk.StringVar(value="")
        self.pdf_field_required_var = tk.BooleanVar(value=False)
        self.pdf_preview_field_var = tk.StringVar(value="")
        self.pdf_preview_value_var = tk.StringVar(value="")
        self.pdf_current_template_id = ""
        self.pdf_current_metadata: dict = {}
        self.pdf_current_fields: list[dict] = []
        self.pdf_current_schema: dict = {}
        self.pdf_current_values: dict[str, str | bool] = {}
        self.pdf_current_issues: list[dict] = []
        self.pdf_last_output_path = ""

        self.micro_status_var = tk.StringVar(value="Micro prêt")
        self.transcription_status_var = tk.StringVar(value="Transcription prête")
        self.model_status_var = tk.StringVar(value="Moteur STT: aucun")
        self.stt_status_var = tk.StringVar(value=f"STT: {self.stt_engine_var.get()}")
        self.prompt_status_var = tk.StringVar(value="Prompt: aucun")
        self.secondary_status_var = tk.StringVar(value="Prompt 2: désactivé")
        self.tertiary_status_var = tk.StringVar(value="Prompt 3: désactivé")
        self.document_now_status_var = tk.StringVar(value="Document maintenant: prêt")
        self.whisper_initial_prompt_status_var = tk.StringVar(value="Prompt Whisper: aucun")
        self.abbreviations_status_var = tk.StringVar(value="Abréviations: non chargées")
        self.message_attachment_status_var = tk.StringVar(value="Fichiers: aucun")
        self.fly_dictation_status_var = tk.StringVar(value="Volée: initialisation")
        self.lmstudio_status_var = tk.StringVar(value="LM Studio: prêt")
        self.lmstudio_progress_var = tk.StringVar(value="")
        self.weda_patient_status_var = tk.StringVar(value="Patient WEDA: non reçu")
        self.patient_safety_title_var = tk.StringVar(value="Aucun dossier WEDA verrouillé")
        self.patient_safety_detail_var = tk.StringVar(value="Récupère le contexte patient avant génération ou import WEDA.")
        self.import_status_var = tk.StringVar(value="Import WEDA: aucun")
        self.server_status_var = tk.StringVar(value="Serveur local: arrêté")
        self.log_status_var = tk.StringVar(value="Logs: prêts")
        self.pdf_status_var = tk.StringVar(value="PDF: aucun modèle")
        self.text_search_window: tk.Toplevel | None = None
        self.text_search_query_var = tk.StringVar(value="")
        self.text_search_status_var = tk.StringVar(value="Recherche prête")
        self.text_search_matches: list[tuple[tk.Text, str, str]] = []
        self.text_search_current_index = -1

        self._fly_dictation_lock = threading.Lock()
        self._fly_dictation_key_down = False
        self._fly_dictation_hook_handles = []
        self._fly_keyboard = None
        self._fly_recording = False
        self._fly_busy = False
        self._fly_recorder: PushToTalkRecorder | None = None
        self._fly_transcription_lock = threading.Lock()
        self._fly_cuda_runtime_failed = False

        self._build_ui()
        self.install_text_search_shortcuts()
        self.setup_tray_icon()
        self.install_live_message_refresh()
        self.restore_last_transcription()
        self._refresh_prompt_combo()
        self._refresh_secondary_prompt_combo()
        self._refresh_tertiary_prompt_combo()
        self._refresh_document_now_prompt_combo()
        self._refresh_pdf_prompt_combo()
        self.refresh_pdf_template_combo()
        self._refresh_whisper_initial_prompt_combo()
        self.load_abbreviations_text()
        self.refresh_context_from_manager()
        self.start_server()
        self.install_fly_dictation_hotkey()
        self.preload_fly_dictation_model()
        self.refresh_lmstudio_context_window_async()
        self.root.bind("<Configure>", self.on_root_configure, add="+")
        self.root.bind("<Unmap>", self.on_root_unmap, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def configure_material_theme(self) -> None:
        self.theme = dict(MATERIAL_DARK_THEME)
        colors = self.theme
        self.root.configure(bg=colors["background"])
        self.root.option_add("*Font", "{Segoe UI} 10")
        self.root.option_add("*TCombobox*Listbox.font", "{Segoe UI} 10")
        self.root.option_add("*TCombobox*Listbox.background", colors["surface_low"])
        self.root.option_add("*TCombobox*Listbox.foreground", colors["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", colors["primary_container"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", colors["text"])

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            ".",
            background=colors["background"],
            foreground=colors["text"],
            fieldbackground=colors["surface_low"],
            bordercolor=colors["outline"],
            lightcolor=colors["surface_high"],
            darkcolor=colors["surface"],
            troughcolor=colors["surface"],
            font=("Segoe UI", 10),
        )
        style.configure("TFrame", background=colors["background"])
        style.configure("Toolbar.TFrame", background=colors["background"], borderwidth=0)
        style.configure("Header.TFrame", background=colors["background"], borderwidth=0)
        style.configure("TLabel", background=colors["background"], foreground=colors["muted_text"])
        style.configure("Title.TLabel", background=colors["background"], foreground=colors["text"], font=("Segoe UI", 11, "bold"))
        style.configure(
            "AppTitle.TLabel",
            background=colors["background"],
            foreground=colors["text"],
            font=("Segoe UI", 20, "bold"),
        )
        style.configure(
            "AppSubtitle.TLabel",
            background=colors["background"],
            foreground=colors["primary"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Status.TLabel",
            background=colors["surface_low"],
            foreground=colors["muted_text"],
            bordercolor=colors["outline_soft"],
            relief=tk.FLAT,
            padding=(8, 4),
        )
        style.configure(
            "Spinner.TLabel",
            background=colors["background"],
            foreground=colors["primary"],
            font=("Segoe UI", 11, "bold"),
        )
        style.configure(
            "TButton",
            background=colors["surface_high"],
            foreground=colors["text"],
            bordercolor=colors["outline"],
            focusthickness=1,
            focuscolor=colors["primary"],
            padding=(10, 6),
            relief=tk.FLAT,
        )
        style.map(
            "TButton",
            background=[
                ("disabled", colors["surface"]),
                ("pressed", colors["primary_container"]),
                ("active", colors["surface_hover"]),
            ],
            foreground=[("disabled", colors["disabled_text"]), ("active", colors["text"])],
            bordercolor=[("focus", colors["primary"]), ("active", colors["primary"])],
        )
        style.configure(
            "Accent.TButton",
            background=colors["primary_container"],
            foreground=colors["text"],
            bordercolor=colors["primary"],
        )
        style.map(
            "Accent.TButton",
            background=[("pressed", colors["primary_high"]), ("active", colors["selection"])],
            foreground=[("pressed", colors["on_primary"]), ("disabled", colors["disabled_text"])],
        )
        style.configure(
            "Danger.TButton",
            background=colors["danger_container"],
            foreground=colors["text"],
            bordercolor=colors["danger"],
        )
        style.map("Danger.TButton", background=[("pressed", "#8f2638"), ("active", "#7f2333")])
        style.configure("TCheckbutton", background=colors["background"], foreground=colors["text"], padding=(4, 3))
        style.map(
            "TCheckbutton",
            background=[("active", colors["background"])],
            foreground=[("disabled", colors["disabled_text"]), ("active", colors["text"])],
            indicatorcolor=[("selected", colors["primary"]), ("!selected", colors["surface_high"])],
        )
        style.configure(
            "TCombobox",
            background=colors["surface_high"],
            foreground=colors["text"],
            fieldbackground=colors["surface_low"],
            arrowcolor=colors["primary"],
            bordercolor=colors["outline"],
            lightcolor=colors["surface_high"],
            darkcolor=colors["surface"],
            padding=(6, 4),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", colors["surface_low"]), ("focus", colors["surface_high"])],
            foreground=[("disabled", colors["disabled_text"])],
            bordercolor=[("focus", colors["primary"]), ("active", colors["primary"])],
        )
        style.configure(
            "TEntry",
            fieldbackground=colors["surface_low"],
            foreground=colors["text"],
            insertcolor=colors["primary"],
            bordercolor=colors["outline"],
            padding=(6, 5),
        )
        style.map("TEntry", bordercolor=[("focus", colors["primary"])])
        style.configure("TNotebook", background=colors["background"], borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure(
            "TNotebook.Tab",
            background=colors["surface"],
            foreground=colors["muted_text"],
            bordercolor=colors["surface"],
            padding=(14, 8),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", colors["primary_container"]), ("active", colors["surface_hover"])],
            foreground=[("selected", colors["text"]), ("active", colors["text"])],
        )
        style.configure("TLabelframe", background=colors["background"], bordercolor=colors["outline"], relief=tk.FLAT)
        style.configure("TLabelframe.Label", background=colors["background"], foreground=colors["primary"], font=("Segoe UI", 10, "bold"))
        style.configure("TPanedwindow", background=colors["background"])
        style.configure(
            "Treeview",
            background=colors["surface_low"],
            fieldbackground=colors["surface_low"],
            foreground=colors["text"],
            bordercolor=colors["outline"],
            rowheight=27,
            relief=tk.FLAT,
        )
        style.configure(
            "Treeview.Heading",
            background=colors["surface_high"],
            foreground=colors["text"],
            bordercolor=colors["outline"],
            font=("Segoe UI", 10, "bold"),
            padding=(6, 5),
        )
        style.map(
            "Treeview",
            background=[("selected", colors["primary_container"])],
            foreground=[("selected", colors["text"])],
        )
        style.configure("Vertical.TScrollbar", background=colors["surface_high"], troughcolor=colors["surface"], arrowcolor=colors["primary"])
        style.configure("Horizontal.TScrollbar", background=colors["surface_high"], troughcolor=colors["surface"], arrowcolor=colors["primary"])

    def create_text_widget(self, parent, **kwargs) -> tk.Text:
        text = tk.Text(parent, **kwargs)
        self.apply_text_theme(text)
        return text

    def apply_text_theme(self, text: tk.Text) -> None:
        colors = self.theme
        text.configure(
            bg=colors["surface_low"],
            fg=colors["text"],
            insertbackground=colors["primary"],
            selectbackground=colors["selection"],
            selectforeground=colors["text"],
            highlightbackground=colors["outline_soft"],
            highlightcolor=colors["primary"],
            highlightthickness=1,
            relief=tk.FLAT,
            bd=0,
            padx=10,
            pady=8,
            font=("Segoe UI", 10),
        )

    def apply_spinbox_theme(self, widget: tk.Spinbox) -> None:
        colors = self.theme
        widget.configure(
            bg=colors["surface_low"],
            fg=colors["text"],
            buttonbackground=colors["surface_high"],
            insertbackground=colors["primary"],
            selectbackground=colors["selection"],
            selectforeground=colors["text"],
            highlightbackground=colors["outline_soft"],
            highlightcolor=colors["primary"],
            relief=tk.FLAT,
            bd=0,
            font=("Segoe UI", 10),
        )

    def document_lmstudio_spinner_key(self, document_index: int) -> str:
        return f"document:{document_index}"

    def register_lmstudio_spinner(self, parent: tk.Widget, key: str) -> None:
        var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=var, width=2, anchor=tk.CENTER, style="Spinner.TLabel").pack(
            side=tk.LEFT,
            padx=(0, 6),
        )
        self.lmstudio_spinner_vars[key] = var

    def start_lmstudio_spinner(self, key: str) -> None:
        self.stop_lmstudio_spinner(key)
        self.lmstudio_spinner_frame_indexes[key] = 0
        self.advance_lmstudio_spinner(key)

    def advance_lmstudio_spinner(self, key: str) -> None:
        var = self.lmstudio_spinner_vars.get(key)
        if var is None:
            return
        frame_index = self.lmstudio_spinner_frame_indexes.get(key, 0)
        var.set(LMSTUDIO_SPINNER_FRAMES[frame_index % len(LMSTUDIO_SPINNER_FRAMES)])
        self.lmstudio_spinner_frame_indexes[key] = frame_index + 1
        self.lmstudio_spinner_jobs[key] = self.root.after(
            140,
            lambda spinner_key=key: self.advance_lmstudio_spinner(spinner_key),
        )

    def stop_lmstudio_spinner(self, key: str) -> None:
        job = self.lmstudio_spinner_jobs.pop(key, None)
        if job:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        self.lmstudio_spinner_frame_indexes.pop(key, None)
        var = self.lmstudio_spinner_vars.get(key)
        if var is not None:
            var.set("")

    def launch_lmstudio_request(
        self,
        key: str,
        client: LmStudioClient,
        message: str,
        *,
        on_success,
        on_error,
        thread_name: str,
        response_format: dict | None = None,
        result_source: str = "",
    ) -> bool:
        request_id = uuid.uuid4().hex
        stop_event = threading.Event()
        with self._active_lmstudio_requests_lock:
            existing = self.active_lmstudio_requests.get(key)
            if existing and not existing["stop_event"].is_set():
                self.lmstudio_status_var.set(f"LM Studio: {key} déjà en cours")
                return False
            self.active_lmstudio_requests[key] = {
                "request_id": request_id,
                "stop_event": stop_event,
                "started_at": time.monotonic(),
                "progress_chars": 0,
                "cancelling": False,
            }
        if result_source:
            self.capture_pending_result_patient_binding(result_source)
        self.update_lmstudio_request_controls()

        def progress(_elapsed: float, chars: int) -> None:
            with self._active_lmstudio_requests_lock:
                current = self.active_lmstudio_requests.get(key)
                if current and current.get("request_id") == request_id:
                    current["progress_chars"] = max(0, int(chars or 0))

        def worker():
            try:
                response = client.chat(
                    message,
                    stop_event=stop_event,
                    response_format=response_format,
                    on_progress=progress,
                )
                self.root.after(0, self.finish_lmstudio_request, key, request_id, on_success, response, None)
            except Exception as exc:
                self.root.after(0, self.finish_lmstudio_request, key, request_id, on_error, None, exc)

        threading.Thread(target=worker, name=thread_name, daemon=True).start()
        return True

    def is_lmstudio_request_active(self, key: str) -> bool:
        with self._active_lmstudio_requests_lock:
            request = self.active_lmstudio_requests.get(key)
            return bool(request and not request["stop_event"].is_set())

    def finish_lmstudio_request(self, key: str, request_id: str, callback, response, error) -> None:
        with self._active_lmstudio_requests_lock:
            current = self.active_lmstudio_requests.get(key)
            if not current or current.get("request_id") != request_id:
                return
            self.active_lmstudio_requests.pop(key, None)
        self.update_lmstudio_request_controls()
        if error is not None:
            callback(error)
        else:
            callback(response)

    def chat_lmstudio_managed_blocking(self, key: str, client: LmStudioClient, message: str):
        request_id = uuid.uuid4().hex
        stop_event = threading.Event()
        with self._active_lmstudio_requests_lock:
            if key in self.active_lmstudio_requests:
                raise RuntimeError(f"Génération {key} déjà en cours.")
            self.active_lmstudio_requests[key] = {
                "request_id": request_id,
                "stop_event": stop_event,
                "started_at": time.monotonic(),
                "progress_chars": 0,
                "cancelling": False,
            }
        self.root.after(0, self.update_lmstudio_request_controls)

        def progress(_elapsed: float, chars: int) -> None:
            with self._active_lmstudio_requests_lock:
                current = self.active_lmstudio_requests.get(key)
                if current and current.get("request_id") == request_id:
                    current["progress_chars"] = max(0, int(chars or 0))

        try:
            return client.chat(message, stop_event=stop_event, on_progress=progress)
        finally:
            self.root.after(0, self.finish_lmstudio_tracking, key, request_id)

    def finish_lmstudio_tracking(self, key: str, request_id: str) -> None:
        with self._active_lmstudio_requests_lock:
            current = self.active_lmstudio_requests.get(key)
            if current and current.get("request_id") == request_id:
                self.active_lmstudio_requests.pop(key, None)
        self.update_lmstudio_request_controls()

    def cancel_all_lmstudio_requests(self) -> None:
        with self._active_lmstudio_requests_lock:
            active = list(self.active_lmstudio_requests.values())
            for request in active:
                request["cancelling"] = True
                request["stop_event"].set()
        if active:
            self.lmstudio_status_var.set(f"LM Studio: annulation demandée ({len(active)})")
        self.update_lmstudio_request_controls()

    def update_lmstudio_request_controls(self) -> None:
        with self._active_lmstudio_requests_lock:
            active = [dict(item) for item in self.active_lmstudio_requests.values()]
        if hasattr(self, "cancel_lmstudio_button"):
            can_cancel = bool(active) and any(not item.get("cancelling") for item in active)
            self.cancel_lmstudio_button.configure(state=tk.NORMAL if can_cancel else tk.DISABLED)
        if active:
            elapsed = max(0.0, max(time.monotonic() - float(item["started_at"]) for item in active))
            chars = sum(int(item.get("progress_chars") or 0) for item in active)
            suffix = f" • {chars} caractères reçus" if chars else ""
            self.lmstudio_progress_var.set(f"{len(active)} génération(s) • {elapsed:.1f} s{suffix}")
            if self._lmstudio_progress_job:
                try:
                    self.root.after_cancel(self._lmstudio_progress_job)
                except Exception:
                    pass
            self._lmstudio_progress_job = self.root.after(250, self.update_lmstudio_request_controls)
        else:
            self.lmstudio_progress_var.set("")
            self._lmstudio_progress_job = None

    def lmstudio_request_was_cancelled(self, error: Exception) -> bool:
        return isinstance(error, LmStudioCancelled)

    def setup_tray_icon(self) -> None:
        if self.tray_icon is not None:
            return

        if pystray is None or Image is None or ImageDraw is None or ImageFont is None:
            self.tray_available = False
            if hasattr(self, "minimize_to_tray_button"):
                self.minimize_to_tray_button.configure(state=tk.DISABLED)
            self.log_debug(
                "warning",
                "app",
                "tray_unavailable",
                "Zone de notification indisponible : pystray/Pillow non installés.",
            )
            return

        try:
            self.tray_images = {
                "idle": self.create_tray_icon_image(recording=False),
                "recording": self.create_tray_icon_image(recording=True),
            }
            menu = pystray.Menu(
                pystray.MenuItem("Afficher DrFloW", self.on_tray_show, default=True),
                pystray.MenuItem("Réduire la fenêtre", self.on_tray_hide),
                pystray.MenuItem("Quitter DrFloW", self.on_tray_quit),
            )
            self.tray_icon = pystray.Icon(
                APP_NAME,
                self.tray_images["idle"],
                self.get_tray_title(),
                menu,
            )
            self.tray_thread = threading.Thread(
                target=self.tray_icon.run,
                name="DrFloWTray",
                daemon=True,
            )
            self.tray_thread.start()
            self.tray_available = True
            self.log_debug("info", "app", "tray_ready", "Icône de zone de notification prête.")
        except Exception as exc:
            self.tray_icon = None
            self.tray_available = False
            if hasattr(self, "minimize_to_tray_button"):
                self.minimize_to_tray_button.configure(state=tk.DISABLED)
            self.log_debug("warning", "app", "tray_setup_error", str(exc))

    def create_tray_icon_image(self, *, recording: bool = False):
        size = 64
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        if recording:
            draw.ellipse((7, 7, 57, 57), fill="#dc2626", outline="#ffffff", width=4)
            draw.ellipse((23, 23, 41, 41), fill="#ffffff")
            return image

        draw.rounded_rectangle((6, 6, 58, 58), radius=16, fill="#174ea6", outline="#cfe8ff", width=3)
        try:
            font = ImageFont.truetype("segoeuib.ttf", 34)
        except Exception:
            font = ImageFont.load_default()

        label = "D"
        try:
            text_box = draw.textbbox((0, 0), label, font=font)
            text_width = text_box[2] - text_box[0]
            text_height = text_box[3] - text_box[1]
            text_x = (size - text_width) / 2 - text_box[0]
            text_y = (size - text_height) / 2 - text_box[1] - 1
        except Exception:
            text_x = 24
            text_y = 18
        draw.text((text_x, text_y), label, fill="#ffffff", font=font)
        return image

    def get_tray_title(self) -> str:
        if self._recording_indicator_active:
            return f"{APP_NAME} - {self.get_recording_indicator_label(self._recording_indicator_source)}"
        return f"{APP_NAME} - prêt"

    def update_tray_icon(self) -> None:
        icon = self.tray_icon
        if not icon or not self.tray_images:
            return

        try:
            icon.icon = self.tray_images["recording" if self._recording_indicator_active else "idle"]
            icon.title = self.get_tray_title()
        except Exception as exc:
            self.log_debug("warning", "app", "tray_update_error", str(exc))

    def on_tray_show(self, _icon=None, _item=None) -> None:
        self.root.after(0, self.restore_from_tray)

    def on_tray_hide(self, _icon=None, _item=None) -> None:
        self.root.after(0, self.minimize_to_tray)

    def on_tray_quit(self, _icon=None, _item=None) -> None:
        self.root.after(0, self.close)

    def minimize_to_tray(self) -> None:
        if not self.tray_available:
            self.setup_tray_icon()

        if not self.tray_available:
            messagebox.showwarning(
                "Zone de notification",
                "La zone de notification n'est pas disponible. Installe les dépendances pystray et Pillow.",
                parent=self.root,
            )
            return

        self.tray_hidden = True
        self.root.withdraw()
        self.update_tray_icon()
        self.log_debug("info", "app", "window_minimized_to_tray", "Fenêtre réduite dans la zone de notification.")

    def restore_from_tray(self) -> None:
        self.tray_hidden = False
        try:
            self.root.deiconify()
            self.root.state("normal")
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass
        self.update_tray_icon()
        self.log_debug("info", "app", "window_restored_from_tray", "Fenêtre restaurée depuis la zone de notification.")

    def on_root_unmap(self, event) -> None:
        if event.widget is not self.root or self._closing or self.tray_hidden:
            return
        if not self.tray_available:
            return

        self.root.after(120, self.minimize_to_tray_if_iconic)

    def minimize_to_tray_if_iconic(self) -> None:
        if self._closing or self.tray_hidden or not self.tray_available:
            return

        try:
            if self.root.state() == "iconic":
                self.minimize_to_tray()
        except tk.TclError:
            pass

    def stop_tray_icon(self) -> None:
        icon = self.tray_icon
        self.tray_icon = None
        self.tray_available = False
        if not icon:
            return

        try:
            icon.stop()
        except Exception as exc:
            self.log_debug("warning", "app", "tray_stop_error", str(exc))

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=8, style="Toolbar.TFrame")
        top.pack(side=tk.TOP, fill=tk.X)

        self.recording_badge = tk.Label(
            top,
            text="REC",
            bg="#dc2626",
            fg="#ffffff",
            font=("Arial", 9, "bold"),
            padx=8,
            pady=2,
            relief=tk.FLAT,
        )

        self.continue_dictation_button = ttk.Button(top, text="Poursuivre dictée", command=self.continue_dictation, style="Accent.TButton")
        self.continue_dictation_button.pack(side=tk.LEFT, padx=(0, 6))

        self.new_dictation_button = ttk.Button(top, text="Nouvelle dictée", command=self.new_dictation)
        self.new_dictation_button.pack(side=tk.LEFT, padx=(0, 6))

        self.stop_dictation_button = ttk.Button(top, text="Arrêter dictée", command=self.stop_dictation, state=tk.DISABLED, style="Danger.TButton")
        self.stop_dictation_button.pack(side=tk.LEFT, padx=(0, 8))

        self.document_now_button = ttk.Button(
            top,
            text="Document maintenant",
            command=self.document_now_checkpoint,
            style="Accent.TButton",
        )
        self.document_now_button.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(top, text="Modèle").pack(side=tk.LEFT)
        self.model_combo = ttk.Combobox(
            top,
            textvariable=self.model_var,
            values=WHISPER_MODEL_CHOICES,
            width=16,
            state="readonly",
        )
        self.model_combo.pack(side=tk.LEFT, padx=(4, 8))
        self.model_combo.bind("<<ComboboxSelected>>", lambda _event: self.save_whisper_runtime_settings())

        ttk.Label(top, text="Device").pack(side=tk.LEFT)
        self.device_combo = ttk.Combobox(
            top,
            textvariable=self.device_var,
            values=WHISPER_DEVICE_CHOICES,
            width=8,
            state="readonly",
        )
        self.device_combo.pack(side=tk.LEFT, padx=(4, 8))
        self.device_combo.bind("<<ComboboxSelected>>", lambda _event: self.save_whisper_runtime_settings())

        ttk.Label(top, text="Compute").pack(side=tk.LEFT)
        self.compute_combo = ttk.Combobox(
            top,
            textvariable=self.compute_var,
            values=WHISPER_COMPUTE_CHOICES,
            width=12,
            state="readonly",
        )
        self.compute_combo.pack(side=tk.LEFT, padx=(4, 8))
        self.compute_combo.bind("<<ComboboxSelected>>", lambda _event: self.save_whisper_runtime_settings())

        ttk.Label(top, text="Micro").pack(side=tk.LEFT)
        self.micro_device_combo = ttk.Combobox(
            top,
            textvariable=self.micro_device_var,
            values=[label for label, _value in self.micro_device_options],
            width=26,
            state="readonly",
        )
        self.micro_device_combo.pack(side=tk.LEFT, padx=(4, 8))
        self.micro_device_combo.bind("<<ComboboxSelected>>", lambda _event: self.save_micro_device())

        ttk.Button(top, text="Prévisualiser", command=self.preview_message).pack(side=tk.LEFT, padx=(12, 4))
        ttk.Button(top, text="Envoyer à LM Studio", command=self.send_to_lmstudio, style="Accent.TButton").pack(side=tk.LEFT, padx=4)
        self.register_lmstudio_spinner(top, LMSTUDIO_MAIN_SPINNER_KEY)
        self.cancel_lmstudio_button = ttk.Button(
            top,
            text="Annuler génération",
            command=self.cancel_all_lmstudio_requests,
            state=tk.DISABLED,
            style="Danger.TButton",
        )
        self.cancel_lmstudio_button.pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(top, textvariable=self.lmstudio_progress_var).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(top, text="Délai contexte (s)").pack(side=tk.LEFT, padx=(12, 4))
        self.context_delay_spinbox = tk.Spinbox(
            top,
            from_=0,
            to=300,
            increment=5,
            width=5,
            textvariable=self.context_delay_seconds_var,
            command=self.save_context_delay,
        )
        self.context_delay_spinbox.pack(side=tk.LEFT)
        self.apply_spinbox_theme(self.context_delay_spinbox)
        self.context_delay_spinbox.bind("<Return>", lambda _event: self.save_context_delay())
        self.context_delay_spinbox.bind("<FocusOut>", lambda _event: self.save_context_delay())

        self.minimize_to_tray_button = ttk.Button(
            top,
            text="Zone notif.",
            command=self.minimize_to_tray,
        )
        self.minimize_to_tray_button.pack(side=tk.RIGHT, padx=(8, 0))

        connector_bar = ttk.Frame(self.root, padding=(8, 0, 8, 6), style="Toolbar.TFrame")
        connector_bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Checkbutton(
            connector_bar,
            text="Connecteur WEDA actif",
            variable=self.connector_enabled_var,
            command=self.save_connector_settings,
        ).pack(side=tk.LEFT, padx=(0, 12))

        key_values = self.connector_key_choices()
        ttk.Label(connector_bar, text="Déclenchement").pack(side=tk.LEFT)
        self.connector_start_key_combo = ttk.Combobox(
            connector_bar,
            textvariable=self.connector_start_key_var,
            values=key_values,
            width=12,
            state="readonly",
        )
        self.connector_start_key_combo.pack(side=tk.LEFT, padx=(4, 12))
        self.connector_start_key_combo.bind("<<ComboboxSelected>>", lambda _event: self.save_connector_settings())

        ttk.Label(connector_bar, text="Arrêt / envoi").pack(side=tk.LEFT)
        self.connector_stop_key_combo = ttk.Combobox(
            connector_bar,
            textvariable=self.connector_stop_key_var,
            values=key_values,
            width=12,
            state="readonly",
        )
        self.connector_stop_key_combo.pack(side=tk.LEFT, padx=(4, 12))
        self.connector_stop_key_combo.bind("<<ComboboxSelected>>", lambda _event: self.save_connector_settings())

        ttk.Label(connector_bar, text="Document maintenant").pack(side=tk.LEFT)
        self.connector_document_now_key_combo = ttk.Combobox(
            connector_bar,
            textvariable=self.connector_document_now_key_var,
            values=key_values,
            width=12,
            state="readonly",
        )
        self.connector_document_now_key_combo.pack(side=tk.LEFT, padx=(4, 12))
        self.connector_document_now_key_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self.save_connector_settings(),
        )

        ttk.Button(connector_bar, text="Versions / comparer", command=self.show_quality_window).pack(
            side=tk.RIGHT,
            padx=(6, 0),
        )
        ttk.Button(connector_bar, text="Diagnostic DrFloW", command=self.show_diagnostic_window).pack(
            side=tk.RIGHT,
            padx=(6, 0),
        )

        self.patient_safety_bar = tk.Frame(self.root, bg="#3b1014", padx=8, pady=5)
        self.patient_safety_bar.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(0, 6))
        self.patient_safety_badge = tk.Label(
            self.patient_safety_bar,
            text="VERROUILLÉ",
            bg="#991b1b",
            fg="#ffffff",
            font=("Segoe UI", 9, "bold"),
            padx=8,
            pady=2,
        )
        self.patient_safety_badge.pack(side=tk.LEFT, padx=(0, 8))
        self.patient_safety_title_label = tk.Label(
            self.patient_safety_bar,
            textvariable=self.patient_safety_title_var,
            bg="#3b1014",
            fg="#ffffff",
            font=("Segoe UI", 10, "bold"),
        )
        self.patient_safety_title_label.pack(side=tk.LEFT)
        self.patient_safety_detail_label = tk.Label(
            self.patient_safety_bar,
            textvariable=self.patient_safety_detail_var,
            bg="#3b1014",
            fg="#fecaca",
            font=("Segoe UI", 9),
        )
        self.patient_safety_detail_label.pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(
            self.patient_safety_bar,
            text="Relire contexte",
            command=self.request_weda_context_refresh,
        ).pack(
            side=tk.RIGHT,
            padx=(6, 0),
        )

        fly_bar = ttk.Frame(self.root, padding=(8, 0, 8, 6), style="Toolbar.TFrame")
        fly_bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Checkbutton(
            fly_bar,
            text="Dictée à la volée active",
            variable=self.fly_dictation_enabled_var,
            command=self.save_fly_dictation_settings,
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Label(fly_bar, text="Maintenir").pack(side=tk.LEFT)
        self.fly_dictation_key_combo = ttk.Combobox(
            fly_bar,
            textvariable=self.fly_dictation_key_var,
            values=self.fly_dictation_key_choices(),
            width=12,
            state="normal",
        )
        self.fly_dictation_key_combo.pack(side=tk.LEFT, padx=(4, 8))
        self.fly_dictation_key_combo.bind("<<ComboboxSelected>>", lambda _event: self.save_fly_dictation_settings())
        self.fly_dictation_key_combo.bind("<Return>", lambda _event: self.save_fly_dictation_settings())
        self.fly_dictation_key_combo.bind("<FocusOut>", lambda _event: self.save_fly_dictation_settings())
        ttk.Label(fly_bar, text="Modèle volée").pack(side=tk.LEFT, padx=(8, 0))
        self.fly_dictation_model_combo = ttk.Combobox(
            fly_bar,
            textvariable=self.fly_dictation_model_var,
            values=WHISPER_MODEL_CHOICES,
            width=14,
            state="readonly",
        )
        self.fly_dictation_model_combo.pack(side=tk.LEFT, padx=(4, 8))
        self.fly_dictation_model_combo.bind("<<ComboboxSelected>>", lambda _event: self.save_fly_dictation_settings())
        ttk.Label(fly_bar, text="Device volée").pack(side=tk.LEFT, padx=(4, 0))
        self.fly_dictation_device_combo = ttk.Combobox(
            fly_bar,
            textvariable=self.fly_dictation_device_var,
            values=WHISPER_DEVICE_CHOICES,
            width=7,
            state="readonly",
        )
        self.fly_dictation_device_combo.pack(side=tk.LEFT, padx=(4, 8))
        self.fly_dictation_device_combo.bind("<<ComboboxSelected>>", lambda _event: self.save_fly_dictation_settings())
        ttk.Label(fly_bar, text="Compute volée").pack(side=tk.LEFT, padx=(4, 0))
        self.fly_dictation_compute_combo = ttk.Combobox(
            fly_bar,
            textvariable=self.fly_dictation_compute_var,
            values=WHISPER_COMPUTE_CHOICES,
            width=11,
            state="readonly",
        )
        self.fly_dictation_compute_combo.pack(side=tk.LEFT, padx=(4, 8))
        self.fly_dictation_compute_combo.bind("<<ComboboxSelected>>", lambda _event: self.save_fly_dictation_settings())
        ttk.Label(fly_bar, text="relâcher pour transcrire et coller").pack(side=tk.LEFT)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self.context_text = self._add_text_tab(
            "Contexte WEDA",
            buttons=[
                ("Rafraîchir depuis WEDA", self.request_weda_context_refresh),
                ("Effacer contexte", self.clear_context),
            ],
        )
        self.transcription_notebook = self._add_series_group_tab("Transcription")
        self.transcription_text = self._add_text_tab(
            "Transcription brute",
            parent_notebook=self.transcription_notebook,
            buttons=[
                ("Copier transcription", self.copy_transcription),
                ("Effacer transcription", self.clear_transcription),
            ],
        )
        self.corrected_transcription_text = self._add_transcription_corrections_tab(
            parent_notebook=self.transcription_notebook
        )
        self.series_1_notebook = self._add_series_group_tab("Document 1")
        self.prompt_text = self._add_prompt_tab(parent_notebook=self.series_1_notebook)
        self.sent_message_text = self._add_text_tab(
            "Message",
            parent_notebook=self.series_1_notebook,
            buttons=[("Prévisualiser message", self.preview_message)],
            readonly=True,
            message_controls=True,
            message_document_index=1,
        )
        self.result_text = self._add_text_tab(
            "Résultat",
            parent_notebook=self.series_1_notebook,
            buttons=[
                ("Copier résultat", self.copy_result),
                ("Réessayer", self.send_to_lmstudio, LMSTUDIO_RESULT_RETRY_SPINNER_KEY),
                ("Effacer résultat", self.clear_result),
                ("Importer dans WEDA", self.prepare_weda_import),
            ],
            destination_controls=True,
            destination_buttons=[
                ("Utiliser pour PDF structuré", self.use_result_for_pdf),
            ],
        )
        self.series_2_notebook = self._add_series_group_tab("Document 2")
        self.secondary_prompt_text = self._add_secondary_prompt_tab(parent_notebook=self.series_2_notebook)
        self.secondary_sent_message_text = self._add_text_tab(
            "Message",
            parent_notebook=self.series_2_notebook,
            buttons=[("Prévisualiser Message 2", self.preview_secondary_message)],
            readonly=True,
            message_controls=True,
            message_document_index=2,
        )
        self.secondary_result_text = self._add_text_tab(
            "Résultat",
            parent_notebook=self.series_2_notebook,
            buttons=[
                ("Copier Résultat 2", self.copy_secondary_result),
                ("Réessayer Prompt 2", self.run_secondary_analysis_manual, LMSTUDIO_SECONDARY_RETRY_SPINNER_KEY),
                ("Effacer Résultat 2", self.clear_secondary_result),
                ("Importer Résultat 2 dans WEDA", self.prepare_weda_import_result_2),
            ],
            destination_controls=True,
            destination_buttons=[
                ("Utiliser Résultat 2 pour PDF structuré", self.use_secondary_result_for_pdf),
            ],
        )
        self.series_3_notebook = self._add_series_group_tab("Document 3")
        self.tertiary_prompt_text = self._add_tertiary_prompt_tab(parent_notebook=self.series_3_notebook)
        self.tertiary_sent_message_text = self._add_text_tab(
            "Message",
            parent_notebook=self.series_3_notebook,
            buttons=[("Prévisualiser Message 3", self.preview_tertiary_message)],
            readonly=True,
            message_controls=True,
            message_document_index=3,
        )
        self.tertiary_result_text = self._add_text_tab(
            "Résultat",
            parent_notebook=self.series_3_notebook,
            buttons=[
                ("Copier Résultat 3", self.copy_tertiary_result),
                ("Réessayer Prompt 3", self.run_tertiary_analysis_manual, LMSTUDIO_TERTIARY_RETRY_SPINNER_KEY),
                ("Effacer Résultat 3", self.clear_tertiary_result),
                ("Importer Résultat 3 dans WEDA", self.prepare_weda_import_result_3),
            ],
            destination_controls=True,
            destination_buttons=[
                ("Utiliser Résultat 3 pour PDF structuré", self.use_tertiary_result_for_pdf),
            ],
        )
        self.document_now_notebook = self._add_series_group_tab("Document maintenant")
        self.document_now_prompt_text = self._add_document_now_prompt_tab(parent_notebook=self.document_now_notebook)
        self.document_now_sent_message_text = self._add_text_tab(
            "Message envoyé",
            parent_notebook=self.document_now_notebook,
            buttons=[("Prévisualiser message", self.preview_document_now_message)],
            readonly=True,
            message_controls=True,
            message_send_command=self.send_document_now_from_message_tab,
            message_send_label="Document maintenant",
            message_spinner_key=DOCUMENT_NOW_SPINNER_KEY,
        )
        self.document_now_result_text = self._add_text_tab(
            "Résultat",
            parent_notebook=self.document_now_notebook,
            buttons=[
                ("Copier résultat", self.copy_document_now_result),
                ("Regénérer depuis snapshot", self.regenerate_document_now_from_snapshot),
                ("Effacer résultat", self.clear_document_now_result),
                ("Importer Document maintenant dans WEDA", self.prepare_weda_import_document_now),
            ],
            destination_controls=True,
            destination_buttons=[
                ("Utiliser Document maintenant pour PDF structuré", self.use_document_now_result_for_pdf),
            ],
        )
        self.pdf_tab_frame = self._add_pdf_structured_tab()
        self.whisper_initial_prompt_text = self._add_whisper_initial_prompt_tab()
        self.abbreviations_text = self._add_abbreviations_tab()
        self.logs_text = self._add_text_tab(
            "Logs",
            buttons=[
                ("Rafraîchir", self.refresh_logs),
                ("Copier logs", self.copy_logs),
                ("Effacer logs", self.clear_logs),
            ],
            readonly=True,
        )
        self.stt_tab_frame = self._add_stt_engine_tab()
        self.apply_main_notebook_tab_order()
        self.install_main_notebook_tab_dragging()
        self.refresh_logs()

        self._message_source_widgets = [
            self.context_text,
            self.transcription_text,
            self.corrected_transcription_text,
            self.prompt_text,
        ]
        self._secondary_message_source_widgets = [
            self.context_text,
            self.transcription_text,
            self.corrected_transcription_text,
            self.prompt_text,
            self.result_text,
            self.secondary_prompt_text,
        ]
        self._tertiary_message_source_widgets = [
            self.context_text,
            self.transcription_text,
            self.corrected_transcription_text,
            self.prompt_text,
            self.result_text,
            self.secondary_prompt_text,
            self.secondary_result_text,
            self.tertiary_prompt_text,
        ]
        self._document_now_message_source_widgets = [
            self.context_text,
            self.transcription_text,
            self.corrected_transcription_text,
            self.document_now_default_prompt_text,
            self.document_now_prompt_text,
        ]
        self.install_rich_result_copy_bindings()

        status = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        status.pack(side=tk.BOTTOM, fill=tk.X)
        for variable in (
            self.micro_status_var,
            self.transcription_status_var,
            self.model_status_var,
            self.stt_status_var,
            self.whisper_initial_prompt_status_var,
            self.abbreviations_status_var,
            self.fly_dictation_status_var,
            self.prompt_status_var,
            self.secondary_status_var,
            self.tertiary_status_var,
            self.document_now_status_var,
            self.lmstudio_status_var,
            self.weda_patient_status_var,
            self.import_status_var,
            self.server_status_var,
            self.log_status_var,
            self.pdf_status_var,
        ):
            ttk.Label(status, textvariable=variable, style="Status.TLabel").pack(side=tk.LEFT, padx=(0, 4))

    def _add_series_group_tab(self, title: str) -> ttk.Notebook:
        frame = ttk.Frame(self.notebook, padding=0)
        self.notebook.add(frame, text=title)
        series_notebook = ttk.Notebook(frame)
        series_notebook.pack(fill=tk.BOTH, expand=True)
        return series_notebook


    def _add_stt_engine_tab(self) -> ttk.Frame:
        frame = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(frame, text="Moteur de transcription")

        controls = ttk.Frame(frame)
        controls.pack(side=tk.TOP, fill=tk.X, pady=(0, 8))

        ttk.Label(controls, text="Moteur").grid(row=0, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        self.stt_engine_combo = ttk.Combobox(
            controls,
            textvariable=self.stt_engine_var,
            values=tuple(STT_ENGINE_LABELS.values()),
            width=18,
            state="readonly",
        )
        self.stt_engine_combo.grid(row=0, column=1, sticky=tk.W, padx=(0, 12), pady=3)
        self.stt_engine_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_stt_engine_changed())

        ttk.Label(controls, text="Modèle").grid(row=0, column=2, sticky=tk.W, padx=(0, 4), pady=3)
        self.stt_model_combo = ttk.Combobox(controls, textvariable=self.stt_model_var, width=26, state="readonly")
        self.stt_model_combo.grid(row=0, column=3, sticky=tk.W, padx=(0, 12), pady=3)
        self.stt_model_combo.bind("<<ComboboxSelected>>", lambda _event: self.save_stt_settings())

        ttk.Label(controls, text="Runtime").grid(row=0, column=4, sticky=tk.W, padx=(0, 4), pady=3)
        self.stt_runtime_combo = ttk.Combobox(controls, textvariable=self.stt_runtime_var, width=14, state="readonly")
        self.stt_runtime_combo.grid(row=0, column=5, sticky=tk.W, padx=(0, 12), pady=3)
        self.stt_runtime_combo.bind("<<ComboboxSelected>>", lambda _event: self.save_stt_settings())

        ttk.Label(controls, text="Device").grid(row=0, column=6, sticky=tk.W, padx=(0, 4), pady=3)
        self.stt_device_combo = ttk.Combobox(controls, textvariable=self.stt_device_var, width=10, state="readonly")
        self.stt_device_combo.grid(row=0, column=7, sticky=tk.W, padx=(0, 12), pady=3)
        self.stt_device_combo.bind("<<ComboboxSelected>>", lambda _event: self.save_stt_settings())

        ttk.Button(controls, text="Charger", command=self.load_active_stt_engine).grid(row=0, column=8, padx=(0, 4), pady=3)
        ttk.Button(controls, text="Décharger", command=self.unload_active_stt_engine).grid(row=0, column=9, padx=(0, 4), pady=3)
        ttk.Button(controls, text="Tester", command=self.test_active_stt_engine).grid(row=0, column=10, padx=(0, 4), pady=3)
        ttk.Button(controls, text="Comparer les moteurs", command=self.compare_stt_engines, style="Accent.TButton").grid(
            row=0,
            column=11,
            padx=(0, 4),
            pady=3,
        )

        ttk.Checkbutton(
            controls,
            text="Moteurs expérimentaux",
            variable=self.stt_allow_experimental_var,
            command=self.save_stt_settings,
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=3)
        ttk.Checkbutton(
            controls,
            text="Fallback faster-whisper",
            variable=self.stt_auto_fallback_var,
            command=self.save_stt_settings,
        ).grid(row=1, column=2, columnspan=2, sticky=tk.W, pady=3)
        ttk.Checkbutton(
            controls,
            text="Garder audio benchmark",
            variable=self.stt_keep_audio_var,
            command=self.save_stt_settings,
        ).grid(row=1, column=4, columnspan=2, sticky=tk.W, pady=3)
        ttk.Checkbutton(
            controls,
            text="Warnings visibles",
            variable=self.stt_show_warnings_var,
            command=self.save_stt_settings,
        ).grid(row=1, column=6, columnspan=2, sticky=tk.W, pady=3)

        ttk.Label(controls, text="Commande externe").grid(row=2, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        self.stt_external_entry = ttk.Entry(controls, textvariable=self.stt_external_cli_var, width=92)
        self.stt_external_entry.grid(row=2, column=1, columnspan=7, sticky=tk.EW, pady=3)
        self.stt_external_entry.bind("<Return>", lambda _event: self.save_stt_settings())
        self.stt_external_entry.bind("<FocusOut>", lambda _event: self.save_stt_settings())

        ttk.Label(controls, text="Serveur local").grid(row=3, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        self.stt_server_entry = ttk.Entry(controls, textvariable=self.stt_server_url_var, width=32)
        self.stt_server_entry.grid(row=3, column=1, columnspan=2, sticky=tk.W, pady=3)
        self.stt_server_entry.bind("<Return>", lambda _event: self.save_stt_settings())
        self.stt_server_entry.bind("<FocusOut>", lambda _event: self.save_stt_settings())

        ttk.Label(controls, text="Comparer").grid(row=3, column=3, sticky=tk.W, padx=(0, 4), pady=3)
        ttk.Checkbutton(
            controls,
            text="faster-whisper",
            variable=self.stt_compare_faster_var,
            command=self.save_stt_settings,
        ).grid(row=3, column=4, sticky=tk.W)
        ttk.Checkbutton(
            controls,
            text="Qwen3-ASR",
            variable=self.stt_compare_qwen_var,
            command=self.save_stt_settings,
        ).grid(row=3, column=5, sticky=tk.W)
        ttk.Checkbutton(
            controls,
            text="Voxtral",
            variable=self.stt_compare_voxtral_var,
            command=self.save_stt_settings,
        ).grid(row=3, column=6, sticky=tk.W)
        ttk.Button(controls, text="Utiliser résultat sélectionné", command=self.use_selected_stt_benchmark_result).grid(
            row=3,
            column=8,
            columnspan=3,
            sticky=tk.W,
            padx=(8, 0),
            pady=3,
        )

        context_frame = ttk.Frame(frame)
        context_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 8))
        ttk.Label(context_frame, text="Mini-vocabulaire STT").pack(side=tk.TOP, anchor=tk.W)
        self.stt_context_bias_text = self.create_text_widget(context_frame, wrap=tk.WORD, undo=True, height=4)
        self.stt_context_bias_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.set_text(self.stt_context_bias_text, str(self.config.get("stt", {}).get("stt_context_bias") or ""))
        self.stt_context_bias_text.bind("<FocusOut>", lambda _event: self.save_stt_settings())

        speaker_frame = ttk.Frame(frame)
        speaker_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 8))
        ttk.Label(speaker_frame, text="Mapping locuteurs (SPEAKER_00=Médecin)").pack(side=tk.TOP, anchor=tk.W)
        self.stt_speaker_map_text = self.create_text_widget(speaker_frame, wrap=tk.WORD, undo=True, height=3)
        self.stt_speaker_map_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.set_text(self.stt_speaker_map_text, self.serialize_stt_speaker_map(self.config.get("stt", {}).get("speaker_map", {})))
        self.stt_speaker_map_text.bind("<FocusOut>", lambda _event: self.save_stt_settings())

        info_frame = ttk.Frame(frame)
        info_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 8))
        self.stt_info_text = self.create_text_widget(info_frame, wrap=tk.WORD, undo=False, height=5)
        self.stt_info_text.pack(side=tk.LEFT, fill=tk.X, expand=True)

        table_frame = ttk.Frame(frame)
        table_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        columns = ("engine", "model", "device", "time", "diarization", "errors", "text")
        self.stt_benchmark_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=8)
        headings = {
            "engine": "Moteur",
            "model": "Modèle",
            "device": "Device",
            "time": "Temps",
            "diarization": "Diarisation",
            "errors": "Erreurs",
            "text": "Texte",
        }
        widths = {"engine": 120, "model": 190, "device": 100, "time": 70, "diarization": 90, "errors": 70, "text": 640}
        for column in columns:
            self.stt_benchmark_tree.heading(column, text=headings[column])
            self.stt_benchmark_tree.column(column, width=widths[column], anchor=tk.W, stretch=column == "text")
        self.stt_benchmark_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(table_frame, command=self.stt_benchmark_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.stt_benchmark_tree.configure(yscrollcommand=scrollbar.set)

        self.refresh_stt_engine_controls()
        return frame

    def _add_text_tab(
        self,
        title: str,
        *,
        parent_notebook: ttk.Notebook | None = None,
        buttons=None,
        readonly: bool = False,
        message_controls: bool = False,
        message_document_index: int = 1,
        message_send_command=None,
        message_send_label: str = "Envoyer à LM Studio",
        message_spinner_key: str | None = None,
        destination_controls: bool = False,
        destination_buttons=None,
    ) -> tk.Text:
        notebook = parent_notebook or self.notebook
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text=title)

        toolbar = ttk.Frame(frame)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
        for button_config in buttons or []:
            label, command = button_config[:2]
            ttk.Button(toolbar, text=label, command=command).pack(side=tk.LEFT, padx=(0, 6))
            if len(button_config) >= 3 and button_config[2]:
                self.register_lmstudio_spinner(toolbar, str(button_config[2]))
        if message_controls:
            self.add_message_composition_controls(
                toolbar,
                document_index=message_document_index,
                send_command=message_send_command,
                send_label=message_send_label,
                spinner_key=message_spinner_key,
            )
        if destination_controls:
            self.add_result_destination_controls(toolbar)
            for label, command in destination_buttons or []:
                ttk.Button(toolbar, text=label, command=command).pack(side=tk.LEFT, padx=(0, 6))
        text = self.create_text_widget(frame, wrap=tk.WORD, undo=True, height=10)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(frame, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.configure(yscrollcommand=scrollbar.set)
        if readonly:
            text.configure(state=tk.DISABLED)
        return text

    def add_message_composition_controls(
        self,
        toolbar: ttk.Frame,
        document_index: int = 1,
        send_command=None,
        send_label: str = "Envoyer à LM Studio",
        spinner_key: str | None = None,
    ) -> None:
        ttk.Label(toolbar, text="Envoyer").pack(side=tk.LEFT, padx=(12, 4))
        for label, variable in (
            ("Prompt", self.include_prompt_var),
            ("Contexte", self.include_context_var),
            ("Transcription", self.include_transcription_var),
        ):
            ttk.Checkbutton(
                toolbar,
                text=label,
                variable=variable,
                command=self.save_message_composition_settings,
            ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="Charger fichier", command=self.add_message_attachment_files).pack(side=tk.LEFT, padx=(8, 6))
        ttk.Button(toolbar, text="Vider fichiers", command=self.clear_message_attachments).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            toolbar,
            text=send_label,
            command=send_command or (lambda index=document_index: self.send_document_to_lmstudio(index)),
            style="Accent.TButton",
        ).pack(side=tk.LEFT, padx=(0, 6))
        self.register_lmstudio_spinner(toolbar, spinner_key or self.document_lmstudio_spinner_key(document_index))
        ttk.Label(toolbar, textvariable=self.message_attachment_status_var).pack(side=tk.LEFT, padx=(0, 6))

    def add_result_destination_controls(self, toolbar: ttk.Frame) -> None:
        ttk.Label(toolbar, text="Destination du résultat").pack(side=tk.LEFT, padx=(12, 4))
        combo = ttk.Combobox(
            toolbar,
            textvariable=self.result_destination_var,
            values=RESULT_DESTINATION_CHOICES,
            width=17,
            state="readonly",
        )
        combo.pack(side=tk.LEFT, padx=(0, 6))
        combo.bind("<<ComboboxSelected>>", lambda _event: self.on_result_destination_changed())

        if not hasattr(self, "result_destination_combos"):
            self.result_destination_combos = []
        self.result_destination_combos.append(combo)

    def _add_prompt_tab(self, *, parent_notebook: ttk.Notebook | None = None) -> tk.Text:
        notebook = parent_notebook or self.notebook
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text="Prompt")

        toolbar = ttk.Frame(frame)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
        self.prompt_combo = ttk.Combobox(toolbar, textvariable=self.prompt_var, width=38, state="readonly")
        self.prompt_combo.pack(side=tk.LEFT, padx=(0, 6))
        self.prompt_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_prompt_selected())

        for label, command in (
            ("Nouveau", self.new_prompt),
            ("Enregistrer", self.save_prompt),
            ("Dupliquer", self.duplicate_prompt),
            ("Supprimer", self.delete_prompt),
            ("Définir par défaut", self.set_default_prompt),
        ):
            ttk.Button(toolbar, text=label, command=command).pack(side=tk.LEFT, padx=(0, 6))

        text = self.create_text_widget(frame, wrap=tk.WORD, undo=True, height=10)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(frame, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.configure(yscrollcommand=scrollbar.set)
        return text

    def _add_secondary_prompt_tab(self, *, parent_notebook: ttk.Notebook | None = None) -> tk.Text:
        notebook = parent_notebook or self.notebook
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text="Prompt")

        toolbar = ttk.Frame(frame)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
        ttk.Checkbutton(
            toolbar,
            text="Activer Prompt 2",
            variable=self.secondary_enabled_var,
            command=self.save_secondary_analysis_settings,
        ).pack(side=tk.LEFT, padx=(0, 8))

        self.secondary_prompt_combo = ttk.Combobox(
            toolbar,
            textvariable=self.secondary_prompt_var,
            width=38,
            state="readonly",
        )
        self.secondary_prompt_combo.pack(side=tk.LEFT, padx=(0, 6))
        self.secondary_prompt_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_secondary_prompt_selected())

        for label, command in (
            ("Nouveau", self.new_secondary_prompt),
            ("Enregistrer", self.save_secondary_prompt),
            ("Dupliquer", self.duplicate_secondary_prompt),
            ("Supprimer", self.delete_secondary_prompt),
            ("Définir comme prompt 2 par défaut", self.set_default_secondary_prompt),
            ("Prévisualiser Message 2", self.preview_secondary_message),
            ("Lancer Prompt 2 maintenant", self.run_secondary_analysis_manual),
        ):
            ttk.Button(toolbar, text=label, command=command).pack(side=tk.LEFT, padx=(0, 6))

        text = self.create_text_widget(frame, wrap=tk.WORD, undo=True, height=10)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(frame, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.configure(yscrollcommand=scrollbar.set)
        return text

    def _add_tertiary_prompt_tab(self, *, parent_notebook: ttk.Notebook | None = None) -> tk.Text:
        notebook = parent_notebook or self.notebook
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text="Prompt")

        toolbar = ttk.Frame(frame)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
        ttk.Checkbutton(
            toolbar,
            text="Activer Prompt 3",
            variable=self.tertiary_enabled_var,
            command=self.save_tertiary_analysis_settings,
        ).pack(side=tk.LEFT, padx=(0, 8))
        self.tertiary_prompt_combo = ttk.Combobox(
            toolbar,
            textvariable=self.tertiary_prompt_var,
            width=38,
            state="readonly",
        )
        self.tertiary_prompt_combo.pack(side=tk.LEFT, padx=(0, 6))
        self.tertiary_prompt_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_tertiary_prompt_selected())

        for label, command in (
            ("Nouveau", self.new_tertiary_prompt),
            ("Enregistrer", self.save_tertiary_prompt),
            ("Dupliquer", self.duplicate_tertiary_prompt),
            ("Supprimer", self.delete_tertiary_prompt),
            ("Définir comme prompt 3 par défaut", self.set_default_tertiary_prompt),
            ("Prévisualiser Message 3", self.preview_tertiary_message),
            ("Lancer Prompt 3 maintenant", self.run_tertiary_analysis_manual),
        ):
            ttk.Button(toolbar, text=label, command=command).pack(side=tk.LEFT, padx=(0, 6))

        text = self.create_text_widget(frame, wrap=tk.WORD, undo=True, height=10)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(frame, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.configure(yscrollcommand=scrollbar.set)
        return text

    def _add_document_now_prompt_tab(self, *, parent_notebook: ttk.Notebook | None = None) -> tk.Text:
        notebook = parent_notebook or self.notebook
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text="Prompt")

        toolbar = ttk.Frame(frame)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
        self.document_now_prompt_combo = ttk.Combobox(
            toolbar,
            textvariable=self.document_now_prompt_var,
            width=38,
            state="readonly",
        )
        self.document_now_prompt_combo.pack(side=tk.LEFT, padx=(0, 6))
        self.document_now_prompt_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_document_now_prompt_selected())

        for label, command in (
            ("Nouveau", self.new_document_now_prompt),
            ("Enregistrer", self.save_document_now_prompt),
            ("Dupliquer", self.duplicate_document_now_prompt),
            ("Supprimer", self.delete_document_now_prompt),
            ("Défaut", self.set_default_document_now_prompt),
            ("Prévisualiser message", self.preview_document_now_message),
            ("Document maintenant", self.document_now_checkpoint),
        ):
            button_style = "Accent.TButton" if label == "Document maintenant" else "TButton"
            ttk.Button(toolbar, text=label, command=command, style=button_style).pack(side=tk.LEFT, padx=(0, 6))

        default_frame = ttk.LabelFrame(frame, text="Prompt par défaut ajouté au Document maintenant", padding=6)
        default_frame.pack(side=tk.TOP, fill=tk.BOTH, pady=(0, 6))
        default_toolbar = ttk.Frame(default_frame)
        default_toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
        ttk.Button(default_toolbar, text="Enregistrer défaut", command=self.save_document_now_default_prompt).pack(
            side=tk.LEFT,
            padx=(0, 6),
        )
        ttk.Button(default_toolbar, text="Réinitialiser défaut", command=self.reset_document_now_default_prompt).pack(
            side=tk.LEFT,
            padx=(0, 6),
        )
        default_body = ttk.Frame(default_frame)
        default_body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.document_now_default_prompt_text = self.create_text_widget(default_body, wrap=tk.WORD, undo=True, height=4)
        self.document_now_default_prompt_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        default_scrollbar = ttk.Scrollbar(default_body, command=self.document_now_default_prompt_text.yview)
        default_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.document_now_default_prompt_text.configure(yscrollcommand=default_scrollbar.set)
        self.set_text(
            self.document_now_default_prompt_text,
            str(self.config.setdefault("document_now", {}).get("default_prompt_prefix") or DEFAULT_DOCUMENT_NOW_PROMPT_PREFIX),
        )

        prompt_frame = ttk.LabelFrame(frame, text="Prompt sélectionné", padding=6)
        prompt_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        text = self.create_text_widget(prompt_frame, wrap=tk.WORD, undo=True, height=10)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(prompt_frame, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.configure(yscrollcommand=scrollbar.set)
        return text

    def _add_whisper_initial_prompt_tab(self) -> tk.Text:
        frame = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(frame, text="Prompt Whisper")

        toolbar = ttk.Frame(frame)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
        self.whisper_initial_prompt_combo = ttk.Combobox(
            toolbar,
            textvariable=self.whisper_initial_prompt_var,
            width=38,
            state="readonly",
        )
        self.whisper_initial_prompt_combo.pack(side=tk.LEFT, padx=(0, 6))
        self.whisper_initial_prompt_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self.on_whisper_initial_prompt_selected(),
        )

        for label, command in (
            ("Nouveau", self.new_whisper_initial_prompt),
            ("Enregistrer", self.save_whisper_initial_prompt),
            ("Dupliquer", self.duplicate_whisper_initial_prompt),
            ("Supprimer", self.delete_whisper_initial_prompt),
            ("Activer", self.activate_selected_whisper_initial_prompt),
            ("Restaurer le prompt par défaut", self.restore_default_whisper_medical_prompt),
        ):
            ttk.Button(toolbar, text=label, command=command).pack(side=tk.LEFT, padx=(0, 6))

        options = ttk.Frame(frame)
        options.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
        ttk.Checkbutton(
            options,
            text="Ajouter automatiquement le contexte WEDA au prompt Whisper",
            variable=self.whisper_include_weda_context_var,
            command=self.save_medical_transcription_settings,
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(
            options,
            text="Utiliser les hotwords dynamiques WEDA",
            variable=self.whisper_use_dynamic_hotwords_var,
            command=self.save_medical_transcription_settings,
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(
            options,
            text="Appliquer les corrections locales très fiables",
            variable=self.whisper_apply_corrections_var,
            command=self.save_medical_transcription_settings,
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Button(options, text="Diagnostic Whisper", command=self.show_whisper_diagnostic_window).pack(side=tk.RIGHT)

        prompt_frame = ttk.LabelFrame(frame, text="Prompt médical Whisper (base fixe)", padding=6)
        prompt_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 6))
        text = self.create_text_widget(prompt_frame, wrap=tk.WORD, undo=True, height=7)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(prompt_frame, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.configure(yscrollcommand=scrollbar.set)

        lexicon_frame = ttk.LabelFrame(frame, text="Lexique médical local permanent (un terme par ligne)", padding=6)
        lexicon_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=False)
        self.permanent_hotwords_text = self.create_text_widget(lexicon_frame, wrap=tk.WORD, undo=True, height=5)
        self.permanent_hotwords_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        lexicon_scrollbar = ttk.Scrollbar(lexicon_frame, command=self.permanent_hotwords_text.yview)
        lexicon_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.permanent_hotwords_text.configure(yscrollcommand=lexicon_scrollbar.set)
        permanent = self.config.get("medical_transcription", {}).get(
            "permanent_hotwords", list(DEFAULT_PERMANENT_MEDICAL_HOTWORDS)
        )
        self.set_text(self.permanent_hotwords_text, "\n".join(parse_permanent_hotwords(permanent)))
        return text

    def _add_transcription_corrections_tab(self, *, parent_notebook: ttk.Notebook | None = None) -> tk.Text:
        notebook = parent_notebook or self.notebook
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text="Transcription corrigée")
        toolbar = ttk.Frame(frame)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
        for label, command in (
            ("Repartir de la transcription brute", self.reset_corrected_transcription),
            ("Comparer les corrections", self.review_transcription_corrections),
            ("Valider explicitement", self.validate_transcription_corrections),
            ("Rejeter", self.reject_transcription_corrections),
        ):
            ttk.Button(toolbar, text=label, command=command).pack(side=tk.LEFT, padx=(0, 6))
        text_frame = ttk.LabelFrame(frame, text="Version corrigée, fidèle et non reformulée", padding=6)
        text_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 6))
        text = self.create_text_widget(text_frame, wrap=tk.WORD, undo=True, height=8)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(text_frame, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.configure(yscrollcommand=scrollbar.set)
        review_frame = ttk.LabelFrame(frame, text="Différences proposées — aucune n’est apprise sans validation", padding=6)
        review_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.correction_review_text = self.create_text_widget(review_frame, wrap=tk.WORD, undo=False, height=6)
        self.correction_review_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        review_scrollbar = ttk.Scrollbar(review_frame, command=self.correction_review_text.yview)
        review_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.correction_review_text.configure(yscrollcommand=review_scrollbar.set, state=tk.DISABLED)
        return text

    def _add_abbreviations_tab(self) -> tk.Text:
        frame = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(frame, text="Abréviations")

        toolbar = ttk.Frame(frame)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
        for label, command in (
            ("Enregistrer", self.save_abbreviations),
            ("Recharger", self.load_abbreviations_text),
            ("Appliquer substitutions sûres", self.apply_safe_abbreviations_to_transcription),
        ):
            ttk.Button(toolbar, text=label, command=command).pack(side=tk.LEFT, padx=(0, 6))

        text = self.create_text_widget(frame, wrap=tk.NONE, undo=True, height=10)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        y_scrollbar = ttk.Scrollbar(frame, command=text.yview)
        y_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        x_scrollbar = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=text.xview)
        x_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        text.configure(yscrollcommand=y_scrollbar.set, xscrollcommand=x_scrollbar.set)
        return text

    def _add_pdf_structured_tab(self) -> ttk.Frame:
        frame = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(frame, text="PDF structurés")

        toolbar = ttk.Frame(frame)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))

        pdf_action_spinner_keys = {
            "Remplir PDF": PDF_FILL_SPINNER_KEY,
        }
        for label, command in (
            ("Importer modèle PDF", self.import_pdf_template),
            ("Renommer", self.rename_pdf_template),
            ("Supprimer", self.delete_pdf_template),
            ("Enregistrer champ", self.save_selected_pdf_field),
            ("Remplir PDF", self.fill_pdf_with_gemma),
            ("Copier JSON", self.copy_pdf_json),
            ("Ouvrir PDF final", self.open_last_pdf_output),
            ("Purger historique local", self.purge_local_history),
        ):
            ttk.Button(
                toolbar,
                text=label,
                command=command,
                style="Accent.TButton" if label == "Remplir PDF" else "TButton",
            ).pack(side=tk.LEFT, padx=(0, 6))
            spinner_key = pdf_action_spinner_keys.get(label)
            if spinner_key:
                self.register_lmstudio_spinner(toolbar, spinner_key)

        selector = ttk.Frame(frame)
        selector.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
        ttk.Label(selector, text="Modèle").pack(side=tk.LEFT)
        self.pdf_template_combo = ttk.Combobox(
            selector,
            textvariable=self.pdf_template_var,
            width=34,
            state="readonly",
        )
        self.pdf_template_combo.pack(side=tk.LEFT, padx=(4, 12))
        self.pdf_template_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_pdf_template_selected())

        ttk.Label(selector, text="Prompt PDF").pack(side=tk.LEFT)
        self.pdf_prompt_combo = ttk.Combobox(
            selector,
            textvariable=self.pdf_prompt_var,
            width=34,
            state="readonly",
        )
        self.pdf_prompt_combo.pack(side=tk.LEFT, padx=(4, 12))
        self.pdf_prompt_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_pdf_prompt_selected())

        for label, command in (
            ("Nouveau", self.new_pdf_prompt),
            ("Enregistrer", self.save_pdf_prompt),
            ("Dupliquer", self.duplicate_pdf_prompt),
            ("Supprimer", self.delete_pdf_prompt),
            ("Défaut", self.set_default_pdf_prompt),
        ):
            ttk.Button(selector, text=label, command=command).pack(side=tk.LEFT, padx=(0, 6))

        ttk.Label(selector, text="Source PDF").pack(side=tk.LEFT)
        self.pdf_source_combo = ttk.Combobox(
            selector,
            textvariable=self.pdf_source_var,
            values=PDF_SOURCE_CHOICES,
            width=22,
            state="readonly",
        )
        self.pdf_source_combo.pack(side=tk.LEFT, padx=(4, 12))
        self.pdf_source_combo.bind("<<ComboboxSelected>>", lambda _event: self.save_pdf_source_preference())

        self.pdf_description_var = tk.StringVar(value="")
        ttk.Label(selector, text="Description").pack(side=tk.LEFT)
        self.pdf_description_entry = ttk.Entry(selector, textvariable=self.pdf_description_var, width=42)
        self.pdf_description_entry.pack(side=tk.LEFT, padx=(4, 6))
        self.pdf_description_entry.bind("<FocusOut>", lambda _event: self.save_pdf_template_description())
        self.pdf_description_entry.bind("<Return>", lambda _event: self.save_pdf_template_description())

        pdf_prompt_frame = ttk.LabelFrame(frame, text="Prompt PDF sélectionné", padding=6)
        pdf_prompt_frame.pack(side=tk.TOP, fill=tk.BOTH, pady=(0, 6))
        self.pdf_prompt_text = self.create_text_widget(pdf_prompt_frame, wrap=tk.WORD, undo=True, height=7)
        self.pdf_prompt_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        pdf_prompt_scroll = ttk.Scrollbar(pdf_prompt_frame, command=self.pdf_prompt_text.yview)
        pdf_prompt_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.pdf_prompt_text.configure(yscrollcommand=pdf_prompt_scroll.set)

        body = ttk.PanedWindow(frame, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True)

        fields_frame = ttk.Frame(body, padding=(0, 0, 8, 0))
        body.add(fields_frame, weight=1)
        ttk.Label(fields_frame, text="Champs détectés").pack(anchor=tk.W)
        self.pdf_fields_tree = ttk.Treeview(
            fields_frame,
            columns=("label", "type", "required", "page", "description"),
            show="tree headings",
            height=12,
        )
        self.pdf_fields_tree.heading("#0", text="Nom technique")
        self.pdf_fields_tree.heading("label", text="Libellé")
        self.pdf_fields_tree.heading("type", text="Type")
        self.pdf_fields_tree.heading("required", text="Req.")
        self.pdf_fields_tree.heading("page", text="Page")
        self.pdf_fields_tree.heading("description", text="Description")
        self.pdf_fields_tree.column("#0", width=170, stretch=True)
        self.pdf_fields_tree.column("label", width=160, stretch=True)
        self.pdf_fields_tree.column("type", width=80, stretch=False)
        self.pdf_fields_tree.column("required", width=50, stretch=False)
        self.pdf_fields_tree.column("page", width=50, stretch=False)
        self.pdf_fields_tree.column("description", width=220, stretch=True)
        self.pdf_fields_tree.pack(fill=tk.BOTH, expand=True)
        self.pdf_fields_tree.bind("<<TreeviewSelect>>", lambda _event: self.on_pdf_field_selected())

        edit = ttk.LabelFrame(fields_frame, text="Libellé du champ", padding=6)
        edit.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(edit, textvariable=self.pdf_field_name_var).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 4))
        ttk.Label(edit, text="Libellé").grid(row=1, column=0, sticky="w")
        ttk.Entry(edit, textvariable=self.pdf_field_label_var, width=32).grid(row=1, column=1, sticky="ew", padx=(4, 8))
        ttk.Checkbutton(edit, text="Requis", variable=self.pdf_field_required_var).grid(row=1, column=2, sticky="w")
        ttk.Label(edit, text="Description").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(edit, textvariable=self.pdf_field_description_var, width=56).grid(
            row=2,
            column=1,
            columnspan=3,
            sticky="ew",
            padx=(4, 0),
            pady=(4, 0),
        )
        edit.columnconfigure(1, weight=1)

        right = ttk.Frame(body)
        body.add(right, weight=1)

        json_frame = ttk.LabelFrame(right, text="JSON proposé par Gemma", padding=6)
        json_frame.pack(fill=tk.BOTH, expand=True)
        self.pdf_json_text = self.create_text_widget(json_frame, wrap=tk.NONE, undo=True, height=8)
        self.pdf_json_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        json_scroll = ttk.Scrollbar(json_frame, command=self.pdf_json_text.yview)
        json_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.pdf_json_text.configure(yscrollcommand=json_scroll.set)

        preview_frame = ttk.LabelFrame(right, text="Prévisualisation avant remplissage", padding=6)
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.pdf_preview_tree = ttk.Treeview(
            preview_frame,
            columns=("label", "value", "status"),
            show="tree headings",
            height=10,
        )
        self.pdf_preview_tree.heading("#0", text="Champ PDF")
        self.pdf_preview_tree.heading("label", text="Libellé")
        self.pdf_preview_tree.heading("value", text="Valeur proposée")
        self.pdf_preview_tree.heading("status", text="Statut")
        self.pdf_preview_tree.column("#0", width=160, stretch=True)
        self.pdf_preview_tree.column("label", width=160, stretch=True)
        self.pdf_preview_tree.column("value", width=240, stretch=True)
        self.pdf_preview_tree.column("status", width=130, stretch=True)
        self.pdf_preview_tree.pack(fill=tk.BOTH, expand=True)
        self.pdf_preview_tree.bind("<<TreeviewSelect>>", lambda _event: self.on_pdf_preview_selected())

        value_edit = ttk.Frame(preview_frame)
        value_edit.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(value_edit, textvariable=self.pdf_preview_field_var, width=24).pack(side=tk.LEFT)
        ttk.Entry(value_edit, textvariable=self.pdf_preview_value_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        ttk.Button(value_edit, text="Appliquer valeur", command=self.apply_pdf_preview_value).pack(side=tk.LEFT)

        return frame

    def ensure_pdf_config(self) -> None:
        defaults = {
            "templates_dir": "data/pdf_templates",
            "outputs_dir": "data/pdf_outputs",
            "open_after_export": True,
            "require_manual_validation": True,
            "allow_pdf_without_fields": False,
            "default_prompt_id": "pdf_form_fill",
            "preferred_source": "Contexte + transcription",
            "max_tokens": 8192,
        }
        pdf_config = self.config.setdefault("pdf", {})
        changed = False
        for key, value in defaults.items():
            if key not in pdf_config:
                pdf_config[key] = value
                changed = True
        if changed:
            try:
                save_json(BASE_DIR / "config.json", self.config)
            except Exception:
                pass

    def ensure_message_composition_config(self) -> None:
        message_config = self.config.setdefault("message_composition", {})
        changed = False
        for key, value in DEFAULT_MESSAGE_COMPOSITION_CONFIG.items():
            if key not in message_config:
                message_config[key] = value
                changed = True
        if changed:
            try:
                save_json(BASE_DIR / "config.json", self.config)
            except Exception:
                pass

    def ensure_secondary_analysis_config(self) -> None:
        existing = self.config.get("secondary_analysis", {})
        normalized = normalize_secondary_analysis_config(existing if isinstance(existing, dict) else {})
        changed = existing != normalized
        self.config["secondary_analysis"] = normalized
        if changed:
            try:
                save_json(BASE_DIR / "config.json", self.config)
            except Exception:
                pass

    def ensure_tertiary_analysis_config(self) -> None:
        existing = self.config.get("tertiary_analysis", {})
        normalized = normalize_tertiary_analysis_config(existing if isinstance(existing, dict) else {})
        changed = existing != normalized
        self.config["tertiary_analysis"] = normalized
        if changed:
            try:
                save_json(BASE_DIR / "config.json", self.config)
            except Exception:
                pass

    def resolve_app_path(self, value, fallback: str) -> Path:
        raw = str(value or fallback)
        path = Path(raw)
        return path if path.is_absolute() else BASE_DIR / path

    def ensure_pdf_form_fill_prompt(self) -> None:
        pdf_config = self.config.setdefault("pdf", {})
        prompt_id = str(pdf_config.get("default_prompt_id") or "pdf_form_fill")
        prompt = self.prompt_manager.get(prompt_id) or self.prompt_manager.get_by_name("Remplissage PDF structuré")
        if prompt is None:
            self.prompt_manager.create(
                "Remplissage PDF structuré",
                DEFAULT_PDF_FORM_FILL_PROMPT,
                is_default=True,
                prompt_type="pdf_form_fill",
                prompt_id=prompt_id,
            )
            return
        if prompt.prompt_type != "pdf_form_fill":
            self.prompt_manager.update(prompt.id, prompt_type="pdf_form_fill")
        if (
            prompt.id == "pdf_form_fill"
            and "Source préférée préparée pour le PDF" in prompt.content
            and "RÉSULTAT LM STUDIO EXISTANT SI DISPONIBLE" in prompt.content
        ):
            prompt = self.prompt_manager.update(prompt.id, content=DEFAULT_PDF_FORM_FILL_PROMPT)
        pdf_config["default_prompt_id"] = prompt.id
        try:
            save_json(BASE_DIR / "config.json", self.config)
        except Exception:
            pass

    def ensure_secondary_analysis_prompt(self) -> None:
        secondary_config = self.config.setdefault(
            "secondary_analysis",
            dict(DEFAULT_SECONDARY_ANALYSIS_CONFIG),
        )
        prompt = self.prompt_manager.get(SECONDARY_ANALYSIS_PROMPT_ID)
        if prompt is None:
            prompt = self.prompt_manager.create(
                SECONDARY_ANALYSIS_PROMPT_NAME,
                DEFAULT_SECONDARY_ANALYSIS_PROMPT,
                is_default=False,
                prompt_type="generic",
                prompt_id=SECONDARY_ANALYSIS_PROMPT_ID,
            )
        elif prompt.prompt_type != "generic":
            prompt = self.prompt_manager.update(prompt.id, prompt_type="generic")

        default_prompt_id = str(secondary_config.get("default_prompt_id") or "")
        selected = self.prompt_manager.get(default_prompt_id)
        if selected is None or selected.prompt_type != "generic":
            secondary_config["default_prompt_id"] = prompt.id
            try:
                save_json(BASE_DIR / "config.json", self.config)
            except Exception:
                pass

    def ensure_tertiary_analysis_prompt(self) -> None:
        tertiary_config = self.config.setdefault(
            "tertiary_analysis",
            dict(DEFAULT_TERTIARY_ANALYSIS_CONFIG),
        )
        prompt = self.prompt_manager.get(TERTIARY_ANALYSIS_PROMPT_ID)
        if prompt is None:
            prompt = self.prompt_manager.create(
                TERTIARY_ANALYSIS_PROMPT_NAME,
                DEFAULT_TERTIARY_ANALYSIS_PROMPT,
                is_default=False,
                prompt_type="generic",
                prompt_id=TERTIARY_ANALYSIS_PROMPT_ID,
            )
        elif prompt.prompt_type != "generic":
            prompt = self.prompt_manager.update(prompt.id, prompt_type="generic")

        default_prompt_id = str(tertiary_config.get("default_prompt_id") or "")
        selected = self.prompt_manager.get(default_prompt_id)
        if selected is None or selected.prompt_type != "generic":
            tertiary_config["default_prompt_id"] = prompt.id
            try:
                save_json(BASE_DIR / "config.json", self.config)
            except Exception:
                pass

    def ensure_document_now_prompt(self) -> None:
        document_now_config = self.config.setdefault("document_now", {})
        changed = False
        if "default_prompt_prefix" not in document_now_config:
            document_now_config["default_prompt_prefix"] = DEFAULT_DOCUMENT_NOW_PROMPT_PREFIX
            changed = True
        prompt = self.prompt_manager.get(DOCUMENT_NOW_PROMPT_ID) or self.prompt_manager.get_by_name(DOCUMENT_NOW_PROMPT_NAME)
        if prompt is None:
            prompt = self.prompt_manager.create(
                DOCUMENT_NOW_PROMPT_NAME,
                DEFAULT_DOCUMENT_NOW_PROMPT,
                is_default=False,
                prompt_type="generic",
                prompt_id=DOCUMENT_NOW_PROMPT_ID,
            )
        elif prompt.prompt_type != "generic":
            prompt = self.prompt_manager.update(prompt.id, prompt_type="generic")

        default_prompt_id = str(document_now_config.get("default_prompt_id") or "")
        selected = self.prompt_manager.get(default_prompt_id)
        if selected is None or selected.prompt_type != "generic":
            document_now_config["default_prompt_id"] = prompt.id
            changed = True
        if changed:
            try:
                save_json(BASE_DIR / "config.json", self.config)
            except Exception:
                pass

    def on_result_destination_changed(self) -> None:
        self.capture_ui_selection_settings()
        self.write_runtime_config("result_destination")
        if self.result_destination_var.get() == "PDF structuré" and hasattr(self, "pdf_tab_frame"):
            self.notebook.select(self.pdf_tab_frame)

    def _refresh_pdf_prompt_combo(self, selected_id: str | None = None) -> None:
        prompts = self.prompt_manager.list_prompts(prompt_type="pdf_form_fill")
        if not prompts:
            self.ensure_pdf_form_fill_prompt()
            prompts = self.prompt_manager.list_prompts(prompt_type="pdf_form_fill")
        self.pdf_prompt_name_to_id = {prompt.name: prompt.id for prompt in prompts}
        if hasattr(self, "pdf_prompt_combo"):
            self.pdf_prompt_combo["values"] = [prompt.name for prompt in prompts]
        selected = self.prompt_manager.get(selected_id) if selected_id else None
        if selected is None:
            selected = self.prompt_manager.get(str(self.config.get("pdf", {}).get("last_prompt_id") or ""))
        if selected is None:
            selected = self.prompt_manager.get(str(self.config.get("pdf", {}).get("default_prompt_id") or ""))
        if selected is None or selected.prompt_type != "pdf_form_fill":
            selected = self.prompt_manager.get_default("pdf_form_fill")
        if selected:
            self.pdf_prompt_var.set(selected.name)
            self.load_selected_pdf_prompt()

    def current_pdf_prompt_id(self) -> str:
        return self.pdf_prompt_name_to_id.get(self.pdf_prompt_var.get(), "")

    def on_pdf_prompt_selected(self) -> None:
        self.load_selected_pdf_prompt()
        self.capture_pdf_selection_settings()
        self.write_runtime_config("pdf_prompt_selection")
        self.save_pdf_template_prompt()

    def load_selected_pdf_prompt(self) -> None:
        prompt = self.prompt_manager.get(self.current_pdf_prompt_id())
        if not prompt:
            return
        if hasattr(self, "pdf_prompt_text"):
            self.set_text(self.pdf_prompt_text, prompt.content)
        marker = " par défaut" if prompt.id == str(self.config.get("pdf", {}).get("default_prompt_id") or "") else ""
        self.pdf_status_var.set(f"PDF: prompt {prompt.name}{marker}")

    def new_pdf_prompt(self) -> None:
        name = simpledialog.askstring("Nouveau prompt PDF", "Nom du prompt PDF :", parent=self.root)
        if not name:
            return
        prompt = self.prompt_manager.create(name, self.get_text(self.pdf_prompt_text), prompt_type="pdf_form_fill")
        self._refresh_pdf_prompt_combo(prompt.id)
        self.save_pdf_template_prompt()

    def save_pdf_prompt(self) -> None:
        prompt_id = self.current_pdf_prompt_id()
        if not prompt_id:
            return
        prompt = self.prompt_manager.update(prompt_id, content=self.get_text(self.pdf_prompt_text), prompt_type="pdf_form_fill")
        self._refresh_pdf_prompt_combo(prompt.id)
        self.save_pdf_template_prompt()
        self.pdf_status_var.set(f"PDF: prompt enregistré ({prompt.name})")

    def duplicate_pdf_prompt(self) -> None:
        prompt_id = self.current_pdf_prompt_id()
        if not prompt_id:
            return
        source = self.prompt_manager.get(prompt_id)
        default_name = f"{source.name} - copie" if source else "Prompt PDF - copie"
        name = simpledialog.askstring("Dupliquer prompt PDF", "Nom de la copie :", initialvalue=default_name, parent=self.root)
        prompt = self.prompt_manager.create(
            name or default_name,
            self.get_text(self.pdf_prompt_text),
            prompt_type="pdf_form_fill",
        )
        self._refresh_pdf_prompt_combo(prompt.id)
        self.save_pdf_template_prompt()

    def delete_pdf_prompt(self) -> None:
        prompt_id = self.current_pdf_prompt_id()
        if not prompt_id:
            return
        if not messagebox.askyesno("Supprimer prompt PDF", "Supprimer ce prompt PDF ?", parent=self.root):
            return
        try:
            self.prompt_manager.delete(prompt_id)
            pdf_config = self.config.setdefault("pdf", {})
            if pdf_config.get("default_prompt_id") == prompt_id:
                fallback = self.prompt_manager.get_default("pdf_form_fill")
                pdf_config["default_prompt_id"] = fallback.id if fallback else "pdf_form_fill"
                save_json(BASE_DIR / "config.json", self.config)
            self._refresh_pdf_prompt_combo()
            self.save_pdf_template_prompt()
        except Exception as exc:
            messagebox.showerror("Prompt PDF", str(exc), parent=self.root)

    def set_default_pdf_prompt(self) -> None:
        prompt_id = self.current_pdf_prompt_id()
        if not prompt_id:
            return
        prompt = self.prompt_manager.get(prompt_id)
        if not prompt:
            return
        self.prompt_manager.set_default(prompt.id)
        pdf_config = self.config.setdefault("pdf", {})
        pdf_config["default_prompt_id"] = prompt.id
        pdf_config["last_prompt_id"] = prompt.id
        try:
            save_json(BASE_DIR / "config.json", self.config)
        except Exception as exc:
            self.log_debug("warning", "pdf", "pdf_default_prompt_save_error", str(exc))
        self._refresh_pdf_prompt_combo(prompt.id)
        self.save_pdf_template_prompt()

    def refresh_pdf_template_combo(self, selected_id: str | None = None) -> None:
        if not hasattr(self, "pdf_template_combo"):
            return
        templates = self.pdf_template_manager.list_templates()
        label_counts: dict[str, int] = {}
        for item in templates:
            label = str(item.get("name") or item.get("id") or "Modèle PDF")
            label_counts[label] = label_counts.get(label, 0) + 1

        self.pdf_template_name_to_id = {}
        labels = []
        for item in templates:
            name = str(item.get("name") or item.get("id") or "Modèle PDF")
            label = f"{name} ({item.get('id')})" if label_counts.get(name, 0) > 1 else name
            labels.append(label)
            self.pdf_template_name_to_id[label] = str(item.get("id") or "")

        self.pdf_template_combo["values"] = labels
        if not labels:
            self.pdf_template_var.set("")
            self.pdf_current_template_id = ""
            self.pdf_status_var.set("PDF: aucun modèle")
            self.render_pdf_fields([])
            self.render_pdf_preview()
            return

        template_id_to_select = selected_id or str(self.config.get("pdf", {}).get("last_template_id") or "")
        selected_label = next(
            (label for label, template_id in self.pdf_template_name_to_id.items() if template_id == template_id_to_select),
            labels[0],
        )
        self.pdf_template_var.set(selected_label)
        self.load_selected_pdf_template()

    def current_pdf_template_id(self) -> str:
        return self.pdf_template_name_to_id.get(self.pdf_template_var.get(), "")

    def on_pdf_template_selected(self) -> None:
        self.load_selected_pdf_template()
        self.capture_pdf_selection_settings()
        self.write_runtime_config("pdf_template_selection")

    def load_selected_pdf_template(self) -> None:
        template_id = self.current_pdf_template_id()
        if not template_id:
            return
        try:
            metadata = self.pdf_template_manager.get_template(template_id) or {}
            fields = self.pdf_template_manager.load_fields(template_id)
        except Exception as exc:
            self.pdf_status_var.set("PDF: erreur modèle")
            messagebox.showerror("PDF structuré", str(exc), parent=self.root)
            return

        self.pdf_current_template_id = template_id
        self.pdf_current_metadata = metadata
        self.pdf_current_fields = fields
        self.pdf_current_schema = build_json_schema(fields)
        self.pdf_current_values = {}
        self.pdf_current_issues = []
        self.pdf_last_output_path = ""
        self.pdf_description_var.set(str(metadata.get("description") or ""))
        prompt_id = str(metadata.get("default_prompt_id") or self.config.get("pdf", {}).get("default_prompt_id") or "")
        self._refresh_pdf_prompt_combo(prompt_id)
        self.render_pdf_fields(fields)
        self.set_text(self.pdf_json_text, "")
        self.render_pdf_preview()
        self.pdf_status_var.set(f"PDF: {metadata.get('name', template_id)} ({len(fields)} champ(s))")

    def import_pdf_template(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Importer un modèle PDF structuré",
            filetypes=[("PDF", "*.pdf"), ("Tous les fichiers", "*.*")],
        )
        if not path:
            return
        name = simpledialog.askstring("Nom du modèle", "Nom du modèle PDF :", parent=self.root)
        if not name:
            name = Path(path).stem
        try:
            metadata = self.pdf_template_manager.import_template(
                path,
                name=name,
                default_prompt_id=self.current_pdf_prompt_id() or self.config.get("pdf", {}).get("default_prompt_id", "pdf_form_fill"),
            )
        except Exception as exc:
            messagebox.showerror("Import PDF", str(exc), parent=self.root)
            self.pdf_status_var.set("PDF: import impossible")
            return
        self.refresh_pdf_template_combo(str(metadata.get("id") or ""))
        self.pdf_status_var.set(f"PDF: modèle importé ({metadata.get('field_count', 0)} champ(s))")
        self.log_debug(
            "info",
            "pdf",
            "pdf_template_imported",
            "Modèle PDF importé.",
            {"template_id": metadata.get("id"), "field_count": metadata.get("field_count", 0)},
        )

    def rename_pdf_template(self) -> None:
        template_id = self.current_pdf_template_id()
        if not template_id:
            return
        current = self.pdf_current_metadata.get("name") or template_id
        name = simpledialog.askstring("Renommer modèle PDF", "Nouveau nom :", initialvalue=current, parent=self.root)
        if not name:
            return
        try:
            metadata = self.pdf_template_manager.rename_template(template_id, name)
            self.refresh_pdf_template_combo(str(metadata.get("id") or template_id))
        except Exception as exc:
            messagebox.showerror("PDF structuré", str(exc), parent=self.root)

    def delete_pdf_template(self) -> None:
        template_id = self.current_pdf_template_id()
        if not template_id:
            return
        name = self.pdf_current_metadata.get("name") or template_id
        if not messagebox.askyesno(
            "Supprimer modèle PDF",
            f"Supprimer le modèle « {name} » ?\nLe PDF original sauvegardé localement sera supprimé.",
            parent=self.root,
        ):
            return
        try:
            self.pdf_template_manager.delete_template(template_id)
            self.refresh_pdf_template_combo()
        except Exception as exc:
            messagebox.showerror("PDF structuré", str(exc), parent=self.root)

    def save_pdf_template_description(self) -> None:
        template_id = self.current_pdf_template_id()
        if not template_id:
            return
        try:
            self.pdf_current_metadata = self.pdf_template_manager.update_template_metadata(
                template_id,
                {"description": self.pdf_description_var.get()},
            )
        except Exception as exc:
            self.log_debug("warning", "pdf", "pdf_template_description_save_error", str(exc))

    def save_pdf_template_prompt(self) -> None:
        template_id = self.current_pdf_template_id()
        prompt_id = self.current_pdf_prompt_id()
        if not template_id or not prompt_id:
            return
        try:
            self.pdf_current_metadata = self.pdf_template_manager.update_template_metadata(
                template_id,
                {"default_prompt_id": prompt_id},
            )
            self.pdf_status_var.set("PDF: prompt associé au modèle")
        except Exception as exc:
            self.log_debug("warning", "pdf", "pdf_template_prompt_save_error", str(exc))

    def save_pdf_source_preference(self) -> None:
        self.capture_pdf_selection_settings()
        try:
            save_json(BASE_DIR / "config.json", self.config)
        except Exception as exc:
            self.log_debug("warning", "pdf", "pdf_source_preference_save_error", str(exc))

    def build_pdf_context_transcription_source_text(self, *, transcription_only: bool = False) -> str:
        weda_context = self.get_text(self.context_text).strip()
        transcription = self.get_clean_transcription_text()
        parts = []
        if not transcription_only and weda_context:
            parts.append("CONTEXTE WEDA :\n" + weda_context)
        if transcription:
            parts.append("TRANSCRIPTION :\n" + transcription)
        return "\n\n".join(parts).strip()

    def build_pdf_preferred_source_text(self) -> str:
        result_1 = self.get_text(self.result_text).strip()
        result_2 = self.get_text(self.secondary_result_text).strip()
        result_3 = self.get_text(self.tertiary_result_text).strip() if hasattr(self, "tertiary_result_text") else ""
        document_now_result = (
            self.get_text(self.document_now_result_text).strip() if hasattr(self, "document_now_result_text") else ""
        )
        source = self.pdf_source_var.get() or "Résultat 1 + Résultat 2"
        if source == "Contexte + transcription":
            return self.build_pdf_context_transcription_source_text()
        if source == "Transcription seule":
            return self.build_pdf_context_transcription_source_text(transcription_only=True)
        if source == "Résultat 1":
            return result_1
        if source == "Résultat 2":
            return result_2
        if source == "Résultat 3":
            return result_3
        if source == "Document maintenant":
            return document_now_result
        parts = []
        if result_1:
            parts.append("RÉSULTAT 1 :\n" + result_1)
        if result_2:
            parts.append("RÉSULTAT 2 :\n" + result_2)
        if source == "Résultat 1 + Résultat 2 + Résultat 3" and result_3:
            parts.append("RÉSULTAT 3 :\n" + result_3)
        return "\n\n".join(parts).strip()

    def render_pdf_fields(self, fields: list[dict]) -> None:
        if not hasattr(self, "pdf_fields_tree"):
            return
        self.pdf_fields_tree.delete(*self.pdf_fields_tree.get_children())
        for field in fields:
            name = str(field.get("name") or "")
            self.pdf_fields_tree.insert(
                "",
                tk.END,
                iid=name,
                text=name,
                values=(
                    str(field.get("label") or ""),
                    str(field.get("type") or "text"),
                    "Oui" if field.get("required") else "Non",
                    str(field.get("page") or ""),
                    str(field.get("description") or ""),
                ),
            )

    def on_pdf_field_selected(self) -> None:
        selection = self.pdf_fields_tree.selection()
        if not selection:
            return
        name = str(selection[0])
        field = self.get_pdf_field(name)
        if not field:
            return
        self.pdf_field_name_var.set(name)
        self.pdf_field_label_var.set(str(field.get("label") or ""))
        self.pdf_field_description_var.set(str(field.get("description") or ""))
        self.pdf_field_required_var.set(bool(field.get("required")))

    def save_selected_pdf_field(self) -> None:
        template_id = self.current_pdf_template_id()
        name = self.pdf_field_name_var.get()
        if not template_id or not name:
            return
        patch = {
            "label": self.pdf_field_label_var.get().strip(),
            "description": self.pdf_field_description_var.get().strip(),
            "required": bool(self.pdf_field_required_var.get()),
        }
        try:
            self.pdf_current_fields = self.pdf_template_manager.update_field(template_id, name, patch)
            self.pdf_current_schema = build_json_schema(self.pdf_current_fields)
            self.render_pdf_fields(self.pdf_current_fields)
            self.render_pdf_preview()
            self.pdf_status_var.set("PDF: champ enregistré")
        except Exception as exc:
            messagebox.showerror("Champ PDF", str(exc), parent=self.root)

    def get_pdf_field(self, name: str) -> dict | None:
        for field in self.pdf_current_fields:
            if str(field.get("name") or "") == name:
                return field
        return None

    def build_pdf_lmstudio_message(self) -> str:
        if not self.pdf_current_fields:
            raise RuntimeError("Aucun modèle PDF sélectionné.")
        prompt = self.prompt_manager.get(self.current_pdf_prompt_id()) or self.prompt_manager.get_default("pdf_form_fill")
        if not prompt:
            raise RuntimeError("Prompt PDF introuvable.")
        prompt_content = self.get_text(self.pdf_prompt_text).strip() if hasattr(self, "pdf_prompt_text") else prompt.content
        if not prompt_content:
            raise RuntimeError("Prompt PDF vide.")
        schema = build_json_schema(self.pdf_current_fields)
        self.pdf_current_schema = schema
        variables = self.build_prompt_variables()
        variables.update(
            {
                "lmstudio_result": self.build_pdf_preferred_source_text(),
                "result_1": self.get_text(self.result_text).strip(),
                "result_2": self.get_text(self.secondary_result_text).strip(),
                "result_3": self.get_text(self.tertiary_result_text).strip() if hasattr(self, "tertiary_result_text") else "",
                "document_now_result": (
                    self.get_text(self.document_now_result_text).strip()
                    if hasattr(self, "document_now_result_text")
                    else ""
                ),
                "pdf_fields": json.dumps(self.pdf_current_fields, ensure_ascii=False, indent=2),
                "pdf_schema": json.dumps(schema, ensure_ascii=False, indent=2),
            }
        )
        message, variables = self.apply_lmstudio_context_limit(
            prompt_content,
            variables,
            lambda working_variables: self.prompt_manager.render_prompt(prompt_content, working_variables),
            label="pdf_structure",
            max_tokens=int(self.config.get("pdf", {}).get("max_tokens") or 8192),
        )
        return message

    def fill_pdf_with_gemma(self) -> None:
        self.generate_pdf_values_with_gemma(auto_export=True)

    def generate_pdf_values_with_gemma(self, *, auto_export: bool = False) -> None:
        if self.is_lmstudio_request_active("pdf_form"):
            self.pdf_status_var.set("PDF: génération déjà en cours")
            return
        if not self.current_pdf_template_id():
            messagebox.showwarning("PDF structuré", "Sélectionne ou importe d’abord un modèle PDF.", parent=self.root)
            return
        if "Contexte" in str(self.pdf_source_var.get() or "") and not self.require_fresh_patient_context(
            "Génération du PDF"
        ):
            return
        try:
            message = self.build_pdf_lmstudio_message()
        except Exception as exc:
            messagebox.showerror("PDF structuré", str(exc), parent=self.root)
            return
        self.set_text(self.sent_message_text, message, readonly=True)
        self.result_destination_var.set("PDF structuré")
        self.on_result_destination_changed()
        self.lmstudio_status_var.set("LM Studio: génération JSON PDF")
        self.pdf_status_var.set("PDF: demande Gemma en cours")
        pdf_config = self.config.get("pdf", {})
        client = self.build_lmstudio_client(max_tokens=int(pdf_config.get("max_tokens") or 8192))
        self.adjust_lmstudio_client_for_context(client, message, label="pdf_structure")
        response_format = self.build_pdf_response_format()
        self.start_lmstudio_spinner(PDF_FILL_SPINNER_KEY)

        self.launch_lmstudio_request(
            "pdf_form",
            client,
            message,
            response_format=response_format,
            on_success=lambda response: self.on_pdf_lmstudio_response(response, message, auto_export),
            on_error=self.on_pdf_lmstudio_error,
            thread_name="lmstudio-pdf-form",
        )

    def build_pdf_response_format(self) -> dict | None:
        lm_config = self.config.get("lmstudio", {})
        if not bool(lm_config.get("use_json_schema_response_format", False)):
            return None
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "pdf_form_fill",
                "schema": self.pdf_current_schema or build_json_schema(self.pdf_current_fields),
                "strict": True,
            },
        }

    def on_pdf_lmstudio_response(self, response, sent_message: str, auto_export: bool = False) -> None:
        if not auto_export:
            self.stop_lmstudio_spinner(PDF_FILL_SPINNER_KEY)
        try:
            parsed_json = parse_json_object_result(response.text)
            raw_values = parsed_json.values
            values, issues = validate_pdf_field_values(raw_values, self.pdf_current_fields)
        except Exception as exc:
            self.stop_lmstudio_spinner(PDF_FILL_SPINNER_KEY)
            self.lmstudio_status_var.set("LM Studio: JSON PDF invalide")
            self.pdf_status_var.set("PDF: réponse JSON invalide")
            self.set_text(self.pdf_json_text, response.text)
            messagebox.showerror("JSON PDF", str(exc), parent=self.root)
            return
        self.record_generation_metric(
            "pdf_form",
            "pdf_form",
            status="success",
            elapsed_seconds=response.elapsed_seconds,
            input_chars=len(sent_message or ""),
            result_chars=len(response.text or ""),
        )

        if parsed_json.recovered_partial:
            issues.insert(
                0,
                {
                    "field": "_gemma_json",
                    "level": "warning",
                    "message": parsed_json.warning or "JSON récupéré partiellement.",
                },
            )
        self.pdf_current_values = values
        self.pdf_current_issues = issues
        self.set_text(self.pdf_json_text, json.dumps(values, ensure_ascii=False, indent=2))
        self.render_pdf_preview()
        self.lmstudio_status_var.set(f"LM Studio: JSON PDF reçu en {response.elapsed_seconds:.1f}s")
        self.pdf_status_var.set(
            "PDF: JSON partiel récupéré, validation requise"
            if parsed_json.recovered_partial
            else "PDF: valeurs proposées, validation requise"
        )
        self.notebook.select(self.pdf_tab_frame)
        self.history_manager.append(
            {
                **self.current_stt_history_payload(),
                "prompt_name": self.pdf_prompt_var.get(),
                "prompt_type": "pdf_form_fill",
                "transcription": self.get_clean_transcription_text(),
                "weda_context": self.get_text(self.context_text),
                "sent_message": sent_message,
                "lmstudio_result": self.get_text(self.result_text),
                "result_1": self.get_text(self.result_text),
                "result_2": self.get_text(self.secondary_result_text),
                "result_3": self.get_text(self.tertiary_result_text) if hasattr(self, "tertiary_result_text") else "",
                "document_now_result": (
                    self.get_text(self.document_now_result_text)
                    if hasattr(self, "document_now_result_text")
                    else ""
                ),
                "pdf_source": self.pdf_source_var.get(),
                "pdf_template_id": self.pdf_current_template_id,
                "pdf_template_name": self.pdf_current_metadata.get("name", ""),
                "pdf_fields": self.pdf_current_fields,
                "pdf_generated_json": values,
                "pdf_export_status": "preview",
                "status": "pdf_values_generated",
            }
        )
        if auto_export:
            self.pdf_status_var.set("PDF: valeurs reçues, export en cours")
            if not self.fill_and_export_pdf(skip_manual_validation=True):
                self.stop_lmstudio_spinner(PDF_FILL_SPINNER_KEY)

    def on_pdf_lmstudio_error(self, error: Exception) -> None:
        self.stop_lmstudio_spinner(PDF_FILL_SPINNER_KEY)
        if self.lmstudio_request_was_cancelled(error):
            self.record_generation_metric("pdf_form", "pdf_form", status="cancelled", error=error)
            self.lmstudio_status_var.set("LM Studio: génération PDF annulée")
            self.pdf_status_var.set("PDF: génération annulée")
            self.log_debug("info", "pdf", "pdf_lmstudio_cancelled", str(error))
            return
        self.record_generation_metric("pdf_form", "pdf_form", status="error", error=error)
        self.lmstudio_status_var.set("LM Studio: erreur JSON PDF")
        self.pdf_status_var.set("PDF: génération impossible")
        self.log_debug("error", "pdf", "pdf_lmstudio_error", str(error))
        messagebox.showerror("PDF structuré", str(error), parent=self.root)

    def render_pdf_preview(self) -> None:
        if not hasattr(self, "pdf_preview_tree"):
            return
        self.pdf_preview_tree.delete(*self.pdf_preview_tree.get_children())
        if not self.pdf_current_fields:
            return
        rows = build_preview_rows(self.pdf_current_fields, self.pdf_current_values, self.pdf_current_issues)
        for row in rows:
            self.pdf_preview_tree.insert(
                "",
                tk.END,
                iid=row["name"],
                text=row["name"],
                values=(row["label"], row["value"], row["status"]),
            )

    def on_pdf_preview_selected(self) -> None:
        selection = self.pdf_preview_tree.selection()
        if not selection:
            return
        name = str(selection[0])
        self.pdf_preview_field_var.set(name)
        value = self.pdf_current_values.get(name, "")
        self.pdf_preview_value_var.set("true" if value is True else "false" if value is False else str(value or ""))

    def apply_pdf_preview_value(self) -> None:
        name = self.pdf_preview_field_var.get()
        if not name:
            return
        raw_values = dict(self.pdf_current_values)
        raw_values[name] = self.pdf_preview_value_var.get()
        values, issues = validate_pdf_field_values(raw_values, self.pdf_current_fields)
        self.pdf_current_values = values
        self.pdf_current_issues = issues
        self.set_text(self.pdf_json_text, json.dumps(values, ensure_ascii=False, indent=2))
        self.render_pdf_preview()
        self.pdf_status_var.set("PDF: valeur corrigée manuellement")

    def parse_pdf_json_from_editor(self) -> bool:
        raw = self.get_text(self.pdf_json_text).strip()
        if not raw:
            return bool(self.pdf_current_values)
        try:
            parsed = parse_json_object(raw)
            values, issues = validate_pdf_field_values(parsed, self.pdf_current_fields)
        except Exception as exc:
            messagebox.showerror("JSON PDF", str(exc), parent=self.root)
            return False
        self.pdf_current_values = values
        self.pdf_current_issues = issues
        self.set_text(self.pdf_json_text, json.dumps(values, ensure_ascii=False, indent=2))
        self.render_pdf_preview()
        return True

    def copy_pdf_json(self) -> None:
        if not self.parse_pdf_json_from_editor():
            return
        ok = copy_text_to_clipboard(self.get_text(self.pdf_json_text), self.root)
        self.pdf_status_var.set("PDF: JSON copié" if ok else "PDF: copie JSON impossible")

    def fill_and_export_pdf(self, *, skip_manual_validation: bool = False) -> bool:
        if not self.current_pdf_template_id() or not self.pdf_current_fields:
            messagebox.showwarning("PDF structuré", "Sélectionne un modèle PDF.", parent=self.root)
            return False
        if not self.parse_pdf_json_from_editor():
            return False
        if not self.pdf_current_values:
            messagebox.showwarning("PDF structuré", "Aucune valeur PDF à remplir.", parent=self.root)
            return False

        issue_lines = [f"- {issue.get('field')}: {issue.get('message')}" for issue in self.pdf_current_issues]
        details = "\n".join(issue_lines[:8])
        if len(issue_lines) > 8:
            details += f"\n... +{len(issue_lines) - 8} autre(s) alerte(s)"

        pdf_config = self.config.get("pdf", {})
        if not skip_manual_validation and bool(pdf_config.get("require_manual_validation", True)):
            message = "Générer le PDF final avec les valeurs affichées ?\n\nLe modèle original restera intact."
            if details:
                message += "\n\nAlertes à vérifier :\n" + details
            if not messagebox.askyesno("Validation humaine requise", message, parent=self.root):
                return False

        context = self.context_manager.get_latest()
        patient_identity = context.patient_identity if context else ""
        template_name = str(self.pdf_current_metadata.get("name") or self.pdf_current_template_id)
        output_path = self.pdf_export_manager.build_output_path(
            template_name=template_name,
            patient_identity=patient_identity,
        )
        template_path = self.pdf_current_metadata.get("template_path") or self.pdf_template_manager.template_pdf_path(self.pdf_current_template_id)
        values_snapshot = dict(self.pdf_current_values)
        fields_snapshot = [dict(field) for field in self.pdf_current_fields]
        history_payload = {
            **self.current_stt_history_payload(),
            "prompt_name": self.pdf_prompt_var.get(),
            "prompt_type": "pdf_form_fill",
            "pdf_template_id": self.pdf_current_template_id,
            "pdf_template_name": template_name,
            "pdf_fields": fields_snapshot,
            "pdf_generated_json": values_snapshot,
            "result_1": self.get_text(self.result_text),
            "result_2": self.get_text(self.secondary_result_text),
            "result_3": self.get_text(self.tertiary_result_text) if hasattr(self, "tertiary_result_text") else "",
            "document_now_result": (
                self.get_text(self.document_now_result_text)
                if hasattr(self, "document_now_result_text")
                else ""
            ),
            "pdf_source": self.pdf_source_var.get(),
        }
        open_after_export = bool(pdf_config.get("open_after_export", True))
        self.pdf_status_var.set("PDF: export en cours")
        self.start_lmstudio_spinner(PDF_FILL_SPINNER_KEY)

        def worker():
            try:
                result = self.pdf_fill_manager.fill_pdf(
                    template_path,
                    values_snapshot,
                    output_path,
                    fields=fields_snapshot,
                )
                self.root.after(0, self.on_pdf_export_success, result, history_payload, open_after_export)
            except Exception as exc:
                self.root.after(0, self.on_pdf_export_error, exc)

        threading.Thread(target=worker, name="pdf-structured-export", daemon=True).start()
        return True

    def on_pdf_export_success(self, result, history_payload: dict, open_after_export: bool) -> None:
        self.stop_lmstudio_spinner(PDF_FILL_SPINNER_KEY)
        self.pdf_last_output_path = str(result.output_path)
        self.pdf_status_var.set(f"PDF: exporté {result.output_path.name}")
        history_payload.update(
            {
                "pdf_final_path": str(result.output_path),
                "pdf_export_status": "exported",
                "pdf_warnings": result.warnings,
                "status": "pdf_exported",
            }
        )
        self.history_manager.append(history_payload)
        if result.warnings:
            self.log_debug("warning", "pdf", "pdf_export_warnings", "PDF exporté avec alertes.", {"warnings": result.warnings})
        if open_after_export:
            self.open_last_pdf_output()

    def on_pdf_export_error(self, error: Exception) -> None:
        self.stop_lmstudio_spinner(PDF_FILL_SPINNER_KEY)
        self.pdf_status_var.set("PDF: export impossible")
        messagebox.showerror("PDF structuré", str(error), parent=self.root)

    def open_last_pdf_output(self) -> None:
        if not self.pdf_last_output_path:
            messagebox.showinfo("PDF structuré", "Aucun PDF final exporté pour l’instant.", parent=self.root)
            return
        try:
            self.pdf_export_manager.open_file(self.pdf_last_output_path)
        except Exception as exc:
            messagebox.showerror("PDF structuré", str(exc), parent=self.root)

    def purge_local_history(self) -> None:
        if not messagebox.askyesno(
            "Purger historique local",
            "Supprimer l’historique local de l’application ?\nLes modèles PDF et PDF exportés ne seront pas supprimés.",
            parent=self.root,
        ):
            return
        self.history_manager.purge()
        self.pdf_status_var.set("PDF: historique local purgé")

    def install_live_message_refresh(self) -> None:
        for widget in self._message_source_widgets:
            widget.bind("<<Modified>>", self.on_message_source_modified, add="+")
            try:
                widget.edit_modified(False)
            except Exception:
                pass
        for widget in self._secondary_message_source_widgets:
            widget.bind("<<Modified>>", self.on_secondary_message_source_modified, add="+")
            try:
                widget.edit_modified(False)
            except Exception:
                pass
        for widget in self._tertiary_message_source_widgets:
            widget.bind("<<Modified>>", self.on_tertiary_message_source_modified, add="+")
            try:
                widget.edit_modified(False)
            except Exception:
                pass
        for widget in self._document_now_message_source_widgets:
            widget.bind("<<Modified>>", self.on_document_now_message_source_modified, add="+")
            try:
                widget.edit_modified(False)
            except Exception:
                pass
        self.include_prompt_var.trace_add("write", lambda *_args: self.schedule_message_refresh())
        self.include_prompt_var.trace_add("write", lambda *_args: self.schedule_secondary_message_refresh())
        self.include_prompt_var.trace_add("write", lambda *_args: self.schedule_tertiary_message_refresh())
        self.include_prompt_var.trace_add("write", lambda *_args: self.schedule_document_now_message_refresh())
        self.include_context_var.trace_add("write", lambda *_args: self.schedule_message_refresh())
        self.include_context_var.trace_add("write", lambda *_args: self.schedule_secondary_message_refresh())
        self.include_context_var.trace_add("write", lambda *_args: self.schedule_tertiary_message_refresh())
        self.include_context_var.trace_add("write", lambda *_args: self.schedule_document_now_message_refresh())
        self.include_transcription_var.trace_add("write", lambda *_args: self.schedule_message_refresh())
        self.include_transcription_var.trace_add("write", lambda *_args: self.schedule_secondary_message_refresh())
        self.include_transcription_var.trace_add("write", lambda *_args: self.schedule_tertiary_message_refresh())
        self.include_transcription_var.trace_add("write", lambda *_args: self.schedule_document_now_message_refresh())
        self.secondary_enabled_var.trace_add("write", lambda *_args: self.schedule_secondary_message_refresh())
        self.secondary_enabled_var.trace_add("write", lambda *_args: self.schedule_tertiary_message_refresh())
        self.tertiary_enabled_var.trace_add("write", lambda *_args: self.schedule_tertiary_message_refresh())
        self.schedule_message_refresh()
        self.schedule_secondary_message_refresh()
        self.schedule_tertiary_message_refresh()
        self.schedule_document_now_message_refresh()

    def on_message_source_modified(self, event) -> None:
        widget = event.widget
        try:
            if not widget.edit_modified():
                return
            widget.edit_modified(False)
        except Exception:
            pass
        self.schedule_message_refresh()

    def on_secondary_message_source_modified(self, event) -> None:
        try:
            event.widget.edit_modified(False)
        except Exception:
            pass
        self.schedule_secondary_message_refresh()
        self.schedule_tertiary_message_refresh()

    def on_tertiary_message_source_modified(self, event) -> None:
        try:
            event.widget.edit_modified(False)
        except Exception:
            pass
        self.schedule_tertiary_message_refresh()

    def on_document_now_message_source_modified(self, event) -> None:
        try:
            event.widget.edit_modified(False)
        except Exception:
            pass
        self.schedule_document_now_message_refresh()

    def schedule_message_refresh(self, delay_ms: int = 60) -> None:
        if not hasattr(self, "sent_message_text"):
            return
        if self._message_refresh_job:
            try:
                self.root.after_cancel(self._message_refresh_job)
            except Exception:
                pass
        self._message_refresh_job = self.root.after(delay_ms, self.refresh_sent_message)

    def schedule_secondary_message_refresh(self, delay_ms: int = 90) -> None:
        if not hasattr(self, "secondary_sent_message_text"):
            return
        if self._secondary_message_refresh_job:
            try:
                self.root.after_cancel(self._secondary_message_refresh_job)
            except Exception:
                pass
        self._secondary_message_refresh_job = self.root.after(delay_ms, self.refresh_secondary_sent_message)

    def schedule_tertiary_message_refresh(self, delay_ms: int = 110) -> None:
        if not hasattr(self, "tertiary_sent_message_text"):
            return
        if self._tertiary_message_refresh_job:
            try:
                self.root.after_cancel(self._tertiary_message_refresh_job)
            except Exception:
                pass
        self._tertiary_message_refresh_job = self.root.after(delay_ms, self.refresh_tertiary_sent_message)

    def schedule_document_now_message_refresh(self, delay_ms: int = 120) -> None:
        if not hasattr(self, "document_now_sent_message_text"):
            return
        if self._document_now_message_refresh_job:
            try:
                self.root.after_cancel(self._document_now_message_refresh_job)
            except Exception:
                pass
        self._document_now_message_refresh_job = self.root.after(delay_ms, self.refresh_document_now_sent_message)

    def write_runtime_config(self, reason: str = "settings") -> bool:
        try:
            save_json(BASE_DIR / "config.json", self.config)
            return True
        except Exception as exc:
            self.log_debug("error", "app", "runtime_config_save_error", str(exc), {"reason": reason})
            return False

    def normalize_result_destination(self) -> str:
        value = self.result_destination_var.get() if hasattr(self, "result_destination_var") else "WEDA consultation"
        if value not in RESULT_DESTINATION_CHOICES:
            value = "WEDA consultation"
            if hasattr(self, "result_destination_var"):
                self.result_destination_var.set(value)
        return value

    def normalize_pdf_source_choice(self) -> str:
        value = self.pdf_source_var.get() if hasattr(self, "pdf_source_var") else "Résultat 1 + Résultat 2"
        if value not in PDF_SOURCE_CHOICES:
            value = "Résultat 1 + Résultat 2"
            if hasattr(self, "pdf_source_var"):
                self.pdf_source_var.set(value)
        return value

    def capture_message_composition_settings(self) -> None:
        if not all(hasattr(self, name) for name in ("include_prompt_var", "include_context_var", "include_transcription_var")):
            return
        message_config = self.config.setdefault("message_composition", {})
        message_config["include_prompt"] = bool(self.include_prompt_var.get())
        message_config["include_weda_context"] = bool(self.include_context_var.get())
        message_config["include_transcription"] = bool(self.include_transcription_var.get())

    def capture_ui_selection_settings(self) -> None:
        ui_config = self.config.setdefault("ui", {})
        if hasattr(self, "result_destination_var"):
            ui_config["result_destination"] = self.normalize_result_destination()
        if hasattr(self, "notebook"):
            ui_config["main_notebook_tab_order"] = self.get_main_notebook_tab_order()

    def get_main_notebook_tab_order(self) -> list[str]:
        if not hasattr(self, "notebook"):
            return []
        labels = []
        for tab_id in self.notebook.tabs():
            try:
                label = str(self.notebook.tab(tab_id, "text") or "").strip()
            except tk.TclError:
                label = ""
            if label:
                labels.append(label)
        return labels

    def apply_main_notebook_tab_order(self) -> None:
        if not hasattr(self, "notebook"):
            return
        stored_order = self.config.get("ui", {}).get("main_notebook_tab_order")
        if not isinstance(stored_order, list) or not stored_order:
            return

        tabs_by_label = {}
        current_order = []
        for tab_id in self.notebook.tabs():
            try:
                label = str(self.notebook.tab(tab_id, "text") or "").strip()
            except tk.TclError:
                continue
            if not label or label in tabs_by_label:
                continue
            tabs_by_label[label] = tab_id
            current_order.append(label)

        migrated_order = migrate_main_notebook_tab_order(stored_order)
        ordered_labels = [label for label in migrated_order if label in tabs_by_label]
        ordered_labels.extend(label for label in current_order if label not in ordered_labels)
        if ordered_labels == current_order:
            return

        selected = self.notebook.select()
        for index, label in enumerate(ordered_labels):
            try:
                self.notebook.insert(index, tabs_by_label[label])
            except tk.TclError:
                continue
        if selected:
            try:
                self.notebook.select(selected)
            except tk.TclError:
                pass

    def install_main_notebook_tab_dragging(self) -> None:
        if not hasattr(self, "notebook") or getattr(self.notebook, "_drflow_tab_drag_installed", False):
            return
        self.notebook._drflow_tab_drag_installed = True
        self.notebook.bind("<ButtonPress-1>", self.on_main_notebook_tab_press, add="+")
        self.notebook.bind("<B1-Motion>", self.on_main_notebook_tab_motion, add="+")
        self.notebook.bind("<ButtonRelease-1>", self.on_main_notebook_tab_release, add="+")

    def main_notebook_tab_index_at(self, x: int, y: int) -> int | None:
        if not hasattr(self, "notebook"):
            return None
        try:
            element = str(self.notebook.identify(x, y) or "")
        except tk.TclError:
            element = ""
        if not element:
            return None
        try:
            return int(self.notebook.index(f"@{x},{y}"))
        except (tk.TclError, ValueError):
            return None

    def on_main_notebook_tab_press(self, event) -> None:
        index = self.main_notebook_tab_index_at(event.x, event.y)
        self._main_notebook_drag_index = index
        self._main_notebook_drag_active = False
        self._main_notebook_drag_start_x = int(event.x)
        self._main_notebook_drag_start_y = int(event.y)

    def on_main_notebook_tab_motion(self, event) -> None:
        if self._main_notebook_drag_index is None:
            return
        distance = abs(int(event.x) - self._main_notebook_drag_start_x) + abs(int(event.y) - self._main_notebook_drag_start_y)
        if not self._main_notebook_drag_active and distance < 8:
            return

        target_index = self.main_notebook_tab_index_at(event.x, event.y)
        if target_index is None or target_index == self._main_notebook_drag_index:
            return

        tabs = self.notebook.tabs()
        if self._main_notebook_drag_index < 0 or self._main_notebook_drag_index >= len(tabs):
            return

        dragged_tab = tabs[self._main_notebook_drag_index]
        try:
            self.notebook.insert(target_index, dragged_tab)
            self.notebook.select(dragged_tab)
            self._main_notebook_drag_index = int(self.notebook.index(dragged_tab))
            self._main_notebook_drag_active = True
        except tk.TclError:
            return

    def on_main_notebook_tab_release(self, _event) -> None:
        should_save = self._main_notebook_drag_active
        self._main_notebook_drag_index = None
        self._main_notebook_drag_active = False
        if should_save:
            self.config.setdefault("ui", {})["main_notebook_tab_order"] = self.get_main_notebook_tab_order()
            self.write_runtime_config("main_notebook_tab_order")

    def capture_pdf_selection_settings(self) -> None:
        pdf_config = self.config.setdefault("pdf", {})
        if hasattr(self, "pdf_source_var"):
            pdf_config["preferred_source"] = self.normalize_pdf_source_choice()
        if hasattr(self, "pdf_template_name_to_id"):
            template_id = self.current_pdf_template_id()
            if template_id:
                pdf_config["last_template_id"] = template_id
        if hasattr(self, "pdf_prompt_name_to_id"):
            prompt_id = self.current_pdf_prompt_id()
            if prompt_id:
                pdf_config["last_prompt_id"] = prompt_id

    def capture_prompt_selection_settings(self) -> None:
        if hasattr(self, "prompt_name_to_id"):
            prompt_id = self.current_prompt_id()
            if prompt_id:
                self.config.setdefault("ui", {})["last_prompt_id"] = prompt_id

        if hasattr(self, "secondary_prompt_name_to_id"):
            secondary_config = normalize_secondary_analysis_config(self.config.get("secondary_analysis", {}))
            if hasattr(self, "secondary_enabled_var"):
                secondary_config["enabled"] = bool(self.secondary_enabled_var.get())
            prompt_id = self.current_secondary_prompt_id()
            if prompt_id:
                secondary_config["last_prompt_id"] = prompt_id
            self.config["secondary_analysis"] = secondary_config

        if hasattr(self, "tertiary_prompt_name_to_id"):
            tertiary_config = normalize_tertiary_analysis_config(self.config.get("tertiary_analysis", {}))
            if hasattr(self, "tertiary_enabled_var"):
                tertiary_config["enabled"] = bool(self.tertiary_enabled_var.get())
            prompt_id = self.current_tertiary_prompt_id()
            if prompt_id:
                tertiary_config["last_prompt_id"] = prompt_id
            self.config["tertiary_analysis"] = tertiary_config

        if hasattr(self, "document_now_prompt_name_to_id"):
            prompt_id = self.current_document_now_prompt_id()
            if prompt_id:
                self.config.setdefault("document_now", {})["last_prompt_id"] = prompt_id

    def capture_document_now_default_prompt_setting(self) -> None:
        if not hasattr(self, "document_now_default_prompt_text"):
            return
        self.config.setdefault("document_now", {})["default_prompt_prefix"] = self.get_text(
            self.document_now_default_prompt_text
        )

    def capture_context_delay_setting(self) -> None:
        if not hasattr(self, "context_delay_seconds_var"):
            return
        try:
            value = int(float(self.context_delay_seconds_var.get()))
        except (TypeError, ValueError):
            value = self.get_context_capture_delay_seconds()
        value = max(0, min(300, value))
        self.context_delay_seconds_var.set(str(value))
        self.config.setdefault("weda", {})["context_capture_delay_seconds"] = value

    def capture_connector_settings(self) -> None:
        if not all(
            hasattr(self, name)
            for name in (
                "connector_enabled_var",
                "connector_start_key_var",
                "connector_stop_key_var",
                "connector_document_now_key_var",
            )
        ):
            return
        start_key = self.connector_start_key_var.get() or "PageUp"
        stop_key = self.connector_stop_key_var.get() or "PageDown"
        document_now_key = self.connector_document_now_key_var.get() or "F8"
        if start_key == stop_key:
            stop_key = "PageDown" if start_key != "PageDown" else "PageUp"
            self.connector_stop_key_var.set(stop_key)
        if document_now_key in {start_key, stop_key}:
            document_now_key = next(
                (key for key in self.connector_key_choices() if key not in {start_key, stop_key}),
                "F8",
            )
            self.connector_document_now_key_var.set(document_now_key)
        connector_config = self.config.setdefault("connector", {})
        connector_config["enabled"] = bool(self.connector_enabled_var.get())
        connector_config["start_key"] = start_key
        connector_config["stop_key"] = stop_key
        connector_config["document_now_key"] = document_now_key
        connector_config.setdefault("stop_transcription_grace_seconds", 2)
        connector_config.setdefault("auto_return_home", True)

    def capture_fly_dictation_settings(self) -> None:
        if not hasattr(self, "fly_dictation_enabled_var"):
            return
        settings = self.get_fly_dictation_settings()
        self.fly_dictation_key_var.set(settings["key"])
        self.fly_dictation_model_var.set(settings["model"])
        self.fly_dictation_device_var.set(settings["device"])
        self.fly_dictation_compute_var.set(settings["compute_type"])
        fly_config = self.config.setdefault("fly_dictation", {})
        fly_config["enabled"] = settings["enabled"]
        fly_config["key"] = settings["key"]
        fly_config["model"] = settings["model"]
        fly_config["device"] = settings["device"]
        fly_config["compute_type"] = settings["compute_type"]
        fly_config.setdefault("min_seconds", settings["min_seconds"])
        fly_config.setdefault("paste_delay_ms", settings["paste_delay_ms"])
        fly_config.setdefault("beam_size", 1)
        fly_config.setdefault("best_of", 1)
        fly_config.setdefault("temperature", 0.0)
        fly_config.setdefault("condition_on_previous_text", False)
        fly_config.setdefault("vad_filter", False)
        fly_config.setdefault("without_timestamps", True)
        fly_config.setdefault("max_new_tokens", 128)
        fly_config.setdefault("min_silence_duration_ms", 250)
        fly_config.setdefault("initial_prompt", DEFAULT_FLY_WHISPER_INITIAL_PROMPT)
        fly_config.setdefault("preload_model", True)

    def capture_all_runtime_settings(self) -> None:
        self.capture_message_composition_settings()
        self.capture_ui_selection_settings()
        self.capture_pdf_selection_settings()
        self.capture_prompt_selection_settings()
        self.capture_document_now_default_prompt_setting()
        self.capture_context_delay_setting()
        self.capture_connector_settings()
        self.capture_fly_dictation_settings()
        self.capture_stt_runtime_settings()
        medical = self.config.setdefault("medical_transcription", {})
        if hasattr(self, "whisper_include_weda_context_var"):
            medical["include_weda_context_in_whisper_prompt"] = bool(self.whisper_include_weda_context_var.get())
            medical["use_dynamic_weda_hotwords"] = bool(self.whisper_use_dynamic_hotwords_var.get())
            medical["apply_validated_corrections"] = bool(self.whisper_apply_corrections_var.get())
        if hasattr(self, "permanent_hotwords_text"):
            medical["permanent_hotwords"] = parse_permanent_hotwords(self.get_text(self.permanent_hotwords_text))

    def save_all_runtime_settings(self, reason: str = "settings") -> bool:
        self.capture_all_runtime_settings()
        return self.write_runtime_config(reason)

    def save_message_composition_settings(self) -> None:
        self.capture_message_composition_settings()
        message_config = self.config.setdefault("message_composition", {})
        try:
            save_json(BASE_DIR / "config.json", self.config)
        except Exception as exc:
            self.log_debug("error", "app", "message_composition_save_error", str(exc), dict(message_config))
        self.schedule_message_refresh()
        self.schedule_secondary_message_refresh()
        self.schedule_tertiary_message_refresh()

    def build_lmstudio_message(self) -> tuple[str, dict[str, str]]:
        prompt_content = self.get_text(self.prompt_text) if self.include_prompt_var.get() else ""
        variables = self.build_prompt_variables()
        def render_message(working_variables: dict[str, str]) -> str:
            rendered = self.prompt_manager.render_prompt(prompt_content, working_variables) if prompt_content.strip() else ""
            rendered = self.append_missing_source_sections(prompt_content, rendered, working_variables)
            rendered = self.append_message_attachment_section(prompt_content, rendered, working_variables)
            return rendered

        message, variables = self.apply_lmstudio_context_limit(
            prompt_content,
            variables,
            render_message,
            label="message_principal",
        )
        return message, variables

    def refresh_sent_message(self) -> str:
        self._message_refresh_job = None
        message, _variables = self.build_lmstudio_message()
        self.set_text(self.sent_message_text, message, readonly=True)
        return message

    def document_prompt_text_widget(self, document_index: int) -> tk.Text:
        if document_index == 2:
            return self.secondary_prompt_text
        if document_index == 3:
            return self.tertiary_prompt_text
        return self.prompt_text

    def document_sent_message_widget(self, document_index: int) -> tk.Text:
        if document_index == 2:
            return self.secondary_sent_message_text
        if document_index == 3:
            return self.tertiary_sent_message_text
        return self.sent_message_text

    def document_result_widget(self, document_index: int) -> tk.Text:
        if document_index == 2:
            return self.secondary_result_text
        if document_index == 3:
            return self.tertiary_result_text
        return self.result_text

    def document_status_var(self, document_index: int) -> tk.StringVar:
        if document_index == 2:
            return self.secondary_status_var
        if document_index == 3:
            return self.tertiary_status_var
        return self.lmstudio_status_var

    def document_prompt_name(self, document_index: int) -> str:
        if document_index == 2:
            return self.secondary_prompt_var.get()
        if document_index == 3:
            return self.tertiary_prompt_var.get()
        return self.prompt_var.get()

    def build_independent_document_lmstudio_message(self, document_index: int) -> tuple[str, dict[str, str]]:
        prompt_widget = self.document_prompt_text_widget(document_index)
        prompt_content = self.get_text(prompt_widget) if self.include_prompt_var.get() else ""
        variables = self.build_prompt_variables()
        variables["document_index"] = str(document_index)
        variables["document_label"] = f"Document {document_index}"
        variables["prompt_name"] = self.document_prompt_name(document_index)

        def render_message(working_variables: dict[str, str]) -> str:
            rendered = self.prompt_manager.render_prompt(prompt_content, working_variables) if prompt_content.strip() else ""
            rendered = self.append_missing_source_sections(prompt_content, rendered, working_variables)
            rendered = self.append_message_attachment_section(prompt_content, rendered, working_variables)
            return rendered

        message, variables = self.apply_lmstudio_context_limit(
            prompt_content,
            variables,
            render_message,
            label=f"document_{document_index}",
        )
        return message, variables

    def send_document_to_lmstudio(self, document_index: int) -> None:
        if document_index == 1:
            # Document 1 is the entry point of the optional 1 -> 2 -> 3 chain.
            # Keep every "Envoyer" button on the same orchestration path.
            self.send_to_lmstudio()
            return
        if self.is_lmstudio_request_active(f"document_{document_index}"):
            self.document_status_var(document_index).set(f"Document {document_index}: génération déjà en cours")
            return
        if self.include_context_var.get() and not self.require_fresh_patient_context(
            f"Génération du Document {document_index}"
        ):
            return
        try:
            message, variables = self.build_independent_document_lmstudio_message(document_index)
        except Exception as exc:
            messagebox.showerror(f"Document {document_index}", str(exc), parent=self.root)
            return

        message = message.strip()
        if not message:
            messagebox.showwarning(
                f"Document {document_index}",
                "Le message à envoyer est vide. Ajoute un prompt, du contexte, une transcription ou un fichier.",
                parent=self.root,
            )
            return

        sent_widget = self.document_sent_message_widget(document_index)
        self.set_text(sent_widget, message, readonly=True)
        status_var = self.document_status_var(document_index)
        status_var.set(f"Document {document_index}: envoi LM Studio")
        self.lmstudio_status_var.set(f"LM Studio: Document {document_index} en cours")
        lm_config = self.config.get("lmstudio", {})
        client = self.build_lmstudio_client()
        self.adjust_lmstudio_client_for_context(client, message, label=f"document_{document_index}")
        self.start_lmstudio_spinner(self.document_lmstudio_spinner_key(document_index))
        self.log_debug(
            "info",
            "app",
            "lmstudio_document_request_started",
            "Envoi document indépendant à LM Studio.",
            {
                "document_index": document_index,
                "prompt_name": variables.get("prompt_name", ""),
                "url": str(lm_config.get("url") or "http://localhost:1234/v1/chat/completions"),
                "model": str(lm_config.get("model") or "local-model"),
                "message_length": len(message),
                "transcription_length": len(variables.get("transcription") or ""),
                "weda_context_length": len(variables.get("weda_context") or ""),
                "attachments_length": len(variables.get("attachments") or ""),
            },
        )

        self.launch_lmstudio_request(
            f"document_{document_index}",
            client,
            message,
            on_success=lambda response: self.on_document_lmstudio_response(document_index, response, message),
            on_error=lambda error: self.on_document_lmstudio_error(document_index, error, message),
            thread_name=f"lmstudio-document-{document_index}-request",
            result_source=self.result_source_key_for_document(document_index),
        )

    def on_document_lmstudio_response(self, document_index: int, response, sent_message: str) -> None:
        self.stop_lmstudio_spinner(self.document_lmstudio_spinner_key(document_index))
        result_text = self.apply_abbreviations_to_lmstudio_result(response.text, f"Résultat {document_index}")
        result_source = self.result_source_key_for_document(document_index)
        result_payload = self.remember_weda_result_payload(result_source, result_text)
        self.record_generation_metric(
            f"document_{document_index}",
            result_source,
            status="success",
            elapsed_seconds=response.elapsed_seconds,
            input_chars=len(sent_message or ""),
            result_chars=len(result_payload.text or ""),
        )
        result_widget = self.document_result_widget(document_index)
        self.set_rich_result_text(result_widget, result_payload, source=result_source)
        self.select_tab_containing_widget(result_widget)
        self.document_status_var(document_index).set(f"Document {document_index}: réponse reçue en {response.elapsed_seconds:.1f}s")
        self.lmstudio_status_var.set(f"LM Studio: Document {document_index} reçu en {response.elapsed_seconds:.1f}s")
        self.log_debug(
            "info",
            "app",
            "lmstudio_document_response",
            "Réponse document indépendant reçue.",
            {
                "document_index": document_index,
                "elapsed_seconds": response.elapsed_seconds,
                "raw_result_length": len(response.text or ""),
                "result_length": len(result_payload.text or ""),
                "result_html_length": len(result_payload.html or ""),
            },
        )
        if document_index == 1:
            self.schedule_secondary_message_refresh()
            self.schedule_tertiary_message_refresh()
        elif document_index == 2:
            self.schedule_tertiary_message_refresh()
        self.append_independent_document_history(document_index, sent_message, result_payload.text)

    def on_document_lmstudio_error(self, document_index: int, error: Exception, sent_message: str) -> None:
        self.stop_lmstudio_spinner(self.document_lmstudio_spinner_key(document_index))
        self.discard_pending_result_patient_binding(self.result_source_key_for_document(document_index))
        if self.lmstudio_request_was_cancelled(error):
            self.record_generation_metric(
                f"document_{document_index}",
                self.result_source_key_for_document(document_index),
                status="cancelled",
                input_chars=len(sent_message or ""),
                error=error,
            )
            self.document_status_var(document_index).set(f"Document {document_index}: génération annulée")
            self.lmstudio_status_var.set("LM Studio: génération annulée")
            self.log_debug("info", "app", "lmstudio_document_cancelled", str(error), {"document_index": document_index})
            return
        self.record_generation_metric(
            f"document_{document_index}",
            self.result_source_key_for_document(document_index),
            status="error",
            input_chars=len(sent_message or ""),
            error=error,
        )
        message = f"Erreur Document {document_index} : {error}"
        result_widget = self.document_result_widget(document_index)
        self.set_text(result_widget, message)
        self.select_tab_containing_widget(result_widget)
        self.document_status_var(document_index).set(f"Document {document_index}: erreur")
        self.lmstudio_status_var.set("LM Studio: erreur")
        self.log_debug(
            "error",
            "app",
            "lmstudio_document_error",
            str(error),
            {
                "document_index": document_index,
                "message_length": len(sent_message or ""),
            },
        )
        messagebox.showerror(f"Document {document_index}", str(error), parent=self.root)

    def append_independent_document_history(self, document_index: int, sent_message: str, result_text: str) -> None:
        self.history_manager.append(
            {
                **self.current_stt_history_payload(),
                "status": "lmstudio_document_response",
                "document_index": document_index,
                "document_label": f"Document {document_index}",
                "prompt_name": self.document_prompt_name(document_index),
                "message_sent": sent_message,
                "lmstudio_result": result_text,
                "message_sent_1": sent_message if document_index == 1 else self.get_text(self.sent_message_text),
                "message_sent_2": sent_message if document_index == 2 else self.get_text(self.secondary_sent_message_text),
                "message_sent_3": sent_message if document_index == 3 else self.get_text(self.tertiary_sent_message_text),
                "result_1": self.get_text(self.result_text),
                "result_2": self.get_text(self.secondary_result_text),
                "result_3": self.get_text(self.tertiary_result_text) if hasattr(self, "tertiary_result_text") else "",
                "document_now_result": (
                    self.get_text(self.document_now_result_text)
                    if hasattr(self, "document_now_result_text")
                    else ""
                ),
                "transcription": self.get_clean_transcription_text(),
                "weda_context": self.get_text(self.context_text),
            }
        )

    def build_document_now_patient_details(self) -> str:
        context = self.context_manager.get_latest()
        if not context:
            return ""
        lines = [
            context.patient_identity,
            f"Âge : {context.patient_age}" if context.patient_age else "",
            f"Sexe : {context.patient_sex}" if context.patient_sex else "",
        ]
        return "\n".join(line for line in lines if line).strip()

    def create_document_now_snapshot(
        self,
        checkpoint_id: str,
        result=None,
        *,
        status: str = "snapshot_ready",
    ) -> DocumentNowSnapshot:
        prompt_id = self.current_document_now_prompt_id()
        prompt = self.prompt_manager.get(prompt_id) if prompt_id else None
        selected_prompt_content = self.get_text(self.document_now_prompt_text) if hasattr(self, "document_now_prompt_text") else (
            prompt.content if prompt else DEFAULT_DOCUMENT_NOW_PROMPT
        )
        prompt_content = self.compose_document_now_prompt_content(selected_prompt_content)
        audio_stats = getattr(result, "audio_stats", {}) or {}
        duration_seconds = audio_stats.get("duration_seconds")
        try:
            transcript_duration_seconds = float(duration_seconds) if duration_seconds not in (None, "") else None
        except (TypeError, ValueError):
            transcript_duration_seconds = None

        segment_index = getattr(result, "segment_index", None)
        try:
            transcript_segment_count = int(segment_index) if segment_index is not None else None
        except (TypeError, ValueError):
            transcript_segment_count = None

        return DocumentNowSnapshot(
            id=checkpoint_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            transcript_text=self.get_clean_transcription_text(),
            transcript_duration_seconds=transcript_duration_seconds,
            transcript_segment_count=transcript_segment_count,
            weda_context=self.get_text(self.context_text).strip() or None,
            patient_details=self.build_document_now_patient_details() or None,
            date_today=date.today().strftime("%d/%m/%Y"),
            document_type="document_intermediaire",
            prompt_id=prompt.id if prompt else prompt_id or None,
            prompt_name=prompt.name if prompt else self.document_now_prompt_var.get() or None,
            prompt_content=prompt_content,
            sent_message=None,
            result=None,
            status=status,
            error=None,
        )

    def build_document_now_prompt_variables(self, snapshot: DocumentNowSnapshot) -> dict[str, str]:
        variables = self.build_prompt_variables()
        include_prompt = bool(self.include_prompt_var.get())
        include_context = bool(self.include_context_var.get())
        include_transcription = bool(self.include_transcription_var.get())
        patient_details = (snapshot.patient_details or "") if include_prompt or include_context else ""
        snapshot_transcription = (snapshot.transcript_text or "") if include_transcription else ""
        weda_context = (snapshot.weda_context or "") if include_context else ""
        variables.update(
            {
                "transcription": snapshot_transcription,
                "snapshot_transcription": snapshot_transcription,
                "snapshot_de_transcription": snapshot_transcription,
                "weda_context": weda_context,
                "patient_details": patient_details,
                "patient_identity": patient_details or variables.get("patient_identity", ""),
                "current_date": snapshot.date_today,
                "date_today": snapshot.date_today,
                "checkpoint_id": snapshot.id,
                "snapshot_id": snapshot.id,
                "document_type": snapshot.document_type or "document_intermediaire",
                "document_label": "Document maintenant",
                "prompt_name": snapshot.prompt_name or "",
                "document_now_default_prompt": self.get_document_now_default_prompt_prefix(),
                "prompt_defaut_document_maintenant": self.get_document_now_default_prompt_prefix(),
                "transcript_segment_count": "" if snapshot.transcript_segment_count is None else str(snapshot.transcript_segment_count),
                "transcript_duration_seconds": (
                    "" if snapshot.transcript_duration_seconds is None else f"{snapshot.transcript_duration_seconds:.1f}"
                ),
                "snapshot_created_at": snapshot.created_at,
            }
        )
        return variables

    def append_missing_document_now_sections(
        self,
        prompt_content: str,
        message: str,
        variables: dict[str, str],
    ) -> str:
        sections = []
        if not (
            self.prompt_contains_variable(prompt_content, "date_today")
            or self.prompt_contains_variable(prompt_content, "current_date")
        ):
            sections.append(("DATE", variables.get("date_today", "")))

        if not (
            self.prompt_contains_variable(prompt_content, "patient_details")
            or self.prompt_contains_variable(prompt_content, "patient_identity")
        ):
            sections.append(("PATIENT", variables.get("patient_details", "")))

        if not self.prompt_contains_variable(prompt_content, "weda_context"):
            sections.append(("CONTEXTE WEDA", variables.get("weda_context", "")))

        if not (
            self.prompt_contains_variable(prompt_content, "snapshot_transcription")
            or self.prompt_contains_variable(prompt_content, "snapshot_de_transcription")
            or self.prompt_contains_variable(prompt_content, "transcription")
        ):
            sections.append(("SNAPSHOT DE TRANSCRIPTION", variables.get("snapshot_transcription", "")))

        source_block = "\n\n".join(f"{title} :\n{content}" for title, content in sections if content)
        if not source_block:
            return message.strip()

        header = "DONNÉES DU DOCUMENT INTERMÉDIAIRE (snapshot de transcription figé)"
        if not message.strip():
            return f"{header}\n\n{source_block}".strip()
        return f"{message.rstrip()}\n\n---\n{header}\n\n{source_block}".strip()

    def build_document_now_lmstudio_message(
        self,
        snapshot: DocumentNowSnapshot | None = None,
    ) -> tuple[str, dict[str, str], DocumentNowSnapshot]:
        snapshot = snapshot or self.document_now_current_snapshot or self.create_document_now_snapshot(
            f"preview-{uuid.uuid4().hex[:8]}",
            status="preview",
        )
        selected_prompt_content = (
            self.get_text(self.document_now_prompt_text) if hasattr(self, "document_now_prompt_text") else (
                snapshot.prompt_content or DEFAULT_DOCUMENT_NOW_PROMPT
            )
        ) if self.include_prompt_var.get() else ""
        prompt_content = self.compose_document_now_prompt_content(selected_prompt_content) if self.include_prompt_var.get() else ""
        prompt_id = self.current_document_now_prompt_id()
        prompt = self.prompt_manager.get(prompt_id) if prompt_id else None
        snapshot.prompt_id = prompt.id if prompt else prompt_id or snapshot.prompt_id
        snapshot.prompt_name = prompt.name if prompt else self.document_now_prompt_var.get() or snapshot.prompt_name
        snapshot.prompt_content = prompt_content
        variables = self.build_document_now_prompt_variables(snapshot)
        def render_message(working_variables: dict[str, str]) -> str:
            rendered = self.prompt_manager.render_prompt(prompt_content, working_variables) if prompt_content.strip() else ""
            rendered = self.append_missing_document_now_sections(prompt_content, rendered, working_variables)
            rendered = self.append_message_attachment_section(prompt_content, rendered, working_variables)
            return rendered

        message, variables = self.apply_lmstudio_context_limit(
            prompt_content,
            variables,
            render_message,
            label="document_maintenant",
        )
        return message, variables, snapshot

    def refresh_document_now_sent_message(self) -> str:
        self._document_now_message_refresh_job = None
        try:
            message, _variables, _snapshot = self.build_document_now_lmstudio_message()
        except Exception as exc:
            message = f"[Message Document maintenant non disponible] {exc}"
        self.set_text(self.document_now_sent_message_text, message, readonly=True)
        return message

    def preview_document_now_message(self) -> str:
        message = self.refresh_document_now_sent_message()
        self.select_tab_containing_widget(self.document_now_sent_message_text)
        self.log_debug(
            "info",
            "app",
            "document_now_message_previewed",
            "Message Document maintenant prévisualisé.",
            {
                "prompt_name": self.document_now_prompt_var.get(),
                "message_length": len(message),
                "has_snapshot": bool(self.document_now_current_snapshot),
            },
        )
        return message

    def document_now_checkpoint(self) -> None:
        if self.document_now_running:
            self.document_now_status_var.set("Document maintenant: génération déjà en cours")
            return
        if self.context_manager.get_latest() is not None and not self.require_fresh_patient_context(
            "Document maintenant"
        ):
            return
        if self.document_now_pending_checkpoints:
            self.document_now_status_var.set("Document maintenant: checkpoint déjà en attente de transcription")
            return

        checkpoint_id = f"checkpoint-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.document_now_pending_checkpoints[checkpoint_id] = {"created_at": time.time()}
        self.document_now_status_var.set("Document maintenant: checkpoint demandé, flush du segment audio")
        self.log_debug(
            "info",
            "app",
            "document_now_checkpoint_requested",
            "Checkpoint Document maintenant demandé.",
            {
                "checkpoint_id": checkpoint_id,
                "session_running": bool(self.session and self.session.is_running()),
                "transcription_length": len(self.get_clean_transcription_text()),
            },
        )

        if self.session and self.session.is_running() and self.session.request_checkpoint(checkpoint_id):
            self.transcription_status_var.set("Checkpoint Document maintenant: segment en transcription")
            return

        self.document_now_pending_checkpoints.pop(checkpoint_id, None)
        snapshot = self.create_document_now_snapshot(checkpoint_id, status="snapshot_ready")
        self.run_document_now_snapshot(snapshot, trigger="no_active_recording")

    def request_connector_document_now_checkpoint(
        self,
        job_id: str,
        *,
        expected_patient_id: str = "",
    ) -> None:
        if self.document_now_running:
            raise RuntimeError("Une génération « Document maintenant » est déjà en cours.")
        if self.document_now_pending_checkpoints:
            raise RuntimeError("Un checkpoint « Document maintenant » est déjà en attente.")
        context = self.context_manager.get_latest()
        if (
            context is not None
            and expected_patient_id
            and context.patient_id
            and not patient_ids_match(context.patient_id, expected_patient_id)
        ):
            raise RuntimeError(
                "Le patient WEDA actif ne correspond pas au contexte chargé dans DrFloW."
            )
        if context is not None and not self.require_fresh_patient_context(
            "Document maintenant depuis WEDA"
        ):
            raise RuntimeError("Le contexte patient WEDA doit être confirmé avant la génération.")

        checkpoint_id = f"connector-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.document_now_pending_checkpoints[checkpoint_id] = {
            "created_at": time.time(),
            "trigger": "connector_weda",
            "connector_job_id": job_id,
        }
        self.set_document_now_connector_job(
            {
                "status": "waiting_transcription",
                "message": "Création du snapshot de transcription.",
                "snapshot_id": checkpoint_id,
            },
            job_id=job_id,
        )
        self.document_now_status_var.set("Document maintenant: demande reçue depuis WEDA")
        self.log_debug(
            "info",
            "connector",
            "connector_document_now_checkpoint_requested",
            "Checkpoint Document maintenant demandé depuis WEDA.",
            {
                "job_id": job_id,
                "checkpoint_id": checkpoint_id,
                "session_running": bool(self.session and self.session.is_running()),
                "transcription_length": len(self.get_clean_transcription_text()),
            },
        )

        if self.session and self.session.is_running() and self.session.request_checkpoint(checkpoint_id):
            self.transcription_status_var.set("Checkpoint WEDA Document maintenant: segment en transcription")
            return

        self.document_now_pending_checkpoints.pop(checkpoint_id, None)
        snapshot = self.create_document_now_snapshot(checkpoint_id, status="snapshot_ready")
        self.set_document_now_connector_job(
            {
                "status": "generating",
                "message": "Génération de « Document maintenant » par LM Studio.",
            },
            job_id=job_id,
        )
        self.run_document_now_snapshot(snapshot, trigger="connector_weda_no_active_recording")
        if snapshot.status != "generating":
            raise RuntimeError(snapshot.error or "La génération « Document maintenant » n’a pas pu démarrer.")

    def send_document_now_from_message_tab(self) -> None:
        if self.document_now_current_snapshot:
            self.regenerate_document_now_from_snapshot()
            return
        self.document_now_checkpoint()

    def handle_document_now_checkpoints(self, result) -> None:
        checkpoint_ids = list(getattr(result, "checkpoint_ids", None) or [])
        if not checkpoint_ids:
            return
        for checkpoint_id in checkpoint_ids:
            checkpoint = self.document_now_pending_checkpoints.pop(checkpoint_id, None) or {}
            snapshot = self.create_document_now_snapshot(checkpoint_id, result, status="snapshot_ready")
            connector_job_id = str(checkpoint.get("connector_job_id") or "")
            if connector_job_id:
                self.set_document_now_connector_job(
                    {
                        "status": "generating",
                        "message": "Génération de « Document maintenant » par LM Studio.",
                        "snapshot_id": checkpoint_id,
                    },
                    job_id=connector_job_id,
                )
            trigger = str(checkpoint.get("trigger") or "checkpoint_flush")
            self.run_document_now_snapshot(snapshot, trigger=trigger)
            if connector_job_id and snapshot.status != "generating":
                self.set_document_now_connector_job(
                    {
                        "status": "error",
                        "message": snapshot.error or "La génération « Document maintenant » n’a pas pu démarrer.",
                        "error": snapshot.error or "document_now_start_failed",
                    },
                    job_id=connector_job_id,
                )

    def run_document_now_snapshot(self, snapshot: DocumentNowSnapshot, *, trigger: str = "manual") -> None:
        if self.document_now_running:
            self.document_now_status_var.set("Document maintenant: génération déjà en cours")
            return
        try:
            message, variables, snapshot = self.build_document_now_lmstudio_message(snapshot)
        except Exception as exc:
            snapshot.status = "error"
            snapshot.error = str(exc)
            self.document_now_current_snapshot = snapshot
            self.document_now_snapshots[snapshot.id] = snapshot
            self.document_now_status_var.set("Document maintenant: message impossible")
            messagebox.showerror("Document maintenant", str(exc), parent=self.root)
            return

        message = message.strip()
        if not message:
            snapshot.status = "error"
            snapshot.error = "message LM Studio vide"
            self.document_now_current_snapshot = snapshot
            self.document_now_snapshots[snapshot.id] = snapshot
            self.document_now_status_var.set("Document maintenant: message vide")
            messagebox.showwarning(
                "Document maintenant",
                "Le message à envoyer est vide. Ajoute un prompt, une transcription ou un contexte.",
                parent=self.root,
            )
            return

        snapshot.sent_message = message
        snapshot.status = "generating"
        snapshot.error = None
        self.document_now_current_snapshot = snapshot
        self.document_now_snapshots[snapshot.id] = snapshot
        self.set_text(self.document_now_sent_message_text, message, readonly=True)
        self.set_text(self.document_now_result_text, "")
        self.document_now_running = True
        self.configure_document_now_button_state()
        self.document_now_status_var.set("Document maintenant: génération du document intermédiaire")
        self.lmstudio_status_var.set("LM Studio: Document maintenant en cours")
        self.start_lmstudio_spinner(DOCUMENT_NOW_SPINNER_KEY)
        self.select_tab_containing_widget(self.document_now_sent_message_text)
        lm_config = self.config.get("lmstudio", {})
        client = self.build_lmstudio_client()
        self.adjust_lmstudio_client_for_context(client, message, label="document_maintenant")
        self.log_debug(
            "info",
            "app",
            "document_now_lmstudio_request_started",
            "Génération Document maintenant lancée.",
            {
                "checkpoint_id": snapshot.id,
                "trigger": trigger,
                "prompt_name": variables.get("prompt_name", ""),
                "url": str(lm_config.get("url") or "http://localhost:1234/v1/chat/completions"),
                "model": str(lm_config.get("model") or "local-model"),
                "message_length": len(message),
                "snapshot_transcription_length": len(snapshot.transcript_text or ""),
                "weda_context_length": len(snapshot.weda_context or ""),
            },
        )

        self.launch_lmstudio_request(
            "document_now",
            client,
            message,
            on_success=lambda response: self.on_document_now_response(snapshot.id, response, message),
            on_error=lambda error: self.on_document_now_error(snapshot.id, error, message),
            thread_name="lmstudio-document-now-request",
            result_source="document_now",
        )

    def configure_document_now_button_state(self) -> None:
        if hasattr(self, "document_now_button"):
            self.document_now_button.configure(state=tk.DISABLED if self.document_now_running else tk.NORMAL)

    def on_document_now_response(self, snapshot_id: str, response, sent_message: str) -> None:
        self.stop_lmstudio_spinner(DOCUMENT_NOW_SPINNER_KEY)
        snapshot = self.document_now_snapshots.get(snapshot_id) or self.document_now_current_snapshot
        result_text = self.apply_abbreviations_to_lmstudio_result(response.text, "Document maintenant")
        result_payload = self.remember_weda_result_payload("document_now", result_text)
        self.record_generation_metric(
            "document_now",
            "document_now",
            status="success",
            elapsed_seconds=response.elapsed_seconds,
            input_chars=len(sent_message or ""),
            result_chars=len(result_payload.text or ""),
        )
        if snapshot:
            snapshot.result = result_payload.text
            snapshot.sent_message = sent_message
            snapshot.status = "done"
            snapshot.error = None
            self.document_now_snapshots[snapshot.id] = snapshot
            self.document_now_current_snapshot = snapshot
        self.document_now_running = False
        self.configure_document_now_button_state()
        self.set_rich_result_text(self.document_now_result_text, result_payload, source="document_now")
        self.select_tab_containing_widget(self.document_now_result_text)
        self.document_now_status_var.set(f"Document maintenant: reçu en {response.elapsed_seconds:.1f}s")
        self.lmstudio_status_var.set(f"LM Studio: Document maintenant reçu en {response.elapsed_seconds:.1f}s")
        self.log_debug(
            "info",
            "app",
            "document_now_lmstudio_response",
            "Document intermédiaire reçu.",
            {
                "checkpoint_id": snapshot_id,
                "elapsed_seconds": response.elapsed_seconds,
                "raw_result_length": len(response.text or ""),
                "result_length": len(result_payload.text or ""),
                "result_html_length": len(result_payload.html or ""),
            },
        )
        self.finalize_document_now_connector_result(
            snapshot_id,
            result_payload,
            elapsed_seconds=response.elapsed_seconds,
        )
        if snapshot:
            self.append_document_now_history(snapshot, sent_message, result_payload.text)

    def on_document_now_error(self, snapshot_id: str, error: Exception, sent_message: str) -> None:
        self.stop_lmstudio_spinner(DOCUMENT_NOW_SPINNER_KEY)
        self.discard_pending_result_patient_binding("document_now")
        snapshot = self.document_now_snapshots.get(snapshot_id) or self.document_now_current_snapshot
        if self.lmstudio_request_was_cancelled(error):
            self.record_generation_metric(
                "document_now",
                "document_now",
                status="cancelled",
                input_chars=len(sent_message or ""),
                error=error,
            )
            if snapshot:
                snapshot.status = "cancelled"
                snapshot.error = str(error)
            self.document_now_running = False
            self.configure_document_now_button_state()
            self.document_now_status_var.set("Document maintenant: génération annulée")
            self.lmstudio_status_var.set("LM Studio: génération annulée")
            self.log_debug("info", "app", "document_now_lmstudio_cancelled", str(error))
            self.fail_document_now_connector_job(snapshot_id, error)
            return
        self.record_generation_metric(
            "document_now",
            "document_now",
            status="error",
            input_chars=len(sent_message or ""),
            error=error,
        )
        message = f"Erreur Document maintenant : {error}"
        if snapshot:
            snapshot.sent_message = sent_message
            snapshot.status = "error"
            snapshot.error = str(error)
            self.document_now_snapshots[snapshot.id] = snapshot
            self.document_now_current_snapshot = snapshot
        self.document_now_running = False
        self.configure_document_now_button_state()
        self.set_text(self.document_now_result_text, message)
        self.select_tab_containing_widget(self.document_now_result_text)
        self.document_now_status_var.set("Document maintenant: erreur")
        self.lmstudio_status_var.set("LM Studio: erreur Document maintenant")
        self.log_debug(
            "error",
            "app",
            "document_now_lmstudio_error",
            str(error),
            {
                "checkpoint_id": snapshot_id,
                "message_length": len(sent_message or ""),
            },
        )
        self.fail_document_now_connector_job(snapshot_id, error)
        messagebox.showerror("Document maintenant", str(error), parent=self.root)

    def finalize_document_now_connector_result(
        self,
        snapshot_id: str,
        result_payload: RichTextPayload,
        *,
        elapsed_seconds: float,
    ) -> bool:
        job = self.get_document_now_connector_job()
        if not job or job.get("snapshot_id") != snapshot_id:
            return False
        try:
            copied = bool(self.copy_rich_result_source("document_now"))
        except Exception as exc:
            copied = False
            copy_error = str(exc)
        else:
            copy_error = ""

        if copied:
            self.set_document_now_connector_job(
                {
                    "status": "ready",
                    "message": "Document maintenant prêt à être collé.",
                    "clipboard_copied": True,
                    "result_length": len(result_payload.text or ""),
                    "result_html_length": len(result_payload.html or ""),
                    "elapsed_seconds": elapsed_seconds,
                },
                job_id=str(job.get("id") or ""),
            )
            self.document_now_status_var.set("Document maintenant: copié, prêt à coller dans WEDA")
            self.log_debug(
                "info",
                "connector",
                "connector_document_now_ready",
                "Document maintenant généré et copié dans le presse-papiers.",
                {
                    "job_id": job.get("id"),
                    "checkpoint_id": snapshot_id,
                    "result_length": len(result_payload.text or ""),
                    "result_html_length": len(result_payload.html or ""),
                    "elapsed_seconds": elapsed_seconds,
                },
            )
            return True

        error_message = copy_error or "La copie automatique dans le presse-papiers a échoué."
        self.set_document_now_connector_job(
            {
                "status": "error",
                "message": error_message,
                "error": error_message,
                "clipboard_copied": False,
            },
            job_id=str(job.get("id") or ""),
        )
        self.document_now_status_var.set("Document maintenant: copie automatique impossible")
        self.log_debug(
            "error",
            "connector",
            "connector_document_now_clipboard_error",
            error_message,
            {"job_id": job.get("id"), "checkpoint_id": snapshot_id},
        )
        return False

    def fail_document_now_connector_job(self, snapshot_id: str, error: Exception | str) -> None:
        job = self.get_document_now_connector_job()
        if not job or job.get("snapshot_id") != snapshot_id:
            return
        message = str(error or "Erreur de génération « Document maintenant ».")
        self.set_document_now_connector_job(
            {
                "status": "error",
                "message": message,
                "error": message,
                "clipboard_copied": False,
            },
            job_id=str(job.get("id") or ""),
        )

    def append_document_now_history(
        self,
        snapshot: DocumentNowSnapshot,
        sent_message: str,
        result_text: str,
    ) -> None:
        self.history_manager.append(
            {
                **self.current_stt_history_payload(),
                "status": "document_now_response",
                "document_label": "Document maintenant",
                "document_type": snapshot.document_type,
                "document_now_snapshot": asdict(snapshot),
                "checkpoint_id": snapshot.id,
                "snapshot_created_at": snapshot.created_at,
                "prompt_id": snapshot.prompt_id or "",
                "prompt_name": snapshot.prompt_name or self.document_now_prompt_var.get(),
                "transcription": self.get_clean_transcription_text(),
                "snapshot_transcription": snapshot.transcript_text,
                "weda_context": snapshot.weda_context or "",
                "sent_message": sent_message,
                "lmstudio_result": result_text,
            }
        )

    def regenerate_document_now_from_snapshot(self) -> None:
        snapshot = self.document_now_current_snapshot
        if not snapshot:
            messagebox.showinfo(
                "Document maintenant",
                "Aucun snapshot de transcription n’est disponible pour régénérer.",
                parent=self.root,
            )
            return
        snapshot.result = None
        snapshot.status = "snapshot_ready"
        snapshot.error = None
        self.run_document_now_snapshot(snapshot, trigger="regenerate_same_snapshot")

    def copy_document_now_result(self) -> None:
        ok = self.copy_rich_result_source("document_now")
        self.document_now_status_var.set("Document maintenant: résultat WEDA copié" if ok else "Document maintenant: copie impossible")

    def clear_document_now_result(self) -> None:
        self.set_text(self.document_now_result_text, "")
        self.rich_result_payloads.pop("document_now", None)
        self.result_patient_bindings.pop("document_now", None)
        self.generated_result_originals.pop("document_now", None)
        self.result_generation_metadata.pop("document_now", None)
        if self.document_now_current_snapshot:
            self.document_now_current_snapshot.result = None
            self.document_now_current_snapshot.status = "cleared"
        self.document_now_status_var.set("Document maintenant: résultat effacé")

    def build_secondary_lmstudio_message(self) -> tuple[str, dict[str, str]]:
        result_1 = self.get_text(self.result_text).strip()
        if not result_1:
            raise RuntimeError("Prompt 2 nécessite un Résultat 1 non vide.")

        prompt_2 = None
        prompt_2_id = self.current_secondary_prompt_id()
        if self.include_prompt_var.get():
            prompt_2 = self.prompt_manager.get(prompt_2_id) if prompt_2_id else None
            if prompt_2 is None:
                raise RuntimeError("Prompt 2 activé mais aucun prompt secondaire n’est sélectionné.")
        prompt_1 = self.prompt_manager.get(self.current_prompt_id())
        prompt_1_content = self.get_text(self.prompt_text)
        prompt_2_content = self.get_text(self.secondary_prompt_text) if self.include_prompt_var.get() else ""
        variables = build_secondary_prompt_variables(
            self.build_prompt_variables(),
            prompt_1_name=prompt_1.name if prompt_1 else self.prompt_var.get(),
            prompt_1_content=prompt_1_content,
            prompt_2_name=prompt_2.name if prompt_2 else self.secondary_prompt_var.get(),
            prompt_2_content=prompt_2_content,
            result_1=result_1,
        )
        missing = find_unresolved_variables(prompt_2_content, variables)
        if missing:
            raise RuntimeError("Variable(s) inconnue(s) dans Prompt 2 : " + ", ".join(missing))

        def render_message(working_variables: dict[str, str]) -> str:
            if self.include_prompt_var.get():
                rendered = self.prompt_manager.render_prompt(prompt_2_content, working_variables)
                return append_missing_secondary_sections(prompt_2_content, rendered, working_variables)
            source_sections = []
            for variable_name, title in (
                ("current_date", "DATE DU JOUR"),
                ("patient_identity", "PATIENT"),
                ("weda_context", "CONTEXTE WEDA"),
                ("transcription", "TRANSCRIPTION INITIALE"),
                ("result_1", "RÉSULTAT 1"),
            ):
                value = str(working_variables.get(variable_name) or "").strip()
                if value:
                    source_sections.append(f"{title} :\n{value}")
            return "\n\n".join(source_sections)

        message, variables = self.apply_lmstudio_context_limit(
            prompt_2_content,
            variables,
            lambda working_variables: self.append_message_attachment_section(
                prompt_2_content,
                render_message(working_variables),
                working_variables,
            ),
            label="prompt_2",
        )
        if not message.strip():
            raise RuntimeError("Message Prompt 2 vide après résolution des variables.")
        return message, variables

    def refresh_secondary_sent_message(self) -> str:
        self._secondary_message_refresh_job = None
        if not self.secondary_enabled_var.get() and not self.get_text(self.result_text).strip():
            self.set_text(self.secondary_sent_message_text, "", readonly=True)
            return ""
        try:
            message, _variables = self.build_secondary_lmstudio_message()
        except Exception as exc:
            message = f"[Message 2 non disponible] {exc}"
        self.set_text(self.secondary_sent_message_text, message, readonly=True)
        return message

    def build_tertiary_lmstudio_message(self) -> tuple[str, dict[str, str]]:
        result_1 = self.get_text(self.result_text).strip()
        result_2 = self.get_text(self.secondary_result_text).strip()
        if not result_2:
            raise RuntimeError("Prompt 3 nécessite un Résultat 2 non vide.")

        prompt_3 = None
        prompt_3_id = self.current_tertiary_prompt_id()
        if self.include_prompt_var.get():
            prompt_3 = self.prompt_manager.get(prompt_3_id) if prompt_3_id else None
            if prompt_3 is None:
                raise RuntimeError("Prompt 3 activé mais aucun prompt tertiaire n’est sélectionné.")
        prompt_1 = self.prompt_manager.get(self.current_prompt_id())
        prompt_2 = self.prompt_manager.get(self.current_secondary_prompt_id())
        prompt_1_content = self.get_text(self.prompt_text)
        prompt_2_content = self.get_text(self.secondary_prompt_text)
        prompt_3_content = self.get_text(self.tertiary_prompt_text) if self.include_prompt_var.get() else ""
        variables = build_tertiary_prompt_variables(
            self.build_prompt_variables(),
            prompt_1_name=prompt_1.name if prompt_1 else self.prompt_var.get(),
            prompt_1_content=prompt_1_content,
            prompt_2_name=prompt_2.name if prompt_2 else self.secondary_prompt_var.get(),
            prompt_2_content=prompt_2_content,
            prompt_3_name=prompt_3.name if prompt_3 else self.tertiary_prompt_var.get(),
            prompt_3_content=prompt_3_content,
            result_1=result_1,
            result_2=result_2,
        )
        missing = find_unresolved_variables(prompt_3_content, variables)
        if missing:
            raise RuntimeError("Variable(s) inconnue(s) dans Prompt 3 : " + ", ".join(missing))

        def render_message(working_variables: dict[str, str]) -> str:
            if self.include_prompt_var.get():
                rendered = self.prompt_manager.render_prompt(prompt_3_content, working_variables)
                return append_missing_tertiary_sections(prompt_3_content, rendered, working_variables)
            source_sections = []
            for variable_name, title in (
                ("current_date", "DATE DU JOUR"),
                ("patient_identity", "PATIENT"),
                ("weda_context", "CONTEXTE WEDA"),
                ("transcription", "TRANSCRIPTION INITIALE"),
                ("result_1", "RÉSULTAT 1"),
                ("result_2", "RÉSULTAT 2"),
            ):
                value = str(working_variables.get(variable_name) or "").strip()
                if value:
                    source_sections.append(f"{title} :\n{value}")
            return "\n\n".join(source_sections)

        message, variables = self.apply_lmstudio_context_limit(
            prompt_3_content,
            variables,
            lambda working_variables: self.append_message_attachment_section(
                prompt_3_content,
                render_message(working_variables),
                working_variables,
            ),
            label="prompt_3",
        )
        if not message.strip():
            raise RuntimeError("Message Prompt 3 vide après résolution des variables.")
        return message, variables

    def refresh_tertiary_sent_message(self) -> str:
        self._tertiary_message_refresh_job = None
        if not self.tertiary_enabled_var.get() and not self.get_text(self.secondary_result_text).strip():
            self.set_text(self.tertiary_sent_message_text, "", readonly=True)
            return ""
        try:
            message, _variables = self.build_tertiary_lmstudio_message()
        except Exception as exc:
            message = f"[Message 3 non disponible] {exc}"
        self.set_text(self.tertiary_sent_message_text, message, readonly=True)
        return message

    def select_tab_containing_widget(self, widget: tk.Widget) -> None:
        current = widget
        while current is not None:
            parent = current.master
            if isinstance(parent, ttk.Notebook):
                try:
                    parent.select(current)
                except tk.TclError:
                    pass
            current = parent

    def install_text_search_shortcuts(self) -> None:
        self.root.bind_all("<Control-f>", self.open_text_search, add="+")
        self.root.bind_all("<Control-F>", self.open_text_search, add="+")

    def open_text_search(self, event=None):
        self.ensure_text_search_window()
        selected_text = self.get_active_text_selection_for_search()
        if selected_text:
            self.text_search_query_var.set(selected_text)
        if self.text_search_window is not None:
            self.text_search_window.deiconify()
            self.text_search_window.lift()
        if hasattr(self, "text_search_entry"):
            self.text_search_entry.focus_set()
            self.text_search_entry.select_range(0, tk.END)
        self.refresh_text_search_matches()
        return "break"

    def ensure_text_search_window(self) -> None:
        if self.text_search_window is not None and self.text_search_window.winfo_exists():
            return

        window = tk.Toplevel(self.root)
        window.title("Recherche")
        window.transient(self.root)
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", self.close_text_search)

        frame = ttk.Frame(window, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Rechercher").grid(row=0, column=0, sticky=tk.W, padx=(0, 8))
        self.text_search_entry = ttk.Entry(frame, textvariable=self.text_search_query_var, width=42)
        self.text_search_entry.grid(row=0, column=1, columnspan=3, sticky=tk.EW)
        self.text_search_entry.bind("<KeyRelease>", self.on_text_search_entry_key_release)
        self.text_search_entry.bind("<Return>", self.goto_next_text_search_match_event)
        self.text_search_entry.bind("<Shift-Return>", self.goto_previous_text_search_match_event)

        ttk.Button(frame, text="Précédent", command=self.goto_previous_text_search_match).grid(row=1, column=1, sticky=tk.EW, pady=(8, 0), padx=(0, 6))
        ttk.Button(frame, text="Suivant", command=self.goto_next_text_search_match).grid(row=1, column=2, sticky=tk.EW, pady=(8, 0), padx=(0, 6))
        ttk.Button(frame, text="Fermer", command=self.close_text_search).grid(row=1, column=3, sticky=tk.EW, pady=(8, 0))
        ttk.Label(frame, textvariable=self.text_search_status_var).grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=(8, 0))
        frame.columnconfigure(1, weight=1)
        window.bind("<Escape>", self.close_text_search)
        self.text_search_window = window

    def close_text_search(self, event=None):
        self.clear_text_search_highlights()
        if self.text_search_window is not None and self.text_search_window.winfo_exists():
            self.text_search_window.withdraw()
        return "break"

    def on_text_search_entry_key_release(self, event=None) -> None:
        ignored_keys = {"Return", "Escape", "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"}
        if event is not None and getattr(event, "keysym", "") in ignored_keys:
            return
        self.refresh_text_search_matches()

    def goto_next_text_search_match_event(self, event=None):
        self.goto_next_text_search_match()
        return "break"

    def goto_previous_text_search_match_event(self, event=None):
        self.goto_previous_text_search_match()
        return "break"

    def get_active_text_selection_for_search(self) -> str:
        try:
            focused = self.root.focus_get()
        except tk.TclError:
            focused = None
        if not isinstance(focused, tk.Text):
            return ""
        try:
            selected = focused.get("sel.first", "sel.last")
        except tk.TclError:
            return ""
        return re.sub(r"\s+", " ", selected).strip()[:120]

    def get_searchable_text_widgets(self) -> list[tk.Text]:
        widgets: list[tk.Text] = []

        def visit(widget: tk.Widget) -> None:
            try:
                if isinstance(widget, tk.Text):
                    widgets.append(widget)
                for child in widget.winfo_children():
                    visit(child)
            except tk.TclError:
                return

        visit(self.root)
        return widgets

    def configure_text_search_tags(self, widget: tk.Text) -> None:
        try:
            widget.tag_configure(TEXT_SEARCH_MATCH_TAG, background="#334155", foreground="#f8fafc")
            widget.tag_configure(TEXT_SEARCH_CURRENT_TAG, background="#facc15", foreground="#111827")
            widget.tag_raise(TEXT_SEARCH_CURRENT_TAG, TEXT_SEARCH_MATCH_TAG)
        except tk.TclError:
            pass

    def clear_text_search_highlights(self) -> None:
        for widget in self.get_searchable_text_widgets():
            try:
                widget.tag_remove(TEXT_SEARCH_MATCH_TAG, "1.0", tk.END)
                widget.tag_remove(TEXT_SEARCH_CURRENT_TAG, "1.0", tk.END)
            except tk.TclError:
                continue
        self.text_search_matches = []
        self.text_search_current_index = -1

    def clear_current_text_search_highlight(self) -> None:
        for widget in self.get_searchable_text_widgets():
            try:
                widget.tag_remove(TEXT_SEARCH_CURRENT_TAG, "1.0", tk.END)
            except tk.TclError:
                continue

    def refresh_text_search_matches(self) -> None:
        query = self.text_search_query_var.get()
        self.clear_text_search_highlights()
        if not query:
            self.text_search_status_var.set("Saisir un terme à rechercher.")
            return

        for widget in self.get_searchable_text_widgets():
            self.configure_text_search_tags(widget)
            start = "1.0"
            while True:
                try:
                    match_start = widget.search(query, start, stopindex=tk.END, nocase=True, regexp=False)
                except tk.TclError:
                    break
                if not match_start:
                    break
                match_end = f"{match_start}+{len(query)}c"
                try:
                    widget.tag_add(TEXT_SEARCH_MATCH_TAG, match_start, match_end)
                except tk.TclError:
                    break
                self.text_search_matches.append((widget, match_start, match_end))
                start = match_end

        if not self.text_search_matches:
            self.text_search_status_var.set(f"Aucun résultat pour « {query} ».")
            return

        self.goto_text_search_match(0)

    def goto_next_text_search_match(self) -> None:
        if not self.text_search_matches:
            self.refresh_text_search_matches()
            return
        self.goto_text_search_match(self.text_search_current_index + 1)

    def goto_previous_text_search_match(self) -> None:
        if not self.text_search_matches:
            self.refresh_text_search_matches()
            return
        index = self.text_search_current_index - 1
        if self.text_search_current_index < 0:
            index = len(self.text_search_matches) - 1
        self.goto_text_search_match(index)

    def goto_text_search_match(self, index: int) -> None:
        if not self.text_search_matches:
            self.text_search_status_var.set("Aucun résultat.")
            return

        match_index = index % len(self.text_search_matches)
        widget, start, end = self.text_search_matches[match_index]
        self.clear_current_text_search_highlight()
        try:
            self.configure_text_search_tags(widget)
            widget.tag_add(TEXT_SEARCH_CURRENT_TAG, start, end)
            self.select_tab_containing_widget(widget)
            widget.see(start)
            widget.mark_set(tk.INSERT, end)
        except tk.TclError:
            self.refresh_text_search_matches()
            return

        self.text_search_current_index = match_index
        label = self.get_text_search_widget_label(widget)
        self.text_search_status_var.set(f"Résultat {match_index + 1}/{len(self.text_search_matches)} - {label}")

    def get_text_search_widget_label(self, widget: tk.Widget) -> str:
        labels: list[str] = []
        current = widget
        while current is not None:
            parent = current.master
            if isinstance(parent, ttk.Notebook):
                try:
                    label = str(parent.tab(current, "text") or "").strip()
                    if label:
                        labels.append(label)
                except tk.TclError:
                    pass
            current = parent
        return " > ".join(reversed(labels)) or "champ texte"

    def call_ui_sync(self, func, *, timeout_seconds: float = 10.0):
        if threading.get_ident() == self.main_thread_id:
            return func()

        done = threading.Event()
        box: dict = {}

        def wrapper():
            try:
                box["result"] = func()
            except Exception as exc:
                box["error"] = exc
            finally:
                done.set()

        self.root.after(0, wrapper)
        if not done.wait(timeout_seconds):
            raise TimeoutError("Interface graphique indisponible.")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def start_server(self) -> None:
        server_config = self.config.get("server", {})
        host = str(server_config.get("host") or "127.0.0.1")
        port = int(server_config.get("port") or 8765)
        try:
            self.server = LocalServer(
                host=host,
                port=port,
                context_manager=self.context_manager,
                import_manager=self.import_manager,
                debug_logger=self.debug_logger,
                settings_provider=self.get_public_settings,
                connector_start_handler=self.connector_start,
                connector_stop_handler=self.connector_stop,
                connector_status_provider=self.get_connector_job,
                connector_document_now_handler=self.connector_document_now,
                connector_document_now_status_provider=self.get_document_now_connector_job,
                context_refresh_provider=self.get_weda_context_refresh_request,
                context_refresh_claim_handler=self.claim_weda_context_refresh,
                context_refresh_ack_handler=self.acknowledge_weda_context_refresh,
                fly_dictation_start_handler=self.fly_dictation_start,
                fly_dictation_stop_handler=self.fly_dictation_stop,
                fly_dictation_status_provider=self.get_fly_dictation_state,
                on_context=self.on_server_context,
                on_import_status=self.on_import_status,
                on_debug_log=self.on_debug_log,
            )
            self.server.start()
            self.server_status_var.set(f"Serveur local: {host}:{port}")
            self.log_debug("info", "app", "server_started", "Serveur local démarré.", {"host": host, "port": port})
        except Exception as exc:
            self.server_status_var.set("Serveur local: erreur")
            self.log_debug("error", "app", "server_error", str(exc), {"host": host, "port": port})
            messagebox.showerror("Serveur local", str(exc))

    def get_saved_window_geometry(self) -> str:
        ui_config = self.config.get("ui", {})
        width = self.parse_dimension(ui_config.get("window_width"), 1180)
        height = self.parse_dimension(ui_config.get("window_height"), 780)
        width = max(900, min(width, max(900, self.root.winfo_screenwidth())))
        height = max(560, min(height, max(560, self.root.winfo_screenheight())))
        return f"{width}x{height}"

    def parse_dimension(self, value, fallback: int) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return fallback

    def on_root_configure(self, event) -> None:
        if event.widget is not self.root:
            return
        try:
            if self.root.state() in {"zoomed", "iconic"}:
                return
        except Exception:
            pass

        width = int(event.width)
        height = int(event.height)
        if width < 900 or height < 560:
            return

        if self._window_geometry_save_job:
            try:
                self.root.after_cancel(self._window_geometry_save_job)
            except Exception:
                pass
        self._window_geometry_save_job = self.root.after(700, self.save_window_geometry, width, height)

    def save_window_geometry(self, width: int, height: int) -> None:
        self._window_geometry_save_job = None
        ui_config = self.config.setdefault("ui", {})
        if ui_config.get("window_width") == width and ui_config.get("window_height") == height:
            return
        ui_config["window_width"] = width
        ui_config["window_height"] = height
        try:
            save_json(BASE_DIR / "config.json", self.config)
        except Exception as exc:
            self.log_debug("warning", "app", "window_geometry_save_error", str(exc), {
                "width": width,
                "height": height,
            })

    def ensure_stt_config(self) -> None:
        changed = ensure_stt_config(self.config)
        if changed:
            try:
                save_json(BASE_DIR / "config.json", self.config)
            except Exception:
                pass

    def ensure_medical_transcription_config(self) -> None:
        changed = False
        target = self.config.setdefault("medical_transcription", {})
        for key, value in DEFAULT_MEDICAL_TRANSCRIPTION_CONFIG.items():
            if key not in target:
                target[key] = list(value) if isinstance(value, list) else value
                changed = True
        for section_name in ("whisper", "faster_whisper"):
            section = self.config.setdefault(section_name, {})
            if float(section.get("segment_seconds") or 15) == 15:
                section["segment_seconds"] = TRANSCRIPTION_WINDOW_SECONDS
                changed = True
            if float(section.get("overlap_seconds") or 1) == 1:
                section["overlap_seconds"] = TRANSCRIPTION_OVERLAP_SECONDS
                changed = True
        if changed:
            try:
                save_json(BASE_DIR / "config.json", self.config)
            except Exception:
                pass

    def ensure_whisper_initial_prompts(self) -> None:
        if self.whisper_initial_prompt_manager.list_prompts():
            return

        whisper_config = self.config.setdefault("whisper", {})
        legacy_prompt = str(whisper_config.get("initial_prompt") or "").strip()
        prompt = self.whisper_initial_prompt_manager.create(
            "Médical général",
            legacy_prompt or DEFAULT_WHISPER_INITIAL_PROMPT,
            is_default=True,
        )
        whisper_config["initial_prompt"] = prompt.content
        whisper_config["initial_prompt_name"] = prompt.name

    def get_active_whisper_initial_prompt_text(self) -> str:
        if hasattr(self, "whisper_initial_prompt_text"):
            return self.get_text(self.whisper_initial_prompt_text).strip()
        prompt = self.whisper_initial_prompt_manager.get_default()
        if prompt:
            return prompt.content
        return str(self.config.get("whisper", {}).get("initial_prompt") or "")

    def sync_active_whisper_initial_prompt_config(self, prompt=None) -> None:
        if prompt is None:
            prompt = self.whisper_initial_prompt_manager.get(self.current_whisper_initial_prompt_id())
        whisper_config = self.config.setdefault("whisper", {})
        whisper_config["initial_prompt"] = self.get_active_whisper_initial_prompt_text()
        whisper_config["initial_prompt_name"] = prompt.name if prompt else self.whisper_initial_prompt_var.get()
        try:
            save_json(BASE_DIR / "config.json", self.config)
        except Exception as exc:
            self.log_debug("error", "app", "whisper_initial_prompt_config_save_error", str(exc))

    def selected_stt_engine_id(self) -> str:
        return normalize_engine_id(self.stt_engine_var.get() if hasattr(self, "stt_engine_var") else FASTER_WHISPER_ENGINE_ID)

    def normalize_whisper_runtime_values(self) -> tuple[str, str, str]:
        model = canonical_french_whisper_model_name(
            self.model_var.get() if hasattr(self, "model_var") else self.config.get("whisper", {}).get("default_model") or "medium"
        )
        if model not in WHISPER_MODEL_CHOICES:
            model = "medium"
        device = str(self.device_var.get() if hasattr(self, "device_var") else self.config.get("whisper", {}).get("device") or "cpu")
        if device not in WHISPER_DEVICE_CHOICES:
            device = "cpu"
        compute_type = str(
            self.compute_var.get() if hasattr(self, "compute_var") else self.config.get("whisper", {}).get("compute_type") or "int8"
        )
        if compute_type not in WHISPER_COMPUTE_CHOICES:
            compute_type = "int8"
        if hasattr(self, "model_var"):
            self.model_var.set(model)
        if hasattr(self, "device_var"):
            self.device_var.set(device)
        if hasattr(self, "compute_var"):
            self.compute_var.set(compute_type)
        return model, device, compute_type

    def capture_whisper_runtime_settings(self) -> None:
        model, device, compute_type = self.normalize_whisper_runtime_values()
        input_device = self.selected_input_device() if hasattr(self, "micro_device_var") else str(
            self.config.get("whisper", {}).get("input_device") or ""
        )
        initial_prompt = self.get_active_whisper_initial_prompt_text() or DEFAULT_WHISPER_INITIAL_PROMPT
        faster = self.config.setdefault("faster_whisper", {})
        faster.update(
            {
                "enabled": True,
                "model": model,
                "device": device,
                "compute_type": compute_type,
                "input_device": input_device,
                "language": "fr",
                "task": "transcribe",
                "force_language": True,
                "disable_language_detection": True,
                "condition_on_previous_text": False,
                "initial_prompt": initial_prompt,
            }
        )
        whisper = self.config.setdefault("whisper", {})
        whisper.update(
            {
                "default_model": model,
                "device": device,
                "compute_type": compute_type,
                "input_device": input_device,
                "language": "fr",
                "task": "transcribe",
                "force_language": True,
                "disable_language_detection": True,
                "condition_on_previous_text": False,
                "initial_prompt": initial_prompt,
            }
        )

    def save_whisper_runtime_settings(self) -> None:
        self.capture_whisper_runtime_settings()
        if self.selected_stt_engine_id() == FASTER_WHISPER_ENGINE_ID:
            self.refresh_stt_engine_controls()
        if self.write_runtime_config("whisper_runtime_settings") and hasattr(self, "model_status_var"):
            self.model_status_var.set("Moteur STT: réglages enregistrés")

    def get_stt_benchmark_engine_settings(self) -> dict[str, bool]:
        return {
            FASTER_WHISPER_ENGINE_ID: bool(self.stt_compare_faster_var.get()) if hasattr(self, "stt_compare_faster_var") else True,
            QWEN3_ASR_ENGINE_ID: bool(self.stt_compare_qwen_var.get()) if hasattr(self, "stt_compare_qwen_var") else False,
            VOXTRAL_ENGINE_ID: bool(self.stt_compare_voxtral_var.get()) if hasattr(self, "stt_compare_voxtral_var") else False,
        }

    def capture_stt_runtime_settings(self) -> None:
        if not hasattr(self, "stt_engine_var"):
            self.capture_whisper_runtime_settings()
            return

        engine_id = self.selected_stt_engine_id()
        stt_config = self.config.setdefault("stt", {})
        stt_config["default_engine"] = engine_id
        stt_config["allow_experimental_engines"] = bool(self.stt_allow_experimental_var.get())
        stt_config["keep_audio_for_benchmark"] = bool(self.stt_keep_audio_var.get())
        stt_config["auto_fallback_to_faster_whisper"] = bool(self.stt_auto_fallback_var.get())
        stt_config["show_engine_warnings"] = bool(self.stt_show_warnings_var.get())
        stt_config["benchmark_engines"] = self.get_stt_benchmark_engine_settings()
        if hasattr(self, "stt_context_bias_text"):
            stt_config["stt_context_bias"] = self.get_text(self.stt_context_bias_text).strip()
        if hasattr(self, "stt_speaker_map_text"):
            stt_config["speaker_map"] = self.parse_stt_speaker_map(self.get_text(self.stt_speaker_map_text))

        if engine_id == FASTER_WHISPER_ENGINE_ID:
            selected_model = canonical_french_whisper_model_name(
                self.stt_model_var.get() or self.model_var.get() or "medium"
            )
            if selected_model not in WHISPER_MODEL_CHOICES:
                selected_model = "medium"
            selected_device = self.stt_device_var.get() or self.device_var.get() or "cpu"
            if selected_device not in WHISPER_DEVICE_CHOICES:
                selected_device = "cpu"
            compute_type = self.compute_var.get() or "int8"
            if compute_type not in WHISPER_COMPUTE_CHOICES:
                compute_type = "int8"
            self.stt_model_var.set(selected_model)
            self.model_var.set(selected_model)
            self.device_var.set(selected_device)
            self.compute_var.set(compute_type)
            self.capture_whisper_runtime_settings()
        else:
            self.capture_whisper_runtime_settings()
            target = self.config.setdefault(engine_id, {})
            target["enabled"] = True
            target["model"] = self.stt_model_var.get()
            target["runtime"] = self.stt_runtime_var.get()
            target["device"] = self.stt_device_var.get()
            target.setdefault("language", "fr")
            target.setdefault("mode", "batch")
            target["external_cli_command"] = self.stt_external_cli_var.get().strip()
            if engine_id == VOXTRAL_ENGINE_ID:
                target["server_url"] = self.stt_server_url_var.get().strip() or "http://127.0.0.1:8000"

    def refresh_stt_engine_controls(self) -> None:
        if not hasattr(self, "stt_model_combo"):
            return
        engine_id = self.selected_stt_engine_id()
        models = STT_ENGINE_MODEL_CHOICES.get(engine_id, STT_ENGINE_MODEL_CHOICES[FASTER_WHISPER_ENGINE_ID])
        runtimes = STT_ENGINE_RUNTIME_CHOICES.get(engine_id, ("auto",))
        devices = STT_ENGINE_DEVICE_CHOICES.get(engine_id, ("cpu", "cuda"))
        self.stt_model_combo["values"] = models
        self.stt_runtime_combo["values"] = runtimes
        self.stt_device_combo["values"] = devices

        if engine_id == FASTER_WHISPER_ENGINE_ID:
            safe_model = canonical_french_whisper_model_name(self.model_var.get() or "medium")
            self.model_var.set(safe_model)
            self.stt_model_var.set(safe_model)
            self.stt_runtime_var.set("python")
            self.stt_device_var.set(self.device_var.get() or "cpu")
            self.stt_external_cli_var.set("")
            self.stt_server_url_var.set("")
        else:
            backend_config = backend_config_for(self.config, engine_id)
            if self.stt_model_var.get() not in models:
                self.stt_model_var.set(str(backend_config.get("model") or models[0]))
            if self.stt_runtime_var.get() not in runtimes:
                self.stt_runtime_var.set(str(backend_config.get("runtime") or runtimes[0]))
            if self.stt_device_var.get() not in devices:
                self.stt_device_var.set(str(backend_config.get("device") or devices[0]))
            self.stt_external_cli_var.set(str(backend_config.get("external_cli_command") or ""))
            self.stt_server_url_var.set(str(backend_config.get("server_url") or ""))

        warning = ""
        if engine_id == VOXTRAL_ENGINE_ID and self.stt_device_var.get().lower() == "cuda":
            warning = (
                "Attention : Voxtral peut consommer de la VRAM et perturber Gemma 31B si LM Studio utilise déjà "
                "fortement la RTX 5090."
            )
        summary = [
            f"Moteur actif : {STT_ENGINE_LABELS.get(engine_id, engine_id)}",
            f"Modèle : {self.stt_model_var.get()}",
            f"Runtime : {self.stt_runtime_var.get()}",
            f"Device : {self.stt_device_var.get()}",
            "Langue forcée : français" if engine_id == FASTER_WHISPER_ENGINE_ID else "",
            "Tâche : transcription" if engine_id == FASTER_WHISPER_ENGINE_ID else "",
            "Détection automatique de langue : désactivée" if engine_id == FASTER_WHISPER_ENGINE_ID else "",
            (
                "Voxtral : serveur local OpenAI-compatible accepté sur /v1/audio/transcriptions "
                "si le champ Serveur local est renseigné."
            ) if engine_id == VOXTRAL_ENGINE_ID else "",
            (
                "Qwen3-ASR : configure une commande externe locale qui écrit un JSON de transcription."
            ) if engine_id == QWEN3_ASR_ENGINE_ID else "",
            (
                "Local uniquement par défaut. Aucun service cloud n'est appelé par l'application."
            ) if engine_id != FASTER_WHISPER_ENGINE_ID else "",
            warning,
        ]
        self.set_text(self.stt_info_text, "\n".join(line for line in summary if line), readonly=True)
        self.stt_status_var.set(f"STT: {STT_ENGINE_LABELS.get(engine_id, engine_id)}")

    def on_stt_engine_changed(self) -> None:
        self.refresh_stt_engine_controls()
        self.save_stt_settings()

    def save_stt_settings(self) -> None:
        if not hasattr(self, "stt_engine_var"):
            return
        engine_id = self.selected_stt_engine_id()
        self.capture_stt_runtime_settings()
        try:
            save_json(BASE_DIR / "config.json", self.config)
            self.refresh_stt_engine_controls()
        except Exception as exc:
            self.log_debug("error", "stt", "stt_settings_save_error", str(exc), {"engine": engine_id})

    def get_stt_settings(self) -> dict:
        engine_id = self.selected_stt_engine_id() if hasattr(self, "stt_engine_var") else FASTER_WHISPER_ENGINE_ID
        config = {
            **self.config,
            "stt": dict(self.config.get("stt", {})),
            "whisper": dict(self.config.get("whisper", {})),
            "faster_whisper": dict(self.config.get("faster_whisper", {})),
            "audio_filter": dict(self.config.get("audio_filter", {})),
            "transcription_cleaning": dict(self.config.get("transcription_cleaning", {})),
            "qwen3_asr": dict(self.config.get("qwen3_asr", {})),
            "voxtral": dict(self.config.get("voxtral", {})),
            "engine": engine_id,
            "default_engine": engine_id,
        }
        config["stt"].update(
            {
                "default_engine": engine_id,
                "allow_experimental_engines": bool(self.stt_allow_experimental_var.get()),
                "keep_audio_for_benchmark": bool(self.stt_keep_audio_var.get()),
                "auto_fallback_to_faster_whisper": bool(self.stt_auto_fallback_var.get()),
                "show_engine_warnings": bool(self.stt_show_warnings_var.get()),
                "benchmark_engines": self.get_stt_benchmark_engine_settings(),
                "stt_context_bias": self.get_text(self.stt_context_bias_text).strip()
                if hasattr(self, "stt_context_bias_text")
                else self.config.get("stt", {}).get("stt_context_bias", ""),
                "speaker_map": self.get_stt_speaker_map(),
            }
        )
        config["allow_experimental_engines"] = config["stt"]["allow_experimental_engines"]
        config["auto_fallback_to_faster_whisper"] = config["stt"]["auto_fallback_to_faster_whisper"]
        config["show_engine_warnings"] = config["stt"]["show_engine_warnings"]
        config["stt_context_bias"] = config["stt"]["stt_context_bias"]

        faster = config["faster_whisper"]
        faster.update(
            {
                "enabled": True,
                "model": canonical_french_whisper_model_name(self.model_var.get()),
                "device": self.device_var.get(),
                "compute_type": self.compute_var.get(),
                "input_device": self.selected_input_device(),
                "language": "fr",
                "task": "transcribe",
                "force_language": True,
                "disable_language_detection": True,
                "condition_on_previous_text": False,
                "initial_prompt": self.get_active_whisper_initial_prompt_text() or DEFAULT_WHISPER_INITIAL_PROMPT,
            }
        )
        medical_config = dict(self.config.get("medical_transcription", {}))
        weda_context = self.get_text(self.context_text) if hasattr(self, "context_text") else ""
        include_weda_prompt = bool(
            self.whisper_include_weda_context_var.get()
            if hasattr(self, "whisper_include_weda_context_var")
            else medical_config.get("include_weda_context_in_whisper_prompt", True)
        )
        use_dynamic_hotwords = bool(
            self.whisper_use_dynamic_hotwords_var.get()
            if hasattr(self, "whisper_use_dynamic_hotwords_var")
            else medical_config.get("use_dynamic_weda_hotwords", True)
        )
        final_prompt, dynamic_context = build_dynamic_whisper_prompt(
            faster["initial_prompt"],
            weda_context,
            include_weda_context=include_weda_prompt,
            max_dynamic_characters=int(
                medical_config.get("max_dynamic_prompt_characters", MAX_DYNAMIC_PROMPT_CHARACTERS)
            ),
        )
        permanent_hotwords = (
            self.get_text(self.permanent_hotwords_text)
            if hasattr(self, "permanent_hotwords_text")
            else medical_config.get("permanent_hotwords", DEFAULT_PERMANENT_MEDICAL_HOTWORDS)
        )
        correction_hotwords = self.correction_store.hotwords() if hasattr(self, "correction_store") else []
        hotword_bundle = build_hotword_bundle(
            permanent_hotwords,
            weda_context,
            correction_hotwords,
            include_weda=use_dynamic_hotwords,
            max_hotwords=int(medical_config.get("max_hotwords", MAX_HOTWORDS)),
            max_hotword_length=int(medical_config.get("max_hotword_length", MAX_HOTWORD_LENGTH)),
            max_characters=int(medical_config.get("max_hotwords_characters", MAX_HOTWORDS_CHARACTERS)),
        )
        faster["initial_prompt"] = final_prompt
        faster["hotwords"] = hotword_bundle.faster_whisper_value
        faster["hotwords_count"] = len(hotword_bundle.final)
        config["medical_whisper_diagnostics"] = {
            "base_prompt": self.get_active_whisper_initial_prompt_text() or DEFAULT_WHISPER_INITIAL_PROMPT,
            "dynamic_context": dynamic_context,
            "final_prompt": final_prompt,
            "permanent_hotwords_count": len(hotword_bundle.permanent),
            "weda_hotwords_count": len(hotword_bundle.weda),
            "correction_hotwords_count": len(hotword_bundle.corrections),
            "final_hotwords": list(hotword_bundle.final),
        }
        self.last_whisper_diagnostics = dict(config["medical_whisper_diagnostics"])
        legacy = config["whisper"]
        legacy.update(
            {
                "default_model": faster["model"],
                "device": faster["device"],
                "compute_type": faster["compute_type"],
                "input_device": faster["input_device"],
                "language": "fr",
                "task": "transcribe",
                "force_language": True,
                "disable_language_detection": True,
                "condition_on_previous_text": False,
                "initial_prompt": faster["initial_prompt"],
            }
        )

        if engine_id != FASTER_WHISPER_ENGINE_ID:
            target = config[engine_id]
            target.update(
                {
                    "enabled": True,
                    "model": self.stt_model_var.get(),
                    "runtime": self.stt_runtime_var.get(),
                    "device": self.stt_device_var.get(),
                    "external_cli_command": self.stt_external_cli_var.get().strip(),
                }
            )
            if engine_id == VOXTRAL_ENGINE_ID:
                target["server_url"] = self.stt_server_url_var.get().strip() or "http://127.0.0.1:8000"

        auto_delete_audio = bool(self.config.get("security", {}).get("auto_delete_audio", True))
        if bool(config["stt"].get("keep_audio_for_benchmark", False)):
            auto_delete_audio = False
        return {
            **config,
            "segment_seconds": faster.get(
                "segment_seconds", legacy.get("segment_seconds", TRANSCRIPTION_WINDOW_SECONDS)
            ),
            "overlap_seconds": faster.get(
                "overlap_seconds", legacy.get("overlap_seconds", TRANSCRIPTION_OVERLAP_SECONDS)
            ),
            "sample_rate": legacy.get("sample_rate", 16000),
            "input_device": self.selected_input_device(),
            "auto_delete_audio": auto_delete_audio,
        }

    def load_active_stt_engine(self) -> None:
        self.save_stt_settings()
        settings = self.get_stt_settings()
        engine_id = self.selected_stt_engine_id()
        self.stt_status_var.set(f"STT: chargement {STT_ENGINE_LABELS.get(engine_id, engine_id)}")

        def worker():
            try:
                health = self.stt_engine_manager.load(settings)
                self.root.after(0, self.on_stt_health_result, health, "chargé")
            except Exception as exc:
                self.root.after(0, self.on_stt_action_error, exc, "chargement")

        threading.Thread(target=worker, name="stt-load", daemon=True).start()

    def unload_active_stt_engine(self) -> None:
        engine_id = self.selected_stt_engine_id()
        try:
            health = self.stt_engine_manager.unload(engine_id)
            self.on_stt_health_result(health, "déchargé")
        except Exception as exc:
            self.on_stt_action_error(exc, "déchargement")

    def test_active_stt_engine(self) -> None:
        self.save_stt_settings()
        settings = self.get_stt_settings()
        engine_id = self.selected_stt_engine_id()
        self.stt_status_var.set(f"STT: test {STT_ENGINE_LABELS.get(engine_id, engine_id)}")

        def worker():
            try:
                health = self.stt_engine_manager.health_check(settings, engine_id)
                self.root.after(0, self.on_stt_health_result, health, "testé")
            except Exception as exc:
                self.root.after(0, self.on_stt_action_error, exc, "test")

        threading.Thread(target=worker, name="stt-health-check", daemon=True).start()

    def on_stt_health_result(self, health: dict, action: str) -> None:
        engine = str(health.get("name") or health.get("engine") or "STT")
        ok = bool(health.get("ok", False))
        warnings = health.get("warnings") or []
        errors = health.get("errors") or []
        status = str(health.get("status") or "")
        lines = [
            f"{engine} {action}.",
            f"Statut : {'OK' if ok else 'à configurer'} {status}".strip(),
        ]
        if warnings:
            lines.append("Warnings : " + " ; ".join(map(str, warnings)))
        if errors:
            lines.append("Erreurs : " + " ; ".join(map(str, errors)))
        if health.get("help"):
            lines.append("Aide : " + str(health.get("help")))
        self.set_text(self.stt_info_text, "\n".join(lines), readonly=True)
        self.stt_status_var.set(f"STT: {engine} {'OK' if ok else 'à configurer'}")
        self.log_debug("info" if ok else "warning", "stt", "stt_health", "\n".join(lines), health)

    def on_stt_action_error(self, error: Exception, action: str) -> None:
        message = f"Erreur STT ({action}) : {error}"
        self.stt_status_var.set("STT: erreur")
        self.set_text(self.stt_info_text, message, readonly=True)
        self.log_debug("error", "stt", "stt_action_error", message, {"action": action})
        messagebox.showerror("Moteur de transcription", message, parent=self.root)

    def selected_stt_compare_engine_ids(self) -> list[str]:
        engines = []
        if self.stt_compare_faster_var.get():
            engines.append(FASTER_WHISPER_ENGINE_ID)
        if self.stt_compare_qwen_var.get():
            engines.append(QWEN3_ASR_ENGINE_ID)
        if self.stt_compare_voxtral_var.get():
            engines.append(VOXTRAL_ENGINE_ID)
        return engines or [self.selected_stt_engine_id()]

    def compare_stt_engines(self) -> None:
        audio_path = self.last_stt_audio_path
        if not audio_path or not Path(audio_path).exists():
            messagebox.showwarning(
                "Benchmark STT",
                "Aucun fichier audio de dictée disponible. Active 'Garder audio benchmark', puis refais une dictée.",
                parent=self.root,
            )
            return
        self.save_stt_settings()
        settings = self.get_stt_settings()
        engine_ids = self.selected_stt_compare_engine_ids()
        self.stt_status_var.set("STT: benchmark en cours")
        self.set_text(self.stt_info_text, f"Comparaison sur {Path(audio_path).name}...", readonly=True)

        def worker():
            results = self.stt_engine_manager.compare_file(audio_path, engine_ids, settings)
            self.root.after(0, self.on_stt_compare_results, results)

        threading.Thread(target=worker, name="stt-compare", daemon=True).start()

    def on_stt_compare_results(self, results: list[dict]) -> None:
        self.stt_benchmark_results = list(results or [])
        self.render_stt_benchmark_results()
        self.stt_status_var.set(f"STT: benchmark {len(self.stt_benchmark_results)} moteur(s)")
        self.log_debug(
            "info",
            "stt",
            "stt_benchmark_done",
            "Benchmark STT terminé.",
            {"engines": [result.get("engine") for result in self.stt_benchmark_results]},
        )

    def render_stt_benchmark_results(self) -> None:
        if not hasattr(self, "stt_benchmark_tree"):
            return
        self.stt_benchmark_tree.delete(*self.stt_benchmark_tree.get_children())
        for index, result in enumerate(self.stt_benchmark_results):
            engine = str(result.get("engine") or "")
            errors = result.get("errors") or []
            speakers = result.get("speakers") or []
            text = format_stt_text(result, self.get_stt_speaker_map())
            self.stt_benchmark_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    STT_ENGINE_LABELS.get(engine, engine),
                    str(result.get("model") or ""),
                    " ".join(part for part in (str(result.get("device") or ""), str(result.get("runtime") or "")) if part),
                    f"{float(result.get('processing_seconds') or 0.0):.1f}s",
                    "oui" if speakers else "non",
                    str(len(errors)),
                    text[:1000],
                ),
            )

    def use_selected_stt_benchmark_result(self) -> None:
        if not hasattr(self, "stt_benchmark_tree"):
            return
        selection = self.stt_benchmark_tree.selection()
        if not selection:
            messagebox.showinfo("Benchmark STT", "Sélectionne une ligne de benchmark.", parent=self.root)
            return
        try:
            result = self.stt_benchmark_results[int(selection[0])]
        except Exception:
            return
        text = clean_transcription_text(format_stt_text(result, self.get_stt_speaker_map()), self.config.get("transcription_cleaning", {}))
        if not text:
            messagebox.showwarning("Benchmark STT", "Ce résultat ne contient pas de transcription utilisable.", parent=self.root)
            return
        self.set_text(self.transcription_text, text)
        if hasattr(self, "corrected_transcription_text"):
            self.set_text(self.corrected_transcription_text, text)
        self.last_stt_result = result
        self.transcription_status_var.set("Transcription remplacée par le benchmark STT")
        self.model_status_var.set(f"Moteur STT: {STT_ENGINE_LABELS.get(result.get('engine'), result.get('engine'))}")
        self.schedule_message_refresh()
        self.log_debug("info", "stt", "stt_benchmark_result_used", "Résultat benchmark utilisé comme transcription principale.", {
            "engine": result.get("engine"),
            "model": result.get("model"),
            "text_length": len(text),
        })

    def current_stt_history_payload(self) -> dict:
        result = self.last_stt_result or {}
        return {
            "stt_engine": result.get("engine", ""),
            "stt_model": result.get("model", ""),
            "stt_runtime": result.get("runtime", ""),
            "stt_device": result.get("device", ""),
            "stt_mode": result.get("mode", ""),
            "stt_output_raw": result.get("raw", {}),
            "stt_output_normalized": result,
            "stt_segments": result.get("segments", []),
            "stt_speakers": result.get("speakers", []),
            "stt_word_timestamps": result.get("word_timestamps", []),
            "stt_processing_seconds": result.get("processing_seconds", 0.0),
            "stt_audio_duration_seconds": result.get("duration_seconds", 0.0),
            "stt_warnings": result.get("warnings", []),
            "stt_errors": result.get("errors", []),
        }

    def get_stt_speaker_map(self) -> dict[str, str]:
        if hasattr(self, "stt_speaker_map_text"):
            return self.parse_stt_speaker_map(self.get_text(self.stt_speaker_map_text))
        value = self.config.get("stt", {}).get("speaker_map", {})
        return value if isinstance(value, dict) else {}

    def parse_stt_speaker_map(self, text: str) -> dict[str, str]:
        mapping = {}
        for line in str(text or "").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            if "=" in raw:
                left, right = raw.split("=", 1)
            elif ":" in raw:
                left, right = raw.split(":", 1)
            else:
                continue
            speaker = left.strip()
            label = right.strip()
            if speaker and label:
                mapping[speaker] = label
        return mapping

    def serialize_stt_speaker_map(self, mapping: dict | None) -> str:
        if not isinstance(mapping, dict) or not mapping:
            return "SPEAKER_00=Médecin\nSPEAKER_01=Patient"
        return "\n".join(f"{key}={value}" for key, value in mapping.items())

    def get_whisper_settings(self) -> dict:
        whisper_config = dict(self.config.get("whisper", {}))
        whisper_config.update(
            {
                "model": canonical_french_whisper_model_name(self.model_var.get()),
                "device": self.device_var.get(),
                "compute_type": self.compute_var.get(),
                "input_device": self.selected_input_device(),
                "language": "fr",
                "task": "transcribe",
                "force_language": True,
                "disable_language_detection": True,
                "condition_on_previous_text": False,
                "initial_prompt": self.get_active_whisper_initial_prompt_text(),
                "auto_delete_audio": self.config.get("security", {}).get("auto_delete_audio", True),
            }
        )
        return whisper_config

    def get_fly_whisper_settings(self) -> dict:
        settings = self.get_whisper_settings()
        fly_config = self.config.get("fly_dictation", {})
        settings["engine"] = FASTER_WHISPER_ENGINE_ID
        settings["default_engine"] = FASTER_WHISPER_ENGINE_ID
        settings["auto_fallback_to_faster_whisper"] = False

        def int_setting(key: str, default: int, minimum: int, maximum: int) -> int:
            try:
                value = int(float(fly_config.get(key, default)))
            except (TypeError, ValueError):
                value = default
            return max(minimum, min(maximum, value))

        def float_setting(key: str, default: float, minimum: float, maximum: float) -> float:
            try:
                value = float(fly_config.get(key, default))
            except (TypeError, ValueError):
                value = default
            return max(minimum, min(maximum, value))

        def bool_setting(key: str, default: bool) -> bool:
            value = fly_config.get(key, default)
            if isinstance(value, str):
                return value.strip().lower() not in {"0", "false", "faux", "no", "non", "off"}
            return bool(value)

        for key in ("model", "default_model", "device", "compute_type"):
            value = str(fly_config.get(key) or "").strip()
            if value:
                settings[key] = value
        if hasattr(self, "fly_dictation_model_var"):
            fly_model = str(self.fly_dictation_model_var.get() or "").strip()
            if fly_model:
                settings["model"] = canonical_french_whisper_model_name(fly_model)
        if hasattr(self, "fly_dictation_device_var"):
            fly_device = str(self.fly_dictation_device_var.get() or "").strip()
            if fly_device:
                settings["device"] = fly_device
        if hasattr(self, "fly_dictation_compute_var"):
            fly_compute = str(self.fly_dictation_compute_var.get() or "").strip()
            if fly_compute:
                settings["compute_type"] = fly_compute

        settings.update(
            {
                "beam_size": int_setting("beam_size", 1, 1, 5),
                "best_of": int_setting("best_of", 1, 1, 5),
                "temperature": float_setting("temperature", 0.0, 0.0, 1.0),
                "language": "fr",
                "task": "transcribe",
                "force_language": True,
                "disable_language_detection": True,
                "condition_on_previous_text": bool_setting("condition_on_previous_text", False),
                "min_silence_duration_ms": int_setting("min_silence_duration_ms", 250, 100, 2000),
                "vad_filter": bool_setting("vad_filter", False),
                "without_timestamps": bool_setting("without_timestamps", True),
                "max_new_tokens": int_setting("max_new_tokens", 128, 16, 256),
                "initial_prompt": str(
                    fly_config.get("initial_prompt", DEFAULT_FLY_WHISPER_INITIAL_PROMPT)
                    or ""
                ),
                # La volée reste une dictée courte autonome : le contexte WEDA
                # et les hotwords de la consultation principale ne doivent pas
                # consommer la fenêtre de décodage du modèle Turbo.
                "hotwords": "",
                "hotwords_count": 0,
            }
        )
        if getattr(self, "_fly_cuda_runtime_failed", False) and str(settings.get("device") or "").lower() == "cuda":
            settings["device"] = "cpu"
            settings["compute_type"] = "int8"
            settings["cuda_fallback_active"] = True
        return settings

    def micro_device_label_for_value(self, value: str) -> str:
        for label, device_value in self.micro_device_options:
            if str(device_value) == str(value):
                return label
        return self.micro_device_options[0][0] if self.micro_device_options else "Micro par défaut"

    def selected_input_device(self) -> str:
        return self.micro_device_values.get(self.micro_device_var.get(), "")

    def save_micro_device(self) -> None:
        value = self.selected_input_device()
        self.capture_whisper_runtime_settings()
        try:
            save_json(BASE_DIR / "config.json", self.config)
            self.log_debug(
                "info",
                "app",
                "micro_device_saved",
                "Micro de dictée enregistré.",
                {"input_device": value, "label": self.micro_device_var.get()},
            )
        except Exception as exc:
            self.log_debug("error", "app", "micro_device_save_error", str(exc), {"input_device": value})

    def connector_key_choices(self) -> tuple[str, ...]:
        return (
            "PageUp",
            "PageDown",
            "F6",
            "F7",
            "F8",
            "F9",
            "F10",
            "F11",
            "F12",
            "Insert",
            "Home",
            "End",
        )

    def fly_dictation_key_choices(self) -> tuple[str, ...]:
        return (
            "²",
            "F6",
            "F7",
            "F8",
            "F9",
            "F10",
            "F11",
            "F12",
            "Insert",
            "Pause",
            "ScrollLock",
            "PageUp",
            "PageDown",
            "Home",
            "End",
        )

    def normalize_fly_dictation_key(self, value: str) -> str:
        text = str(value or "").strip()
        compact = text.lower().replace(" ", "")
        aliases = {
            "2": "²",
            "square": "²",
            "carre": "²",
            "carré": "²",
            "pageup": "PageUp",
            "pagedown": "PageDown",
            "prior": "PageUp",
            "next": "PageDown",
            "insert": "Insert",
            "ins": "Insert",
            "pause": "Pause",
            "scrolllock": "ScrollLock",
            "scroll_lock": "ScrollLock",
            "home": "Home",
            "end": "End",
            "debut": "Home",
            "début": "Home",
            "fin": "End",
        }
        if compact in aliases:
            return aliases[compact]
        f_key = compact.upper()
        if re.fullmatch(r"F(?:[1-9]|1[0-2])", f_key):
            return f_key
        return text or "²"

    def fly_dictation_keyboard_key_name(self, value: str) -> str:
        key = self.normalize_fly_dictation_key(value)
        aliases = {
            "PageUp": "page up",
            "PageDown": "page down",
            "ScrollLock": "scroll lock",
        }
        if key in aliases:
            return aliases[key]
        if re.fullmatch(r"F(?:[1-9]|1[0-2])", key):
            return key.lower()
        return key.lower() if len(key) > 1 else key

    def fly_dictation_keyboard_key_candidates(self, value: str) -> list[str | int]:
        key = self.normalize_fly_dictation_key(value)
        candidates: list[str | int] = []
        if key == "²":
            candidates.append(41)
        candidates.append(self.fly_dictation_keyboard_key_name(key))
        return candidates

    def get_fly_dictation_settings(self) -> dict:
        fly_config = self.config.get("fly_dictation", {})
        try:
            min_seconds = float(fly_config.get("min_seconds", 0.2))
        except (TypeError, ValueError):
            min_seconds = 0.2
        try:
            paste_delay_ms = int(float(fly_config.get("paste_delay_ms", 0)))
        except (TypeError, ValueError):
            paste_delay_ms = 0
        enabled = bool(self.fly_dictation_enabled_var.get()) if hasattr(self, "fly_dictation_enabled_var") else bool(
            fly_config.get("enabled", True)
        )
        key = self.normalize_fly_dictation_key(
            self.fly_dictation_key_var.get() if hasattr(self, "fly_dictation_key_var") else fly_config.get("key", "²")
        )
        model = canonical_french_whisper_model_name(
            str(
                self.fly_dictation_model_var.get()
                if hasattr(self, "fly_dictation_model_var")
                else fly_config.get("model") or fly_config.get("default_model") or self.config.get("whisper", {}).get("default_model")
            ).strip() or "medium"
        )
        device = str(
            self.fly_dictation_device_var.get()
            if hasattr(self, "fly_dictation_device_var")
            else fly_config.get("device") or self.config.get("whisper", {}).get("device")
        ).strip() or "cpu"
        if device not in WHISPER_DEVICE_CHOICES:
            device = "cpu"
        compute_type = str(
            self.fly_dictation_compute_var.get()
            if hasattr(self, "fly_dictation_compute_var")
            else fly_config.get("compute_type") or self.config.get("whisper", {}).get("compute_type")
        ).strip() or "int8"
        if compute_type not in WHISPER_COMPUTE_CHOICES:
            compute_type = "int8"
        return {
            "enabled": enabled,
            "key": key,
            "model": model,
            "device": device,
            "compute_type": compute_type,
            "min_seconds": max(0.05, min(5.0, min_seconds)),
            "paste_delay_ms": max(0, min(1000, paste_delay_ms)),
        }

    def save_fly_dictation_settings(self) -> None:
        self._fly_cuda_runtime_failed = False
        settings = self.get_fly_dictation_settings()
        self.fly_dictation_key_var.set(settings["key"])
        self.fly_dictation_model_var.set(settings["model"])
        self.fly_dictation_device_var.set(settings["device"])
        self.fly_dictation_compute_var.set(settings["compute_type"])
        fly_config = self.config.setdefault("fly_dictation", {})
        fly_config["enabled"] = settings["enabled"]
        fly_config["key"] = settings["key"]
        fly_config["model"] = settings["model"]
        fly_config["device"] = settings["device"]
        fly_config["compute_type"] = settings["compute_type"]
        fly_config.setdefault("min_seconds", settings["min_seconds"])
        fly_config.setdefault("paste_delay_ms", settings["paste_delay_ms"])
        fly_config.setdefault("beam_size", 1)
        fly_config.setdefault("best_of", 1)
        fly_config.setdefault("temperature", 0.0)
        fly_config.setdefault("condition_on_previous_text", False)
        fly_config.setdefault("vad_filter", False)
        fly_config.setdefault("without_timestamps", True)
        fly_config.setdefault("max_new_tokens", 128)
        fly_config.setdefault("min_silence_duration_ms", 250)
        fly_config.setdefault("initial_prompt", DEFAULT_FLY_WHISPER_INITIAL_PROMPT)
        fly_config.setdefault("preload_model", True)
        try:
            save_json(BASE_DIR / "config.json", self.config)
            self.log_debug(
                "info",
                "app",
                "fly_dictation_settings_saved",
                "Réglages de dictée à la volée enregistrés.",
                settings,
            )
        except Exception as exc:
            self.log_debug("error", "app", "fly_dictation_settings_save_error", str(exc), settings)
        self.install_fly_dictation_hotkey()
        self.preload_fly_dictation_model()

    def preload_fly_dictation_model(self) -> None:
        settings = self.get_fly_dictation_settings()
        fly_config = self.config.get("fly_dictation", {})
        preload_value = fly_config.get("preload_model", True)
        if isinstance(preload_value, str):
            preload_enabled = preload_value.strip().lower() not in {"0", "false", "faux", "no", "non", "off"}
        else:
            preload_enabled = bool(preload_value)
        if not settings["enabled"] or not preload_enabled:
            return

        try:
            whisper_settings = WhisperSettings.from_mapping(self.get_fly_whisper_settings())
        except Exception as exc:
            self.log_debug("warning", "app", "fly_dictation_preload_settings_error", str(exc), settings)
            return

        def worker() -> None:
            try:
                model = self.model_manager.load(whisper_settings)
                if whisper_settings.device == "cuda":
                    try:
                        self.validate_fly_cuda_runtime(model)
                    except Exception as cuda_exc:
                        self._fly_cuda_runtime_failed = True
                        fallback_settings = WhisperSettings.from_mapping(
                            self.fly_dictation_cpu_fallback_settings(self.get_fly_whisper_settings())
                        )
                        try:
                            self.model_manager.unload_all()
                            self.model_manager.load(fallback_settings)
                        except Exception as fallback_exc:
                            self.log_debug(
                                "error",
                                "app",
                                "fly_dictation_cuda_cpu_fallback_preload_error",
                                str(fallback_exc),
                                {"cuda_error": str(cuda_exc)},
                            )
                            raise cuda_exc
                        self.log_debug(
                            "warning",
                            "app",
                            "fly_dictation_cuda_runtime_unavailable",
                            "CUDA indisponible pour la volée, fallback CPU activé.",
                            {
                                "error": str(cuda_exc),
                                "requested_model": whisper_settings.model_name,
                                "requested_device": whisper_settings.device,
                                "requested_compute_type": whisper_settings.compute_type,
                                "fallback_device": fallback_settings.device,
                                "fallback_compute_type": fallback_settings.compute_type,
                            },
                        )
                        self.root.after(
                            0,
                            lambda: self.fly_dictation_status_var.set("Volée: CUDA indisponible, fallback CPU"),
                        )
                        self.root.after(0, lambda: self.model_status_var.set(f"Moteur STT: {self.model_manager.active_label()}"))
                        return
                self.log_debug(
                    "info",
                    "app",
                    "fly_dictation_model_preloaded",
                    "Modèle faster-whisper de dictée à la volée préchargé.",
                    {"model": whisper_settings.model_name, "device": whisper_settings.device, "compute_type": whisper_settings.compute_type},
                )
                self.root.after(0, lambda: self.model_status_var.set(f"Moteur STT: {self.model_manager.active_label()}"))
            except Exception as exc:
                self.log_debug(
                    "warning",
                    "app",
                    "fly_dictation_model_preload_error",
                    str(exc),
                    {"model": whisper_settings.model_name, "device": whisper_settings.device, "compute_type": whisper_settings.compute_type},
                )

        threading.Thread(target=worker, name="fly-dictation-model-preload", daemon=True).start()

    def validate_fly_cuda_runtime(self, model) -> None:
        try:
            import numpy as np
        except ImportError:
            return

        audio = np.zeros(1600, dtype="float32")
        segments, _info = model.transcribe(
            audio,
            language="fr",
            task="transcribe",
            beam_size=1,
            best_of=1,
            vad_filter=False,
            condition_on_previous_text=False,
            initial_prompt="Test technique de disponibilité CUDA.",
            temperature=0.0,
            without_timestamps=True,
        )
        list(segments)

    def fly_dictation_cpu_fallback_settings(self, whisper_settings: dict) -> dict:
        fallback = dict(whisper_settings or {})
        fallback["device"] = "cpu"
        fallback["compute_type"] = "int8"
        fallback["cuda_fallback_active"] = True
        return fallback

    def uninstall_fly_dictation_hotkey(self) -> None:
        keyboard_module = self._fly_keyboard
        for handle in list(self._fly_dictation_hook_handles):
            try:
                if keyboard_module:
                    keyboard_module.unhook(handle)
            except Exception:
                pass
        self._fly_dictation_hook_handles = []

    def install_fly_dictation_hotkey(self) -> None:
        self.uninstall_fly_dictation_hotkey()
        settings = self.get_fly_dictation_settings()
        if not settings["enabled"]:
            self.fly_dictation_status_var.set("Volée: inactive")
            return

        try:
            import keyboard
        except ImportError as exc:
            self.fly_dictation_status_var.set("Volée: module keyboard manquant")
            self.log_debug(
                "warning",
                "app",
                "fly_dictation_keyboard_missing",
                "Le raccourci global de dictée à la volée nécessite le module keyboard.",
                {"error": str(exc)},
            )
            return
        except Exception as exc:
            self.fly_dictation_status_var.set("Volée: raccourci global indisponible")
            self.log_debug("warning", "app", "fly_dictation_keyboard_import_error", str(exc))
            return

        installed_key_name = None
        installed_key_names = []
        hook_handles = []
        last_error = None
        try:
            for key_name in self.fly_dictation_keyboard_key_candidates(settings["key"]):
                press_handle = None
                release_handle = None
                try:
                    press_handle = keyboard.on_press_key(
                        key_name,
                        lambda _event: self.on_fly_dictation_key_pressed(),
                        suppress=True,
                    )
                    release_handle = keyboard.on_release_key(
                        key_name,
                        lambda _event: self.on_fly_dictation_key_released(),
                        suppress=True,
                    )
                    installed_key_name = key_name
                    installed_key_names.append(key_name)
                    hook_handles.extend([press_handle, release_handle])
                except Exception as exc:
                    last_error = exc
                    for handle in (press_handle, release_handle):
                        if handle is None:
                            continue
                        try:
                            keyboard.unhook(handle)
                        except Exception:
                            pass
                    continue
            if not hook_handles:
                raise last_error or RuntimeError("Raccourci global non reconnu.")
            self._fly_keyboard = keyboard
            self._fly_dictation_hook_handles = hook_handles
            self.fly_dictation_status_var.set(f"Volée: maintenir {settings['key']}")
            self.log_debug(
                "info",
                "app",
                "fly_dictation_hotkey_installed",
                "Raccourci global de dictée à la volée installé.",
                {"key": settings["key"], "keyboard_key": installed_key_name, "keyboard_keys": installed_key_names},
            )
        except Exception as exc:
            self.fly_dictation_status_var.set("Volée: raccourci non installé")
            self.log_debug(
                "error",
                "app",
                "fly_dictation_hotkey_install_error",
                str(exc),
                {"key": settings["key"], "keyboard_candidates": self.fly_dictation_keyboard_key_candidates(settings["key"])},
            )

    def get_fly_dictation_state(self) -> dict:
        settings = self.get_fly_dictation_settings()
        if self._fly_recording:
            status = "recording"
        elif self._fly_busy:
            status = "transcribing"
        else:
            status = "idle"
        return {
            "enabled": bool(settings["enabled"]),
            "key": settings["key"],
            "model": settings["model"],
            "status": status,
            "recording": bool(self._fly_recording),
            "busy": bool(self._fly_busy),
            "key_down": bool(self._fly_dictation_key_down),
        }

    def fly_dictation_start(self, payload: dict | None = None) -> dict:
        payload = payload or {}

        def ui_start() -> dict:
            settings = self.get_fly_dictation_settings()
            if not settings["enabled"]:
                self.fly_dictation_status_var.set("Volée: inactive")
                return {
                    **self.get_fly_dictation_state(),
                    "status": "disabled",
                    "message": "Dictée à la volée inactive.",
                }

            with self._fly_dictation_lock:
                already_down = self._fly_dictation_key_down
                self._fly_dictation_key_down = True

            if not already_down:
                self.start_fly_dictation_recording()
            return self.get_fly_dictation_state()

        try:
            state = self.call_ui_sync(ui_start)
            self.log_debug("info", "app", "fly_dictation_start_http", "Démarrage dictée à la volée reçu.", {
                "trigger": str(payload.get("trigger") or ""),
                "source": str(payload.get("source") or ""),
                **state,
            })
            return state
        except Exception as exc:
            self.log_debug("error", "app", "fly_dictation_start_http_error", str(exc), payload)
            return {"status": "error", "message": str(exc), "error": str(exc)}

    def fly_dictation_stop(self, payload: dict | None = None) -> dict:
        payload = payload or {}

        def ui_stop() -> dict:
            with self._fly_dictation_lock:
                was_down = self._fly_dictation_key_down
                self._fly_dictation_key_down = False

            if was_down or self._fly_recording:
                self.stop_fly_dictation_recording()
            return self.get_fly_dictation_state()

        try:
            state = self.call_ui_sync(ui_stop)
            self.log_debug("info", "app", "fly_dictation_stop_http", "Arrêt dictée à la volée reçu.", {
                "trigger": str(payload.get("trigger") or ""),
                "source": str(payload.get("source") or ""),
                **state,
            })
            return state
        except Exception as exc:
            self.log_debug("error", "app", "fly_dictation_stop_http_error", str(exc), payload)
            return {"status": "error", "message": str(exc), "error": str(exc)}

    def on_fly_dictation_key_pressed(self) -> None:
        with self._fly_dictation_lock:
            if self._fly_dictation_key_down:
                return
            self._fly_dictation_key_down = True
        self.root.after(0, self.start_fly_dictation_recording)

    def on_fly_dictation_key_released(self) -> None:
        with self._fly_dictation_lock:
            if not self._fly_dictation_key_down:
                return
            self._fly_dictation_key_down = False
        self.root.after(0, self.stop_fly_dictation_recording)

    def start_fly_dictation_recording(self) -> None:
        settings = self.get_fly_dictation_settings()
        if not settings["enabled"] or self._fly_recording:
            return
        if self._fly_busy:
            self.fly_dictation_status_var.set("Volée: transcription en cours")
            return
        if self.session and self.session.is_running():
            self.fly_dictation_status_var.set("Volée: dictée longue active")
            self.log_debug(
                "warning",
                "app",
                "fly_dictation_ignored_regular_dictation_running",
                "Dictée à la volée ignorée car une dictée segmentée est déjà active.",
            )
            return

        whisper_settings = self.get_fly_whisper_settings()
        try:
            recorder = PushToTalkRecorder(
                sample_rate=int(whisper_settings.get("sample_rate") or 16000),
                channels=1,
                device=whisper_settings.get("input_device"),
            )
            recorder.start()
            self._fly_recorder = recorder
            self._fly_recording = True
            self.set_recording_indicator(True, "fly")
            self.micro_status_var.set("Micro: volée en écoute")
            self.fly_dictation_status_var.set(f"Volée: enregistrement ({settings['key']})")
            self.log_debug(
                "info",
                "app",
                "fly_dictation_recording_started",
                "Enregistrement de dictée à la volée démarré.",
                {"key": settings["key"], "sample_rate": recorder.sample_rate},
            )
        except Exception as exc:
            self._fly_recorder = None
            self._fly_recording = False
            self.set_recording_indicator(False)
            self.fly_dictation_status_var.set("Volée: erreur micro")
            self.log_debug("error", "app", "fly_dictation_recording_start_error", str(exc))
            messagebox.showerror("Dictée à la volée", str(exc), parent=self.root)

    def stop_fly_dictation_recording(self) -> None:
        if not self._fly_recording or not self._fly_recorder:
            return

        recorder = self._fly_recorder
        duration_seconds = recorder.duration_seconds()
        self._fly_recorder = None
        self._fly_recording = False
        self._fly_busy = True
        self.set_recording_indicator(False)
        self.micro_status_var.set("Micro: volée arrêtée")
        settings = self.get_fly_dictation_settings()
        self.fly_dictation_status_var.set("Volée: transcription faster-whisper")

        try:
            audio = recorder.stop()
        except Exception as exc:
            self._fly_busy = False
            self.set_recording_indicator(False)
            self.fly_dictation_status_var.set("Volée: erreur arrêt")
            self.log_debug("error", "app", "fly_dictation_recording_stop_error", str(exc))
            messagebox.showerror("Dictée à la volée", str(exc), parent=self.root)
            return

        if duration_seconds < settings["min_seconds"] or len(audio) == 0:
            self._fly_busy = False
            self.fly_dictation_status_var.set("Volée: appui trop court")
            self.log_debug(
                "info",
                "app",
                "fly_dictation_too_short",
                "Appui de dictée à la volée trop court.",
                {"duration_seconds": round(duration_seconds, 3), "min_seconds": settings["min_seconds"]},
            )
            return

        fly_whisper_settings = self.get_fly_whisper_settings()
        threading.Thread(
            target=self.run_fly_dictation_worker,
            args=(
                audio,
                recorder.sample_rate,
                recorder.channels,
                duration_seconds,
                fly_whisper_settings,
            ),
            name="fly-dictation-transcribe",
            daemon=True,
        ).start()

    def run_fly_dictation_worker(
        self,
        audio,
        sample_rate: int,
        channels: int,
        duration_seconds: float,
        whisper_settings: dict,
    ) -> None:
        try:
            result = self.transcribe_fly_dictation_audio_buffer(
                audio,
                sample_rate=sample_rate,
                channels=channels,
                whisper_settings=whisper_settings,
                fallback_label="full",
            )
            self.root.after(0, self.on_fly_dictation_result, result, duration_seconds)
        except Exception as exc:
            self.root.after(0, self.on_fly_dictation_error, exc)

    def transcribe_fly_dictation_audio_buffer(
        self,
        audio,
        *,
        sample_rate: int,
        channels: int,
        whisper_settings: dict,
        fallback_label: str,
    ):
        temp_dir = None
        audio_path = None
        auto_delete_audio = bool(self.config.get("security", {}).get("auto_delete_audio", True))
        try:
            with self._fly_transcription_lock:
                try:
                    return self.transcriber.transcribe_audio_array(
                        audio,
                        sample_rate=sample_rate,
                        channels=channels,
                        segment_index=0,
                        settings_override=whisper_settings,
                    )
                except Exception as memory_exc:
                    if str((whisper_settings or {}).get("device") or "").lower() == "cuda" and is_cuda_runtime_error(memory_exc):
                        self._fly_cuda_runtime_failed = True
                        fallback_settings = self.fly_dictation_cpu_fallback_settings(whisper_settings)
                        self.log_debug(
                            "warning",
                            "app",
                            "fly_dictation_cuda_runtime_fallback",
                            "Erreur CUDA pendant la volée, nouvelle tentative en CPU.",
                            {
                                "error": str(memory_exc),
                                "fallback_label": fallback_label,
                                "fallback_device": fallback_settings["device"],
                                "fallback_compute_type": fallback_settings["compute_type"],
                            },
                        )
                        self.root.after(
                            0,
                            lambda: self.fly_dictation_status_var.set("Volée: CUDA indisponible, fallback CPU"),
                        )
                        return self.transcriber.transcribe_audio_array(
                            audio,
                            sample_rate=sample_rate,
                            channels=channels,
                            segment_index=0,
                            settings_override=fallback_settings,
                        )
                    self.log_debug(
                        "warning",
                        "app",
                        "fly_dictation_memory_transcribe_fallback",
                        "Transcription directe depuis la mémoire impossible, fallback WAV.",
                        {
                            "error": str(memory_exc),
                            "sample_rate": sample_rate,
                            "channels": channels,
                            "fallback_label": fallback_label,
                        },
                    )
                    temp_dir = Path(tempfile.mkdtemp(prefix="gemma_weda_fly_"))
                    audio_path = temp_dir / "dictee_volee.wav"
                    AudioRecorder(sample_rate=sample_rate, channels=channels).write_wav(audio_path, audio)
                    return self.transcriber.transcribe_file(
                        audio_path,
                        segment_index=0,
                        settings_override=whisper_settings,
                    )
        finally:
            if auto_delete_audio and audio_path and temp_dir:
                try:
                    audio_path.unlink(missing_ok=True)
                    temp_dir.rmdir()
                except Exception:
                    pass

    def on_fly_dictation_result(self, result, duration_seconds: float) -> None:
        self._fly_busy = False
        self.model_status_var.set(f"Moteur STT: {result.model_label}")

        if not result.text:
            self.fly_dictation_status_var.set(f"Volée: aucun texte ({self.empty_segment_short_reason(result)})")
            self.log_debug(
                "warning",
                "app",
                "fly_dictation_empty",
                "Dictée à la volée transcrite sans texte.",
                {
                    "duration_seconds": round(duration_seconds, 3),
                    "elapsed_seconds": result.elapsed_seconds,
                    "segments_count": getattr(result, "segments_count", 0),
                    "empty_reason": getattr(result, "empty_reason", ""),
                    "audio_stats": getattr(result, "audio_stats", {}),
                },
            )
            return

        self.log_debug(
            "info",
            "app",
            "fly_dictation_transcribed",
            "Dictée à la volée transcrite.",
            {
                "duration_seconds": round(duration_seconds, 3),
                "elapsed_seconds": result.elapsed_seconds,
                "text_length": len(result.text or ""),
                "segments_count": getattr(result, "segments_count", 0),
            },
        )
        self.copy_and_paste_fly_dictation_text(result.text)

    def copy_and_paste_fly_dictation_text(self, text: str) -> None:
        value = clean_transcription_text(str(text or "").strip(), self.config.get("transcription_cleaning", {}))
        if not value:
            self.fly_dictation_status_var.set("Volée: texte vide")
            return

        clipboard_snapshot_available, previous_clipboard_text = read_text_from_clipboard(self.root)
        copied = copy_text_to_clipboard(value, self.root)
        if not copied:
            self.fly_dictation_status_var.set("Volée: copie impossible")
            self.log_debug("error", "app", "fly_dictation_clipboard_error", "Impossible de copier la dictée à la volée.")
            return

        delay_ms = int(self.get_fly_dictation_settings().get("paste_delay_ms", 0))
        self.fly_dictation_status_var.set("Volée: collage en cours")
        self.root.after(
            delay_ms,
            lambda: self.send_fly_dictation_paste(
                value,
                clipboard_snapshot_available=clipboard_snapshot_available,
                previous_clipboard_text=previous_clipboard_text,
            ),
        )

    def send_fly_dictation_paste(
        self,
        text: str,
        *,
        clipboard_snapshot_available: bool = False,
        previous_clipboard_text: str = "",
    ) -> None:
        current_readable, current_clipboard_text = read_text_from_clipboard(self.root)
        if current_readable and current_clipboard_text != text:
            self.fly_dictation_status_var.set("Volée: collage annulé (presse-papier modifié)")
            self.log_debug(
                "warning",
                "app",
                "fly_dictation_paste_cancelled_clipboard_changed",
                "Collage à la volée annulé car le presse-papier a changé avant Ctrl+V.",
                {
                    "text_length": len(text or ""),
                    "clipboard_length": len(current_clipboard_text or ""),
                    "had_snapshot": clipboard_snapshot_available,
                },
            )
            return

        try:
            keyboard_module = self._fly_keyboard
            if keyboard_module is None:
                import keyboard as keyboard_module
            keyboard_module.send("ctrl+v")
            self.fly_dictation_status_var.set(f"Volée: texte collé ({len(text.split())} mot(s))")
            self.root.after(
                FLY_DICTATION_CLIPBOARD_RESTORE_DELAY_MS,
                lambda: self.restore_fly_dictation_clipboard(
                    text,
                    clipboard_snapshot_available=clipboard_snapshot_available,
                    previous_clipboard_text=previous_clipboard_text,
                ),
            )
            self.log_debug(
                "info",
                "app",
                "fly_dictation_pasted",
                "Dictée à la volée copiée puis collée dans la cible active.",
                {"text_length": len(text or ""), "had_clipboard_snapshot": clipboard_snapshot_available},
            )
        except Exception as exc:
            self.restore_fly_dictation_clipboard(
                text,
                clipboard_snapshot_available=clipboard_snapshot_available,
                previous_clipboard_text=previous_clipboard_text,
            )
            self.fly_dictation_status_var.set("Volée: collage impossible")
            self.log_debug("error", "app", "fly_dictation_paste_error", str(exc))

    def restore_fly_dictation_clipboard(
        self,
        pasted_text: str,
        *,
        clipboard_snapshot_available: bool = False,
        previous_clipboard_text: str = "",
    ) -> None:
        current_readable, current_clipboard_text = read_text_from_clipboard(self.root)
        if not current_readable:
            self.log_debug(
                "warning",
                "app",
                "fly_dictation_clipboard_restore_unreadable",
                "Restauration du presse-papier ignorée car son contenu texte est illisible.",
                {"had_snapshot": clipboard_snapshot_available},
            )
            return

        if current_clipboard_text != pasted_text:
            self.log_debug(
                "info",
                "app",
                "fly_dictation_clipboard_restore_skipped_changed",
                "Restauration du presse-papier ignorée car l'utilisateur l'a modifié après le collage.",
                {
                    "text_length": len(pasted_text or ""),
                    "clipboard_length": len(current_clipboard_text or ""),
                    "had_snapshot": clipboard_snapshot_available,
                },
            )
            return

        if clipboard_snapshot_available and previous_clipboard_text:
            restored = copy_text_to_clipboard(previous_clipboard_text, self.root)
        else:
            restored = clear_text_clipboard(self.root)

        self.log_debug(
            "info" if restored else "warning",
            "app",
            "fly_dictation_clipboard_restored" if clipboard_snapshot_available else "fly_dictation_clipboard_cleared",
            "Presse-papier restauré après collage à la volée.",
            {
                "restored": restored,
                "had_snapshot": clipboard_snapshot_available,
                "previous_text_length": len(previous_clipboard_text or ""),
            },
        )

    def on_fly_dictation_error(self, error: Exception) -> None:
        self._fly_busy = False
        self.fly_dictation_status_var.set("Volée: erreur transcription")
        self.log_debug("error", "app", "fly_dictation_error", str(error))
        messagebox.showerror("Dictée à la volée", str(error), parent=self.root)

    def save_connector_settings(self) -> None:
        start_key = self.connector_start_key_var.get() or "PageUp"
        stop_key = self.connector_stop_key_var.get() or "PageDown"
        document_now_key = self.connector_document_now_key_var.get() or "F8"
        if start_key == stop_key:
            messagebox.showwarning(
                "Connecteur WEDA",
                "La touche de déclenchement et la touche d’arrêt doivent être différentes.",
                parent=self.root,
            )
            stop_key = "PageDown" if start_key != "PageDown" else "PageUp"
            self.connector_stop_key_var.set(stop_key)
        if document_now_key in {start_key, stop_key}:
            messagebox.showwarning(
                "Connecteur WEDA",
                "La touche « Document maintenant » doit être différente des touches de démarrage et d’arrêt.",
                parent=self.root,
            )
            document_now_key = next(
                (key for key in self.connector_key_choices() if key not in {start_key, stop_key}),
                "F8",
            )
            self.connector_document_now_key_var.set(document_now_key)

        connector_config = self.config.setdefault("connector", {})
        connector_config["enabled"] = bool(self.connector_enabled_var.get())
        connector_config["start_key"] = start_key
        connector_config["stop_key"] = stop_key
        connector_config["document_now_key"] = document_now_key
        connector_config.setdefault("stop_transcription_grace_seconds", 2)
        connector_config.setdefault("auto_return_home", True)
        try:
            save_json(BASE_DIR / "config.json", self.config)
            self.log_debug(
                "info",
                "app",
                "connector_settings_saved",
                "Réglages connecteur WEDA enregistrés.",
                self.get_connector_settings(),
            )
        except Exception as exc:
            self.log_debug("error", "app", "connector_settings_save_error", str(exc), self.get_connector_settings())

    def get_connector_settings(self) -> dict:
        connector_config = self.config.get("connector", {})
        try:
            grace_seconds = float(connector_config.get("stop_transcription_grace_seconds", 2))
        except (TypeError, ValueError):
            grace_seconds = 2.0
        return {
            "enabled": bool(connector_config.get("enabled", False)),
            "start_key": str(connector_config.get("start_key") or "PageUp"),
            "stop_key": str(connector_config.get("stop_key") or "PageDown"),
            "document_now_key": str(connector_config.get("document_now_key") or "F8"),
            "stop_transcription_grace_seconds": max(0.0, min(10.0, grace_seconds)),
            "auto_return_home": bool(connector_config.get("auto_return_home", True)),
        }

    def get_context_capture_delay_seconds(self) -> int:
        weda_config = self.config.get("weda", {})
        raw = weda_config.get("context_capture_delay_seconds", 60)
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            value = 60
        return max(0, min(300, value))

    def save_context_delay(self) -> None:
        try:
            value = int(float(self.context_delay_seconds_var.get()))
        except (TypeError, ValueError):
            value = self.get_context_capture_delay_seconds()
        value = max(0, min(300, value))
        self.context_delay_seconds_var.set(str(value))
        self.config.setdefault("weda", {})["context_capture_delay_seconds"] = value
        try:
            save_json(BASE_DIR / "config.json", self.config)
            self.log_debug(
                "info",
                "app",
                "context_delay_saved",
                "Temporisation contexte enregistrée.",
                {"context_capture_delay_seconds": value},
            )
        except Exception as exc:
            self.log_debug("error", "app", "context_delay_save_error", str(exc), {"value": value})
            messagebox.showerror("Réglage contexte", str(exc), parent=self.root)

    def get_public_settings(self) -> dict:
        return {
            "context_capture_delay_seconds": self.get_context_capture_delay_seconds(),
            "connector": self.get_connector_settings(),
            "fly_dictation": self.get_fly_dictation_settings(),
            "recording": self.get_recording_indicator_state(),
        }

    def get_recording_indicator_label(self, source: str) -> str:
        labels = {
            "connector": "REC WEDA",
            "fly": "REC VOLÉE",
            "classic": "REC",
        }
        return labels.get(source or "classic", "REC")

    def get_recording_indicator_state(self) -> dict:
        return {
            "active": bool(self._recording_indicator_active),
            "source": self._recording_indicator_source,
            "label": self.get_recording_indicator_label(self._recording_indicator_source),
        }

    def set_recording_indicator(self, active: bool, source: str = "classic") -> None:
        self._recording_indicator_active = bool(active)
        self._recording_indicator_source = str(source or "classic") if active else ""

        label = self.get_recording_indicator_label(self._recording_indicator_source)
        self.root.title(f"[{label}] {self.base_window_title}" if active else self.base_window_title)
        self.update_tray_icon()

        if not hasattr(self, "recording_badge"):
            return
        if active:
            self.recording_badge.configure(text=label)
            if not self.recording_badge.winfo_ismapped():
                self.recording_badge.pack(
                    side=tk.LEFT,
                    padx=(0, 8),
                    before=self.continue_dictation_button,
                )
        else:
            self.recording_badge.pack_forget()

    def continue_dictation(self) -> None:
        self.start_dictation(reset_session=False, recording_source="classic")

    def new_dictation(self) -> None:
        self.reset_session_fields()
        self.start_dictation(reset_session=True, recording_source="classic")

    def start_dictation(self, *, reset_session: bool, recording_source: str = "classic") -> None:
        if self.session and self.session.is_running():
            return

        self.dictation_run_id += 1
        run_id = self.dictation_run_id
        self.session = SegmentedDictationSession(
            transcriber=self.transcriber,
            settings_provider=self.get_stt_settings,
            on_status=lambda message: self.root.after(0, self.transcription_status_var.set, message),
            on_segment_started=lambda index: self.root.after(0, self.on_segment_started, index, run_id),
            on_transcription=lambda result: self.root.after(0, self.on_transcription_result, result, run_id),
            on_error=lambda error: self.root.after(0, self.on_session_error, error, run_id),
        )
        self.set_dictation_buttons_running(True)
        self.set_recording_indicator(True, recording_source)
        self.micro_status_var.set("Micro: écoute en cours")
        self.log_debug(
            "info",
            "app",
            "dictation_started",
            "Nouvelle dictée démarrée." if reset_session else "Dictée poursuivie.",
            {
                **self.get_stt_settings(),
                "reset_session": reset_session,
                "dictation_run_id": run_id,
            },
        )
        self.session.start()

    def stop_dictation(self):
        session = self.session if self.session and not self.session.is_finished() else None
        if session and session.is_running():
            session.stop()
        self.set_dictation_buttons_running(False)
        self.set_recording_indicator(False)
        self.micro_status_var.set("Micro: arrêt demandé")
        return session

    def pending_dictation_session(self):
        if self.session and not self.session.is_finished():
            return self.session
        return None

    def wait_for_dictation_transcription(self, session, *, timeout_seconds: float | None = None) -> None:
        if not session or session.is_finished():
            return
        wait_timeout = (
            DICTATION_TRANSCRIPTION_FLUSH_TIMEOUT_SECONDS
            if timeout_seconds is None
            else float(timeout_seconds)
        )
        if not session.wait_until_finished(wait_timeout):
            raise TimeoutError("La transcription finale n’est pas terminée.")

    def set_dictation_buttons_running(self, running: bool) -> None:
        state_start = tk.DISABLED if running else tk.NORMAL
        state_stop = tk.NORMAL if running else tk.DISABLED
        self.continue_dictation_button.configure(state=state_start)
        self.new_dictation_button.configure(state=state_start)
        self.stop_dictation_button.configure(state=state_stop)

    def set_dictation_buttons_waiting(self) -> None:
        self.continue_dictation_button.configure(state=tk.DISABLED)
        self.new_dictation_button.configure(state=tk.DISABLED)
        self.stop_dictation_button.configure(state=tk.DISABLED)

    def reset_session_fields(self) -> None:
        self.dictation_run_id += 1
        if self.session and self.session.is_running():
            self.session.stop()
        self.set_recording_indicator(False)

        self.context_manager.clear()
        self.import_manager.clear()
        self.rich_result_payloads.clear()
        self.set_text(self.context_text, "")
        self.set_text(self.transcription_text, "")
        if hasattr(self, "corrected_transcription_text"):
            self.set_text(self.corrected_transcription_text, "")
        if hasattr(self, "correction_review_text"):
            self.set_text(self.correction_review_text, "", readonly=True)
        self.transcription_draft_store.clear()
        self.set_text(self.result_text, "")
        self.set_text(self.sent_message_text, "", readonly=True)
        self.set_text(self.secondary_result_text, "")
        self.set_text(self.secondary_sent_message_text, "", readonly=True)
        self.set_text(self.tertiary_result_text, "")
        self.set_text(self.tertiary_sent_message_text, "", readonly=True)
        self.set_text(self.document_now_result_text, "")
        self.set_text(self.document_now_sent_message_text, "", readonly=True)
        self.document_now_snapshots.clear()
        self.document_now_current_snapshot = None
        self.document_now_pending_checkpoints.clear()
        self.document_now_running = False
        self.configure_document_now_button_state()
        self.weda_patient_status_var.set("Patient WEDA: non reçu")
        self.transcription_status_var.set("Transcription prête")
        self.lmstudio_status_var.set("LM Studio: prêt")
        self.update_secondary_status()
        self.update_tertiary_status()
        self.update_document_now_status()
        self.import_status_var.set("Import WEDA: aucun")
        self.schedule_message_refresh()
        self.schedule_secondary_message_refresh()
        self.schedule_tertiary_message_refresh()
        self.schedule_document_now_message_refresh()
        self.log_debug("info", "app", "dictation_session_reset", "Données de session dictée effacées.")

    def set_connector_job(self, updates: dict, *, replace: bool = False) -> dict:
        with self._connector_lock:
            current = {} if replace or self.connector_job is None else dict(self.connector_job)
            current.update(updates)
            current["updated_at"] = time.time()
            self.connector_job = current
            return dict(current)

    def get_connector_job(self, job_id: str = "") -> dict | None:
        with self._connector_lock:
            if not self.connector_job:
                return None
            if job_id and self.connector_job.get("id") != job_id:
                return None
            return dict(self.connector_job)

    def set_document_now_connector_job(
        self,
        updates: dict,
        *,
        job_id: str = "",
        replace: bool = False,
    ) -> dict:
        with self._document_now_connector_lock:
            current = (
                {}
                if replace or self.document_now_connector_job is None
                else dict(self.document_now_connector_job)
            )
            if job_id and current.get("id") != job_id:
                return current
            current.update(updates)
            current["updated_at"] = time.time()
            self.document_now_connector_job = current
            return dict(current)

    def get_document_now_connector_job(self, job_id: str = "") -> dict | None:
        with self._document_now_connector_lock:
            if not self.document_now_connector_job:
                return None
            if job_id and self.document_now_connector_job.get("id") != job_id:
                return None
            return dict(self.document_now_connector_job)

    def connector_document_now(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        active_job = self.get_document_now_connector_job()
        if active_job and active_job.get("status") in {"waiting_transcription", "generating"}:
            return active_job

        job_id = uuid.uuid4().hex
        job = self.set_document_now_connector_job(
            {
                "id": job_id,
                "status": "starting",
                "message": "Préparation de « Document maintenant ».",
                "patient_id": str(payload.get("patient_id") or ""),
                "patient_identity": str(payload.get("patient_identity") or ""),
                "page_url": str(payload.get("page_url") or ""),
                "created_at": time.time(),
                "clipboard_copied": False,
            },
            replace=True,
        )
        if not self.get_connector_settings().get("enabled"):
            return self.set_document_now_connector_job(
                {
                    "status": "disabled",
                    "message": "Connecteur WEDA désactivé dans l’application.",
                },
                job_id=job_id,
            )

        try:
            self.call_ui_sync(
                lambda: self.request_connector_document_now_checkpoint(
                    job_id,
                    expected_patient_id=str(payload.get("patient_id") or ""),
                ),
                timeout_seconds=15,
            )
            job = self.get_document_now_connector_job(job_id) or job
            self.log_debug(
                "info",
                "connector",
                "connector_document_now_started",
                "Document maintenant lancé depuis WEDA.",
                {
                    "job_id": job_id,
                    "snapshot_id": job.get("snapshot_id", ""),
                    "status": job.get("status", ""),
                },
            )
        except Exception as exc:
            job = self.set_document_now_connector_job(
                {
                    "status": "error",
                    "message": str(exc),
                    "error": str(exc),
                },
                job_id=job_id,
            )
            self.log_debug("error", "connector", "connector_document_now_start_error", str(exc), job)
        return job

    def connector_start(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        if not self.get_connector_settings().get("enabled"):
            return self.set_connector_job(
                {
                    "id": uuid.uuid4().hex,
                    "status": "disabled",
                    "message": "Connecteur WEDA désactivé dans l’application.",
                    "patient_id": str(payload.get("patient_id") or ""),
                },
                replace=True,
            )

        job = self.set_connector_job(
            {
                "id": uuid.uuid4().hex,
                "status": "starting",
                "message": "Démarrage dictée connecteur.",
                "patient_id": str(payload.get("patient_id") or ""),
                "patient_identity": str(payload.get("patient_identity") or ""),
                "page_url": str(payload.get("page_url") or ""),
                "created_at": time.time(),
            },
            replace=True,
        )

        def ui_start():
            self.reset_session_fields()
            self.start_dictation(reset_session=True, recording_source="connector")
            self.micro_status_var.set("Micro: connecteur en écoute")

        try:
            self.call_ui_sync(ui_start)
            job = self.set_connector_job({"status": "recording", "message": "Dictée connecteur en cours."})
            self.log_debug("info", "connector", "connector_start", "Connecteur WEDA démarré.", job)
        except Exception as exc:
            job = self.set_connector_job({"status": "error", "message": str(exc), "error": str(exc)})
            self.log_debug("error", "connector", "connector_start_error", str(exc), job)
        return job

    def connector_stop(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        job_id = uuid.uuid4().hex
        job = self.set_connector_job(
            {
                "id": job_id,
                "status": "stopping",
                "message": "Arrêt dictée et préparation LM Studio.",
                "patient_id": str(payload.get("patient_id") or ""),
                "patient_identity": str(payload.get("patient_identity") or ""),
                "page_url": str(payload.get("page_url") or ""),
                "created_at": time.time(),
            },
            replace=True,
        )

        try:
            stopped_session = self.call_ui_sync(self.stop_dictation)
        except Exception as exc:
            job = self.set_connector_job({"status": "error", "message": str(exc), "error": str(exc)})
            self.log_debug("error", "connector", "connector_stop_error", str(exc), job)
            return job

        threading.Thread(
            target=self.run_connector_stop_worker,
            args=(job_id, payload, stopped_session),
            name="weda-connector-stop",
            daemon=True,
        ).start()
        return job

    def finalize_connector_primary_result(
        self,
        *,
        response,
        message: str,
        result_payload: RichTextPayload,
        patient_id: str,
        patient_identity: str,
    ) -> None:
        self.record_generation_metric(
            "connector",
            "result_1",
            status="success",
            elapsed_seconds=response.elapsed_seconds,
            input_chars=len(message or ""),
            result_chars=len(result_payload.text or ""),
        )
        self.set_rich_result_text(self.result_text, result_payload, source="result_1")
        self.lmstudio_status_var.set(f"LM Studio: réponse connecteur reçue en {response.elapsed_seconds:.1f}s")
        self.import_status_var.set("Import WEDA: résultat connecteur prêt")
        self.history_manager.append(
            {
                **self.current_stt_history_payload(),
                "whisper_model": self.model_manager.active_label(),
                "prompt_name": self.prompt_var.get(),
                "transcription": self.get_clean_transcription_text(),
                "weda_context": self.get_text(self.context_text),
                "sent_message": message,
                "lmstudio_result": result_payload.text,
                "status": "connector_result_ready",
                "patient_id": patient_id,
                "patient_identity": patient_identity,
            }
        )
        if self.is_secondary_auto_run_enabled():
            self.log_debug(
                "info",
                "connector",
                "connector_followup_chain_started",
                "Enchaînement automatique Prompt 2 puis Prompt 3 démarré après le Résultat 1 du connecteur.",
            )
            self.run_secondary_analysis(
                trigger="auto",
                primary_sent_message=message,
                primary_result=result_payload.text,
            )

    def run_connector_stop_worker(self, job_id: str, payload: dict, stopped_session=None) -> None:
        try:
            settings = self.get_connector_settings()
            if stopped_session and not stopped_session.is_finished():
                self.set_connector_job({
                    "status": "waiting_transcription_flush",
                    "message": "Attente de la fin complète de la transcription.",
                })
                self.wait_for_dictation_transcription(stopped_session)

            self.set_connector_job({"status": "generating", "message": "Envoi à LM Studio."})
            self.call_ui_sync(self.refresh_context_from_manager, timeout_seconds=10)
            message = self.call_ui_sync(lambda: self.refresh_sent_message().strip(), timeout_seconds=10)
            if not message:
                raise RuntimeError("Message LM Studio vide après arrêt de la dictée.")

            client = self.build_lmstudio_client()
            self.adjust_lmstudio_client_for_context(client, message, label="connecteur")
            self.call_ui_sync(lambda: self.capture_pending_result_patient_binding("result_1"), timeout_seconds=10)
            response = self.chat_lmstudio_managed_blocking("connector", client, message)
            context = self.context_manager.get_latest()
            patient_id = context.patient_id if context else str(payload.get("patient_id") or "")
            patient_identity = context.patient_identity if context else str(payload.get("patient_identity") or "")
            result_payload = self.call_ui_sync(
                lambda: self.remember_weda_result_payload(
                    "result_1",
                    self.apply_abbreviations_to_lmstudio_result(response.text, "Résultat connecteur"),
                ),
                timeout_seconds=10,
            )
            request = self.import_manager.prepare_result(
                result_payload.text,
                result_html=result_payload.html,
                patient_id=patient_id,
                patient_identity=patient_identity,
                destination="connector_auto",
            )

            self.call_ui_sync(
                lambda: self.finalize_connector_primary_result(
                    response=response,
                    message=message,
                    result_payload=result_payload,
                    patient_id=patient_id,
                    patient_identity=patient_identity,
                ),
                timeout_seconds=10,
            )
            job = self.set_connector_job(
                {
                    "status": "result_ready",
                    "message": "Résultat prêt pour insertion WEDA.",
                    "request_id": request.id,
                    "patient_id": patient_id,
                    "patient_identity": patient_identity,
                    "result_length": len(result_payload.text or ""),
                    "result_html_length": len(result_payload.html or ""),
                    "elapsed_seconds": response.elapsed_seconds,
                    "auto_return_home": bool(settings.get("auto_return_home", True)),
                }
            )
            self.log_debug("info", "connector", "connector_result_ready", "Résultat connecteur prêt.", job)
        except Exception as exc:
            try:
                self.call_ui_sync(lambda: self.discard_pending_result_patient_binding("result_1"), timeout_seconds=5)
                status = "cancelled" if isinstance(exc, LmStudioCancelled) else "error"
                self.call_ui_sync(
                    lambda metric_status=status, error=exc: self.record_generation_metric(
                        "connector",
                        "result_1",
                        status=metric_status,
                        error=error,
                    ),
                    timeout_seconds=5,
                )
            except Exception:
                status = "error"
            job = self.set_connector_job({"status": status, "message": str(exc), "error": str(exc)})
            self.log_debug(
                "info" if status == "cancelled" else "error",
                "connector",
                "connector_generation_cancelled" if status == "cancelled" else "connector_generation_error",
                str(exc),
                job,
            )

    def on_segment_started(self, index: int, run_id: int) -> None:
        if run_id != self.dictation_run_id:
            return
        self.micro_status_var.set(f"Micro: segment {index}")
        self.transcription_status_var.set(f"Segment {index} en enregistrement")

    def on_transcription_result(self, result, run_id: int) -> None:
        if run_id != self.dictation_run_id:
            return
        self.last_stt_result = getattr(result, "stt_result", None) or {}
        audio_path = str(getattr(result, "audio_path", "") or "")
        if audio_path and audio_path != "<memory>" and Path(audio_path).exists():
            self.last_stt_audio_path = audio_path
        if self.last_stt_result:
            mapped_text = clean_transcription_text(
                format_stt_text(self.last_stt_result, self.get_stt_speaker_map()),
                self.config.get("transcription_cleaning", {}),
            )
            if mapped_text:
                result.text = mapped_text
        result.text = clean_transcription_text(str(result.text or ""), self.config.get("transcription_cleaning", {}))
        previous_raw = self.get_text(self.transcription_text)
        overlap_deduplication = deduplicate_transcription_overlap(previous_raw, result.text)
        result.text = overlap_deduplication.text_to_append
        result.deduplicated_words = overlap_deduplication.removed_words
        result.deduplicated_characters = overlap_deduplication.removed_characters
        if not result.text and overlap_deduplication.removed_words:
            result.empty_reason = "overlap_duplicate_removed"
        if result.text:
            self.append_transcription_line(result.text)
            self.update_corrected_transcription_from_raw(previous_raw, result.text)
        self.model_status_var.set(f"Moteur STT: {result.model_label}")
        self.stt_status_var.set(
            f"STT: {getattr(result, 'stt_engine', '') or 'moteur'} {getattr(result, 'stt_model', '')}".strip()
        )
        if result.text:
            self.update_micro_level_status(result, ignored=False)
            self.transcription_status_var.set(
                f"Segment {result.segment_index} transcrit en {result.elapsed_seconds:.1f}s"
            )
        else:
            self.update_micro_level_status(result, ignored=True)
            self.transcription_status_var.set(
                f"Segment {result.segment_index} sans texte ({self.empty_segment_short_reason(result)})"
            )
        self.log_debug(
            "info" if result.text else "warning",
            "app",
            "segment_transcribed",
            "Segment transcrit." if result.text else "Segment transcrit sans texte.",
            {
                "segment_index": result.segment_index,
                "elapsed_seconds": result.elapsed_seconds,
                "model_label": result.model_label,
                "text_length": len(result.text or ""),
                "segments_count": getattr(result, "segments_count", 0),
                "retry_without_vad": getattr(result, "retry_without_vad", False),
                "empty_reason": getattr(result, "empty_reason", ""),
                "stt_engine": getattr(result, "stt_engine", ""),
                "stt_model": getattr(result, "stt_model", ""),
                "stt_runtime": getattr(result, "stt_runtime", ""),
                "stt_device": getattr(result, "stt_device", ""),
                "stt_warnings": getattr(result, "stt_warnings", []),
                "stt_errors": getattr(result, "stt_errors", []),
                "audio_stats": getattr(result, "audio_stats", {}),
                "checkpoint_ids": getattr(result, "checkpoint_ids", []),
                "window": getattr(result, "window_metadata", {}),
                "deduplicated_words": getattr(result, "deduplicated_words", 0),
                "deduplicated_characters": getattr(result, "deduplicated_characters", 0),
                "prompt_length": (getattr(result, "stt_result", {}) or {}).get("raw", {}).get("prompt_length", 0),
                "hotwords_count": (getattr(result, "stt_result", {}) or {}).get("raw", {}).get("hotwords_count", 0),
            },
        )
        self.handle_document_now_checkpoints(result)

    def append_transcription_line(self, text: str, *, diagnostic: bool = False) -> None:
        text = clean_transcription_text(str(text or ""), self.config.get("transcription_cleaning", {}))
        if not text:
            return
        current = self.get_text(self.transcription_text)
        separator = "\n" if current.strip() else ""
        self.set_text(self.transcription_text, current + separator + text)
        if diagnostic:
            try:
                self.transcription_text.tag_configure("diagnostic", foreground=self.theme["muted_text"])
                start = f"end-{len(text) + 1}c"
                self.transcription_text.tag_add("diagnostic", start, "end-1c")
            except Exception:
                pass

    def update_corrected_transcription_from_raw(self, previous_raw: str, appended_raw: str) -> None:
        if not hasattr(self, "corrected_transcription_text"):
            return
        current_corrected = self.get_text(self.corrected_transcription_text)
        full_raw = self.get_text(self.transcription_text)
        if not current_corrected or current_corrected.strip() == str(previous_raw or "").strip():
            candidate = full_raw
        else:
            deduplicated = deduplicate_transcription_overlap(current_corrected, appended_raw)
            separator = "\n" if current_corrected.strip() and deduplicated.text_to_append else ""
            candidate = current_corrected + separator + deduplicated.text_to_append
        medical_config = self.config.get("medical_transcription", {})
        apply_automatic = bool(
            self.whisper_apply_corrections_var.get()
            if hasattr(self, "whisper_apply_corrections_var")
            else medical_config.get("apply_validated_corrections", False)
        )
        applied = 0
        if apply_automatic:
            candidate, applied = self.correction_store.apply_conservative(
                candidate,
                min_validations=int(
                    medical_config.get(
                        "min_validations_for_automatic_correction",
                        MIN_VALIDATIONS_FOR_AUTOMATIC_CORRECTION,
                    )
                ),
            )
        self.set_text(self.corrected_transcription_text, candidate)
        if applied:
            self.log_debug(
                "info",
                "transcription",
                "validated_corrections_applied",
                "Corrections locales très fiables appliquées à la couche corrigée.",
                {"count": applied},
            )

    def update_micro_level_status(self, result, *, ignored: bool) -> None:
        audio_stats = getattr(result, "audio_stats", {}) or {}
        rms = float(audio_stats.get("rms") or 0.0)
        peak = float(audio_stats.get("peak") or 0.0)
        if ignored:
            self.micro_status_var.set(
                f"Segment ignoré : {self.empty_segment_short_reason(result)} ; RMS {rms:.6f} / peak {peak:.6f}"
            )
            return
        self.micro_status_var.set(f"Niveau micro : RMS {rms:.6f} / peak {peak:.6f}")

    def empty_segment_short_reason(self, result) -> str:
        reason = str(getattr(result, "empty_reason", "") or "")
        labels = {
            "audio_empty": "audio vide",
            "audio_too_short": "audio trop court",
            "audio_silent_or_wrong_input_device": "silence ou mauvais micro",
            "no_text_after_retry_without_vad": "signal détecté mais aucun texte",
            "no_speech_segment_detected": "aucune parole détectée",
            "overlap_duplicate_removed": "répétition de chevauchement retirée",
            "speech_segment_without_text": "segment sans texte",
        }
        return labels.get(reason, reason or "aucun texte")

    def on_session_error(self, error: Exception, run_id: int) -> None:
        if run_id != self.dictation_run_id:
            return
        if self.document_now_pending_checkpoints:
            self.document_now_pending_checkpoints.clear()
            self.document_now_status_var.set("Document maintenant: checkpoint annulé après erreur STT")
        self.set_dictation_buttons_running(False)
        self.set_recording_indicator(False)
        self.micro_status_var.set("Micro: erreur")
        self.transcription_status_var.set("Transcription: erreur")
        self.log_debug("error", "app", "dictation_error", str(error))
        messagebox.showerror("Dictée / transcription", str(error))

    def list_common_lmstudio_prompts(self):
        return self.prompt_manager.list_prompts(prompt_type="generic")

    def refresh_common_prompt_combos(self, *, target: str = "primary", selected_id: str | None = None) -> None:
        current_ids = {
            "primary": self.current_prompt_id() if hasattr(self, "prompt_combo") else "",
            "secondary": self.current_secondary_prompt_id() if hasattr(self, "secondary_prompt_combo") else "",
            "tertiary": self.current_tertiary_prompt_id() if hasattr(self, "tertiary_prompt_combo") else "",
            "document_now": self.current_document_now_prompt_id() if hasattr(self, "document_now_prompt_combo") else "",
        }
        self._refresh_prompt_combo(selected_id if target == "primary" else current_ids.get("primary") or None)
        self._refresh_secondary_prompt_combo(selected_id if target == "secondary" else current_ids.get("secondary") or None)
        self._refresh_tertiary_prompt_combo(selected_id if target == "tertiary" else current_ids.get("tertiary") or None)
        self._refresh_document_now_prompt_combo(
            selected_id if target == "document_now" else current_ids.get("document_now") or None
        )

    def is_protected_common_prompt(self, prompt_id: str, *, title: str = "Prompt") -> bool:
        protected = {
            SECONDARY_ANALYSIS_PROMPT_ID: "Le prompt secondaire par défaut ne peut pas être supprimé.",
            TERTIARY_ANALYSIS_PROMPT_ID: "Le prompt tertiaire par défaut ne peut pas être supprimé.",
            DOCUMENT_NOW_PROMPT_ID: "Le prompt Document maintenant par défaut ne peut pas être supprimé.",
        }
        message = protected.get(prompt_id)
        if not message:
            return False
        messagebox.showwarning(title, message, parent=self.root)
        return True

    def reset_prompt_references_after_delete(self, prompt_id: str) -> None:
        changed = False
        secondary_config = normalize_secondary_analysis_config(self.config.get("secondary_analysis", {}))
        secondary_changed = False
        if secondary_config.get("default_prompt_id") == prompt_id:
            secondary_config["default_prompt_id"] = SECONDARY_ANALYSIS_PROMPT_ID
            secondary_changed = True
        if secondary_config.get("last_prompt_id") == prompt_id:
            secondary_config["last_prompt_id"] = secondary_config["default_prompt_id"]
            secondary_changed = True
        if secondary_changed:
            self.config["secondary_analysis"] = secondary_config
            changed = True
        tertiary_config = normalize_tertiary_analysis_config(self.config.get("tertiary_analysis", {}))
        tertiary_changed = False
        if tertiary_config.get("default_prompt_id") == prompt_id:
            tertiary_config["default_prompt_id"] = TERTIARY_ANALYSIS_PROMPT_ID
            tertiary_changed = True
        if tertiary_config.get("last_prompt_id") == prompt_id:
            tertiary_config["last_prompt_id"] = tertiary_config["default_prompt_id"]
            tertiary_changed = True
        if tertiary_changed:
            self.config["tertiary_analysis"] = tertiary_config
            changed = True
        document_now_config = self.config.setdefault("document_now", {})
        if document_now_config.get("default_prompt_id") == prompt_id:
            document_now_config["default_prompt_id"] = DOCUMENT_NOW_PROMPT_ID
            changed = True
        if document_now_config.get("last_prompt_id") == prompt_id:
            document_now_config["last_prompt_id"] = document_now_config["default_prompt_id"]
            changed = True
        if changed:
            save_json(BASE_DIR / "config.json", self.config)

    def _refresh_prompt_combo(self, selected_id: str | None = None) -> None:
        prompts = self.list_common_lmstudio_prompts()
        self.prompt_name_to_id = {prompt.name: prompt.id for prompt in prompts}
        self.prompt_combo["values"] = [prompt.name for prompt in prompts] if hasattr(self, "prompt_combo") else []

        selected = self.prompt_manager.get(selected_id) if selected_id else None
        if selected is None:
            selected = self.prompt_manager.get(str(self.config.get("ui", {}).get("last_prompt_id") or ""))
        if selected is not None and selected.prompt_type != "generic":
            selected = None
        if selected is None:
            selected = self.prompt_manager.get_default("generic")
        if selected:
            self.prompt_var.set(selected.name)
            self.load_selected_prompt()

    def current_prompt_id(self) -> str:
        return self.prompt_name_to_id.get(self.prompt_var.get(), "")

    def load_selected_prompt(self) -> None:
        prompt = self.prompt_manager.get(self.current_prompt_id())
        if not prompt:
            return
        self.set_text(self.prompt_text, prompt.content)
        marker = " par défaut" if prompt.is_default else ""
        self.prompt_status_var.set(f"Prompt: {prompt.name}{marker}")

    def on_prompt_selected(self) -> None:
        self.load_selected_prompt()
        self.capture_prompt_selection_settings()
        self.write_runtime_config("prompt_selection")

    def new_prompt(self) -> None:
        name = simpledialog.askstring("Nouveau prompt", "Nom du prompt :", parent=self.root)
        if not name:
            return
        prompt = self.prompt_manager.create(name, self.get_text(self.prompt_text), prompt_type="generic")
        self.refresh_common_prompt_combos(target="primary", selected_id=prompt.id)

    def save_prompt(self) -> None:
        prompt_id = self.current_prompt_id()
        if not prompt_id:
            return
        prompt = self.prompt_manager.update(prompt_id, content=self.get_text(self.prompt_text), prompt_type="generic")
        self.refresh_common_prompt_combos(target="primary", selected_id=prompt.id)
        self.prompt_status_var.set(f"Prompt enregistré: {prompt.name}")

    def duplicate_prompt(self) -> None:
        prompt_id = self.current_prompt_id()
        if not prompt_id:
            return
        name = simpledialog.askstring("Dupliquer prompt", "Nom de la copie :", parent=self.root)
        source = self.prompt_manager.get(prompt_id)
        prompt = self.prompt_manager.create(
            name or (f"{source.name} - copie" if source else "Prompt - copie"),
            self.get_text(self.prompt_text),
            prompt_type="generic",
        )
        self.refresh_common_prompt_combos(target="primary", selected_id=prompt.id)

    def delete_prompt(self) -> None:
        prompt_id = self.current_prompt_id()
        if not prompt_id:
            return
        if self.is_protected_common_prompt(prompt_id, title="Prompt"):
            return
        if not messagebox.askyesno("Supprimer prompt", "Supprimer ce prompt ?", parent=self.root):
            return
        try:
            self.prompt_manager.delete(prompt_id)
            self.reset_prompt_references_after_delete(prompt_id)
            self.refresh_common_prompt_combos(target="primary")
        except Exception as exc:
            messagebox.showerror("Prompt", str(exc))

    def set_default_prompt(self) -> None:
        prompt_id = self.current_prompt_id()
        if not prompt_id:
            return
        self.prompt_manager.set_default(prompt_id)
        self.config.setdefault("ui", {})["last_prompt_id"] = prompt_id
        self.write_runtime_config("default_prompt_selection")
        self.refresh_common_prompt_combos(target="primary", selected_id=prompt_id)

    def _refresh_secondary_prompt_combo(self, selected_id: str | None = None) -> None:
        prompts = self.list_common_lmstudio_prompts()
        self.secondary_prompt_name_to_id = {prompt.name: prompt.id for prompt in prompts}
        if hasattr(self, "secondary_prompt_combo"):
            self.secondary_prompt_combo["values"] = [prompt.name for prompt in prompts]

        secondary_raw_config = self.config.get("secondary_analysis", {})
        secondary_config = normalize_secondary_analysis_config(secondary_raw_config)
        selected = self.prompt_manager.get(selected_id) if selected_id else None
        if selected is None:
            selected = self.prompt_manager.get(str(secondary_raw_config.get("last_prompt_id") or ""))
        if selected is None or selected.prompt_type != "generic":
            selected = self.prompt_manager.get(str(secondary_config.get("default_prompt_id") or ""))
        if selected is None or selected.prompt_type != "generic":
            selected = self.prompt_manager.get_default("generic")
        if selected:
            self.secondary_prompt_var.set(selected.name)
            self.load_selected_secondary_prompt()
        self.update_secondary_status()

    def current_secondary_prompt_id(self) -> str:
        return self.secondary_prompt_name_to_id.get(self.secondary_prompt_var.get(), "")

    def load_selected_secondary_prompt(self) -> None:
        prompt = self.prompt_manager.get(self.current_secondary_prompt_id())
        if not prompt:
            return
        self.set_text(self.secondary_prompt_text, prompt.content)
        self.update_secondary_status(prompt=prompt)
        self.schedule_secondary_message_refresh()

    def on_secondary_prompt_selected(self) -> None:
        self.load_selected_secondary_prompt()
        self.capture_prompt_selection_settings()
        self.write_runtime_config("secondary_prompt_selection")

    def update_secondary_status(self, prompt=None) -> None:
        if prompt is None:
            prompt = self.prompt_manager.get(self.current_secondary_prompt_id())
        enabled = bool(self.secondary_enabled_var.get())
        if not prompt:
            self.secondary_status_var.set("Prompt 2: aucun")
            return
        secondary_config = normalize_secondary_analysis_config(self.config.get("secondary_analysis", {}))
        marker = " par défaut" if prompt.id == str(secondary_config.get("default_prompt_id") or "") else ""
        state = "actif" if enabled else "désactivé"
        self.secondary_status_var.set(f"Prompt 2: {state}, {prompt.name}{marker}")

    def save_secondary_analysis_settings(self) -> None:
        secondary_config = normalize_secondary_analysis_config(self.config.get("secondary_analysis", {}))
        secondary_config["enabled"] = bool(self.secondary_enabled_var.get())
        if self.current_secondary_prompt_id():
            secondary_config["last_prompt_id"] = self.current_secondary_prompt_id()
            secondary_config["default_prompt_id"] = secondary_config.get("default_prompt_id") or self.current_secondary_prompt_id()
        self.config["secondary_analysis"] = secondary_config
        try:
            save_json(BASE_DIR / "config.json", self.config)
        except Exception as exc:
            self.log_debug("error", "app", "secondary_analysis_settings_save_error", str(exc))
        self.update_secondary_status()
        self.schedule_secondary_message_refresh()

    def new_secondary_prompt(self) -> None:
        name = simpledialog.askstring("Nouveau prompt", "Nom du prompt :", parent=self.root)
        if not name:
            return
        prompt = self.prompt_manager.create(name, self.get_text(self.secondary_prompt_text), prompt_type="generic")
        self.refresh_common_prompt_combos(target="secondary", selected_id=prompt.id)

    def save_secondary_prompt(self) -> None:
        prompt_id = self.current_secondary_prompt_id()
        if not prompt_id:
            return
        prompt = self.prompt_manager.update(prompt_id, content=self.get_text(self.secondary_prompt_text), prompt_type="generic")
        self.refresh_common_prompt_combos(target="secondary", selected_id=prompt.id)
        self.secondary_status_var.set(f"Prompt 2 enregistré: {prompt.name}")

    def duplicate_secondary_prompt(self) -> None:
        prompt_id = self.current_secondary_prompt_id()
        if not prompt_id:
            return
        name = simpledialog.askstring("Dupliquer prompt 2", "Nom de la copie :", parent=self.root)
        source = self.prompt_manager.get(prompt_id)
        default_name = f"{source.name} - copie" if source else "Prompt 2 - copie"
        prompt = self.prompt_manager.create(
            name or default_name,
            self.get_text(self.secondary_prompt_text),
            prompt_type="generic",
        )
        self.refresh_common_prompt_combos(target="secondary", selected_id=prompt.id)

    def delete_secondary_prompt(self) -> None:
        prompt_id = self.current_secondary_prompt_id()
        if not prompt_id:
            return
        if self.is_protected_common_prompt(prompt_id, title="Prompt 2"):
            return
        if not messagebox.askyesno("Supprimer prompt 2", "Supprimer ce prompt secondaire ?", parent=self.root):
            return
        try:
            self.prompt_manager.delete(prompt_id)
            self.reset_prompt_references_after_delete(prompt_id)
            self.refresh_common_prompt_combos(target="secondary")
        except Exception as exc:
            messagebox.showerror("Prompt 2", str(exc), parent=self.root)

    def set_default_secondary_prompt(self) -> None:
        prompt_id = self.current_secondary_prompt_id()
        if not prompt_id:
            return
        prompt = self.prompt_manager.get(prompt_id)
        if not prompt:
            return
        secondary_config = normalize_secondary_analysis_config(self.config.get("secondary_analysis", {}))
        secondary_config["default_prompt_id"] = prompt.id
        secondary_config["last_prompt_id"] = prompt.id
        self.config["secondary_analysis"] = secondary_config
        try:
            save_json(BASE_DIR / "config.json", self.config)
        except Exception as exc:
            self.log_debug("error", "app", "secondary_default_prompt_save_error", str(exc))
        self.refresh_common_prompt_combos(target="secondary", selected_id=prompt.id)

    def _refresh_tertiary_prompt_combo(self, selected_id: str | None = None) -> None:
        prompts = self.list_common_lmstudio_prompts()
        self.tertiary_prompt_name_to_id = {prompt.name: prompt.id for prompt in prompts}
        if hasattr(self, "tertiary_prompt_combo"):
            self.tertiary_prompt_combo["values"] = [prompt.name for prompt in prompts]

        tertiary_raw_config = self.config.get("tertiary_analysis", {})
        tertiary_config = normalize_tertiary_analysis_config(tertiary_raw_config)
        selected = self.prompt_manager.get(selected_id) if selected_id else None
        if selected is None:
            selected = self.prompt_manager.get(str(tertiary_raw_config.get("last_prompt_id") or ""))
        if selected is None or selected.prompt_type != "generic":
            selected = self.prompt_manager.get(str(tertiary_config.get("default_prompt_id") or ""))
        if selected is None or selected.prompt_type != "generic":
            selected = self.prompt_manager.get_default("generic")
        if selected:
            self.tertiary_prompt_var.set(selected.name)
            self.load_selected_tertiary_prompt()
        self.update_tertiary_status()

    def current_tertiary_prompt_id(self) -> str:
        return self.tertiary_prompt_name_to_id.get(self.tertiary_prompt_var.get(), "")

    def load_selected_tertiary_prompt(self) -> None:
        prompt = self.prompt_manager.get(self.current_tertiary_prompt_id())
        if not prompt:
            return
        self.set_text(self.tertiary_prompt_text, prompt.content)
        self.update_tertiary_status(prompt=prompt)
        self.schedule_tertiary_message_refresh()

    def on_tertiary_prompt_selected(self) -> None:
        self.load_selected_tertiary_prompt()
        self.capture_prompt_selection_settings()
        self.write_runtime_config("tertiary_prompt_selection")

    def update_tertiary_status(self, prompt=None) -> None:
        if prompt is None:
            prompt = self.prompt_manager.get(self.current_tertiary_prompt_id())
        enabled = bool(self.tertiary_enabled_var.get())
        if not prompt:
            self.tertiary_status_var.set("Prompt 3: aucun")
            return
        tertiary_config = normalize_tertiary_analysis_config(self.config.get("tertiary_analysis", {}))
        marker = " par défaut" if prompt.id == str(tertiary_config.get("default_prompt_id") or "") else ""
        state = "actif" if enabled else "désactivé"
        self.tertiary_status_var.set(f"Prompt 3: {state}, {prompt.name}{marker}")

    def save_tertiary_analysis_settings(self) -> None:
        tertiary_config = normalize_tertiary_analysis_config(self.config.get("tertiary_analysis", {}))
        tertiary_config["enabled"] = bool(self.tertiary_enabled_var.get())
        if self.current_tertiary_prompt_id():
            tertiary_config["last_prompt_id"] = self.current_tertiary_prompt_id()
            tertiary_config["default_prompt_id"] = tertiary_config.get("default_prompt_id") or self.current_tertiary_prompt_id()
        self.config["tertiary_analysis"] = tertiary_config
        try:
            save_json(BASE_DIR / "config.json", self.config)
        except Exception as exc:
            self.log_debug("error", "app", "tertiary_analysis_settings_save_error", str(exc))
        self.update_tertiary_status()
        self.schedule_tertiary_message_refresh()

    def new_tertiary_prompt(self) -> None:
        name = simpledialog.askstring("Nouveau prompt", "Nom du prompt :", parent=self.root)
        if not name:
            return
        prompt = self.prompt_manager.create(name, self.get_text(self.tertiary_prompt_text), prompt_type="generic")
        self.refresh_common_prompt_combos(target="tertiary", selected_id=prompt.id)

    def save_tertiary_prompt(self) -> None:
        prompt_id = self.current_tertiary_prompt_id()
        if not prompt_id:
            return
        prompt = self.prompt_manager.update(prompt_id, content=self.get_text(self.tertiary_prompt_text), prompt_type="generic")
        self.refresh_common_prompt_combos(target="tertiary", selected_id=prompt.id)
        self.tertiary_status_var.set(f"Prompt 3 enregistré: {prompt.name}")

    def duplicate_tertiary_prompt(self) -> None:
        prompt_id = self.current_tertiary_prompt_id()
        if not prompt_id:
            return
        name = simpledialog.askstring("Dupliquer prompt 3", "Nom de la copie :", parent=self.root)
        source = self.prompt_manager.get(prompt_id)
        default_name = f"{source.name} - copie" if source else "Prompt 3 - copie"
        prompt = self.prompt_manager.create(
            name or default_name,
            self.get_text(self.tertiary_prompt_text),
            prompt_type="generic",
        )
        self.refresh_common_prompt_combos(target="tertiary", selected_id=prompt.id)

    def delete_tertiary_prompt(self) -> None:
        prompt_id = self.current_tertiary_prompt_id()
        if not prompt_id:
            return
        if self.is_protected_common_prompt(prompt_id, title="Prompt 3"):
            return
        if not messagebox.askyesno("Supprimer prompt 3", "Supprimer ce prompt tertiaire ?", parent=self.root):
            return
        try:
            self.prompt_manager.delete(prompt_id)
            self.reset_prompt_references_after_delete(prompt_id)
            self.refresh_common_prompt_combos(target="tertiary")
        except Exception as exc:
            messagebox.showerror("Prompt 3", str(exc), parent=self.root)

    def set_default_tertiary_prompt(self) -> None:
        prompt_id = self.current_tertiary_prompt_id()
        if not prompt_id:
            return
        prompt = self.prompt_manager.get(prompt_id)
        if not prompt:
            return
        tertiary_config = normalize_tertiary_analysis_config(self.config.get("tertiary_analysis", {}))
        tertiary_config["default_prompt_id"] = prompt.id
        tertiary_config["last_prompt_id"] = prompt.id
        self.config["tertiary_analysis"] = tertiary_config
        try:
            save_json(BASE_DIR / "config.json", self.config)
        except Exception as exc:
            self.log_debug("error", "app", "tertiary_default_prompt_save_error", str(exc))
        self.refresh_common_prompt_combos(target="tertiary", selected_id=prompt.id)

    def _refresh_document_now_prompt_combo(self, selected_id: str | None = None) -> None:
        prompts = self.list_common_lmstudio_prompts()
        if not prompts:
            self.ensure_document_now_prompt()
            prompts = self.list_common_lmstudio_prompts()
        self.document_now_prompt_name_to_id = {prompt.name: prompt.id for prompt in prompts}
        if hasattr(self, "document_now_prompt_combo"):
            self.document_now_prompt_combo["values"] = [prompt.name for prompt in prompts]

        document_now_config = self.config.setdefault("document_now", {})
        selected = self.prompt_manager.get(selected_id) if selected_id else None
        if selected is None:
            selected = self.prompt_manager.get(str(document_now_config.get("last_prompt_id") or ""))
        if selected is None or selected.prompt_type != "generic":
            selected = self.prompt_manager.get(str(document_now_config.get("default_prompt_id") or ""))
        if selected is None:
            selected = self.prompt_manager.get(DOCUMENT_NOW_PROMPT_ID)
        if selected is None or selected.prompt_type != "generic":
            selected = self.prompt_manager.get_default("generic")
        if selected:
            self.document_now_prompt_var.set(selected.name)
            self.load_selected_document_now_prompt()
        self.update_document_now_status()

    def current_document_now_prompt_id(self) -> str:
        return self.document_now_prompt_name_to_id.get(self.document_now_prompt_var.get(), "")

    def load_selected_document_now_prompt(self) -> None:
        prompt = self.prompt_manager.get(self.current_document_now_prompt_id())
        if not prompt:
            return
        self.set_text(self.document_now_prompt_text, prompt.content)
        self.update_document_now_status(prompt=prompt)
        self.schedule_document_now_message_refresh()

    def on_document_now_prompt_selected(self) -> None:
        self.load_selected_document_now_prompt()
        self.capture_prompt_selection_settings()
        self.write_runtime_config("document_now_prompt_selection")

    def get_document_now_default_prompt_prefix(self) -> str:
        if hasattr(self, "document_now_default_prompt_text"):
            return self.get_text(self.document_now_default_prompt_text).strip()
        return str(
            self.config.setdefault("document_now", {}).get("default_prompt_prefix")
            or DEFAULT_DOCUMENT_NOW_PROMPT_PREFIX
        ).strip()

    def save_document_now_default_prompt(self) -> None:
        self.capture_document_now_default_prompt_setting()
        try:
            save_json(BASE_DIR / "config.json", self.config)
            self.document_now_status_var.set("Document maintenant: prompt défaut enregistré")
        except Exception as exc:
            self.log_debug("warning", "app", "document_now_default_prompt_prefix_save_error", str(exc))
            self.document_now_status_var.set("Document maintenant: erreur sauvegarde prompt défaut")
        self.schedule_document_now_message_refresh()

    def reset_document_now_default_prompt(self) -> None:
        if not messagebox.askyesno(
            "Document maintenant",
            "Réinitialiser le prompt par défaut ajouté au Document maintenant ?",
            parent=self.root,
        ):
            return
        if hasattr(self, "document_now_default_prompt_text"):
            self.set_text(self.document_now_default_prompt_text, DEFAULT_DOCUMENT_NOW_PROMPT_PREFIX)
        self.save_document_now_default_prompt()

    def compose_document_now_prompt_content(self, prompt_content: str) -> str:
        parts = [
            self.get_document_now_default_prompt_prefix(),
            str(prompt_content or "").strip(),
        ]
        return "\n\n".join(part for part in parts if part).strip()

    def update_document_now_status(self, prompt=None) -> None:
        if prompt is None:
            prompt = self.prompt_manager.get(self.current_document_now_prompt_id())
        if self.document_now_running:
            self.document_now_status_var.set("Document maintenant: génération en cours")
            return
        if not prompt:
            self.document_now_status_var.set("Document maintenant: aucun prompt")
            return
        default_id = str(self.config.setdefault("document_now", {}).get("default_prompt_id") or "")
        marker = " par défaut" if prompt.id == default_id else ""
        self.document_now_status_var.set(f"Document maintenant: {prompt.name}{marker}")

    def new_document_now_prompt(self) -> None:
        name = simpledialog.askstring("Nouveau prompt Document maintenant", "Nom du prompt :", parent=self.root)
        if not name:
            return
        prompt = self.prompt_manager.create(
            name,
            self.get_text(self.document_now_prompt_text),
            prompt_type="generic",
        )
        self.refresh_common_prompt_combos(target="document_now", selected_id=prompt.id)

    def save_document_now_prompt(self) -> None:
        prompt_id = self.current_document_now_prompt_id()
        if not prompt_id:
            return
        prompt = self.prompt_manager.update(
            prompt_id,
            content=self.get_text(self.document_now_prompt_text),
            prompt_type="generic",
        )
        self.refresh_common_prompt_combos(target="document_now", selected_id=prompt.id)
        self.document_now_status_var.set(f"Document maintenant: prompt enregistré ({prompt.name})")

    def duplicate_document_now_prompt(self) -> None:
        prompt_id = self.current_document_now_prompt_id()
        if not prompt_id:
            return
        source = self.prompt_manager.get(prompt_id)
        default_name = f"{source.name} - copie" if source else "Document maintenant - copie"
        name = simpledialog.askstring(
            "Dupliquer prompt Document maintenant",
            "Nom de la copie :",
            initialvalue=default_name,
            parent=self.root,
        )
        prompt = self.prompt_manager.create(
            name or default_name,
            self.get_text(self.document_now_prompt_text),
            prompt_type="generic",
        )
        self.refresh_common_prompt_combos(target="document_now", selected_id=prompt.id)

    def delete_document_now_prompt(self) -> None:
        prompt_id = self.current_document_now_prompt_id()
        if not prompt_id:
            return
        if self.is_protected_common_prompt(prompt_id, title="Document maintenant"):
            return
        if not messagebox.askyesno("Supprimer prompt Document maintenant", "Supprimer ce prompt ?", parent=self.root):
            return
        try:
            self.prompt_manager.delete(prompt_id)
            self.reset_prompt_references_after_delete(prompt_id)
            self.refresh_common_prompt_combos(target="document_now")
        except Exception as exc:
            messagebox.showerror("Document maintenant", str(exc), parent=self.root)

    def set_default_document_now_prompt(self) -> None:
        prompt_id = self.current_document_now_prompt_id()
        if not prompt_id:
            return
        prompt = self.prompt_manager.get(prompt_id)
        if not prompt:
            return
        document_now_config = self.config.setdefault("document_now", {})
        document_now_config["default_prompt_id"] = prompt.id
        document_now_config["last_prompt_id"] = prompt.id
        try:
            save_json(BASE_DIR / "config.json", self.config)
        except Exception as exc:
            self.log_debug("warning", "app", "document_now_default_prompt_save_error", str(exc))
        self.refresh_common_prompt_combos(target="document_now", selected_id=prompt.id)

    def _refresh_whisper_initial_prompt_combo(self, selected_id: str | None = None) -> None:
        prompts = self.whisper_initial_prompt_manager.list_prompts()
        self.whisper_initial_prompt_name_to_id = {prompt.name: prompt.id for prompt in prompts}
        if hasattr(self, "whisper_initial_prompt_combo"):
            self.whisper_initial_prompt_combo["values"] = [prompt.name for prompt in prompts]

        selected = self.whisper_initial_prompt_manager.get(selected_id) if selected_id else self.whisper_initial_prompt_manager.get_default()
        if selected:
            self.whisper_initial_prompt_var.set(selected.name)
            self.load_selected_whisper_initial_prompt()

    def current_whisper_initial_prompt_id(self) -> str:
        return self.whisper_initial_prompt_name_to_id.get(self.whisper_initial_prompt_var.get(), "")

    def load_selected_whisper_initial_prompt(self) -> None:
        prompt = self.whisper_initial_prompt_manager.get(self.current_whisper_initial_prompt_id())
        if not prompt:
            return
        self.set_text(self.whisper_initial_prompt_text, prompt.content)
        marker = " actif" if prompt.is_default else ""
        self.whisper_initial_prompt_status_var.set(f"Prompt Whisper: {prompt.name}{marker}")

    def on_whisper_initial_prompt_selected(self) -> None:
        self.load_selected_whisper_initial_prompt()
        self.activate_selected_whisper_initial_prompt(save_current=False)

    def activate_selected_whisper_initial_prompt(self, *, save_current: bool = True) -> None:
        prompt_id = self.current_whisper_initial_prompt_id()
        if not prompt_id:
            return
        if save_current:
            self.whisper_initial_prompt_manager.update(
                prompt_id,
                content=self.get_text(self.whisper_initial_prompt_text),
            )
        self.whisper_initial_prompt_manager.set_default(prompt_id)
        prompt = self.whisper_initial_prompt_manager.get(prompt_id)
        self.sync_active_whisper_initial_prompt_config(prompt)
        self._refresh_whisper_initial_prompt_combo(prompt_id)
        if prompt:
            self.log_debug(
                "info",
                "app",
                "whisper_initial_prompt_activated",
                "Prompt initial Whisper activé.",
                {"prompt_name": prompt.name, "prompt_length": len(prompt.content or "")},
            )

    def new_whisper_initial_prompt(self) -> None:
        name = simpledialog.askstring("Nouveau prompt Whisper", "Nom du prompt initial Whisper :", parent=self.root)
        if not name:
            return
        prompt = self.whisper_initial_prompt_manager.create(name, self.get_active_whisper_initial_prompt_text())
        self._refresh_whisper_initial_prompt_combo(prompt.id)
        self.activate_selected_whisper_initial_prompt()

    def save_whisper_initial_prompt(self) -> None:
        prompt_id = self.current_whisper_initial_prompt_id()
        if not prompt_id:
            return
        prompt = self.whisper_initial_prompt_manager.update(
            prompt_id,
            content=self.get_text(self.whisper_initial_prompt_text),
        )
        if prompt.is_default:
            self.sync_active_whisper_initial_prompt_config(prompt)
        self.save_medical_transcription_settings()
        self._refresh_whisper_initial_prompt_combo(prompt.id)
        self.whisper_initial_prompt_status_var.set(f"Prompt Whisper enregistré: {prompt.name}")
        self.log_debug(
            "info",
            "app",
            "whisper_initial_prompt_saved",
            "Prompt initial Whisper enregistré.",
            {"prompt_name": prompt.name, "prompt_length": len(prompt.content or "")},
        )

    def restore_default_whisper_medical_prompt(self) -> None:
        self.set_text(self.whisper_initial_prompt_text, DEFAULT_WHISPER_INITIAL_PROMPT)
        self.save_whisper_initial_prompt()
        self.whisper_initial_prompt_status_var.set("Prompt Whisper médical par défaut restauré")

    def save_medical_transcription_settings(self) -> None:
        target = self.config.setdefault("medical_transcription", {})
        target["include_weda_context_in_whisper_prompt"] = bool(self.whisper_include_weda_context_var.get())
        target["use_dynamic_weda_hotwords"] = bool(self.whisper_use_dynamic_hotwords_var.get())
        target["apply_validated_corrections"] = bool(self.whisper_apply_corrections_var.get())
        if hasattr(self, "permanent_hotwords_text"):
            target["permanent_hotwords"] = parse_permanent_hotwords(self.get_text(self.permanent_hotwords_text))
        try:
            save_json(BASE_DIR / "config.json", self.config)
            self.whisper_initial_prompt_status_var.set("Réglages Whisper médical enregistrés")
        except Exception as exc:
            self.log_debug("error", "app", "medical_transcription_settings_save_error", str(exc))

    def show_whisper_diagnostic_window(self) -> None:
        settings = self.get_stt_settings()
        diagnostics = settings.get("medical_whisper_diagnostics", {})
        window = tk.Toplevel(self.root)
        window.title("Diagnostic Whisper médical")
        window.geometry("900x650")
        frame = ttk.Frame(window, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        text = self.create_text_widget(frame, wrap=tk.WORD, undo=False)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(frame, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.configure(yscrollcommand=scrollbar.set)
        final_hotwords = diagnostics.get("final_hotwords", [])
        content = (
            "PROMPT FINAL TRANSMIS À WHISPER\n\n"
            f"{diagnostics.get('final_prompt', '')}\n\n"
            "HOTWORDS\n"
            f"- permanents : {diagnostics.get('permanent_hotwords_count', 0)}\n"
            f"- extraits de WEDA : {diagnostics.get('weda_hotwords_count', 0)}\n"
            f"- corrections validées : {diagnostics.get('correction_hotwords_count', 0)}\n"
            f"- total transmis : {len(final_hotwords)}\n\n"
            + "\n".join(final_hotwords)
        )
        self.set_text(text, content, readonly=True)

    def duplicate_whisper_initial_prompt(self) -> None:
        prompt_id = self.current_whisper_initial_prompt_id()
        if not prompt_id:
            return
        name = simpledialog.askstring("Dupliquer prompt Whisper", "Nom de la copie :", parent=self.root)
        prompt = self.whisper_initial_prompt_manager.duplicate(prompt_id, new_name=name or None)
        self._refresh_whisper_initial_prompt_combo(prompt.id)
        self.activate_selected_whisper_initial_prompt()

    def delete_whisper_initial_prompt(self) -> None:
        prompt_id = self.current_whisper_initial_prompt_id()
        if not prompt_id:
            return
        if not messagebox.askyesno("Supprimer prompt Whisper", "Supprimer ce prompt initial Whisper ?", parent=self.root):
            return
        try:
            self.whisper_initial_prompt_manager.delete(prompt_id)
            self._refresh_whisper_initial_prompt_combo()
            prompt = self.whisper_initial_prompt_manager.get_default()
            self.sync_active_whisper_initial_prompt_config(prompt)
        except Exception as exc:
            messagebox.showerror("Prompt Whisper", str(exc), parent=self.root)

    def load_abbreviations_text(self) -> None:
        try:
            text = ABBREVIATIONS_PATH.read_text(encoding="utf-8") if ABBREVIATIONS_PATH.exists() else "find,replace\n"
            self.set_text(self.abbreviations_text, text)
            self.update_abbreviations_status()
            self.schedule_message_refresh()
        except Exception as exc:
            self.abbreviations_status_var.set("Abréviations: erreur")
            self.log_debug("error", "app", "abbreviations_load_error", str(exc))
            messagebox.showerror("Abréviations", str(exc), parent=self.root)

    def save_abbreviations(self) -> None:
        text = self.get_text(self.abbreviations_text).strip()
        entries, errors = parse_abbreviations_csv(text)
        if errors:
            preview = "\n".join(errors[:6])
            if len(errors) > 6:
                preview += f"\n... +{len(errors) - 6} erreurs"
            if not messagebox.askyesno(
                "Abréviations",
                "Certaines lignes ne respectent pas le format find,replace.\n\n"
                + preview
                + "\n\nEnregistrer quand même ?",
                parent=self.root,
            ):
                return

        ABBREVIATIONS_PATH.write_text(text + "\n", encoding="utf-8")
        self.update_abbreviations_status(entries=entries, errors=errors)
        self.log_debug(
            "info",
            "app",
            "abbreviations_saved",
            "Liste d’abréviations enregistrée.",
            {"entries": len(entries), "errors": len(errors)},
        )

    def get_abbreviation_entries(self) -> tuple[list[tuple[str, str]], list[str]]:
        if not hasattr(self, "abbreviations_text"):
            return [], []
        return parse_abbreviations_csv(self.get_text(self.abbreviations_text))

    def apply_abbreviations_to_lmstudio_result(self, text: str, result_label: str) -> str:
        entries, errors = self.get_abbreviation_entries()
        if errors:
            self.log_debug(
                "warning",
                "app",
                "abbreviations_parse_warning",
                "Certaines abréviations ont été ignorées pendant le post-traitement local.",
                {"errors": errors[:8], "errors_count": len(errors), "result": result_label},
            )

        if not entries or not text:
            self.update_abbreviations_status(entries=entries, errors=errors)
            return text

        transformed, count = apply_safe_abbreviation_substitutions_to_text(text, entries)
        if count > 0:
            self.abbreviations_status_var.set(
                f"Abréviations: {len(entries)} règle(s), {count} substitution(s) sur {result_label}"
            )
            self.log_debug(
                "info",
                "app",
                "abbreviations_result_postprocess",
                "Substitutions contrôlées appliquées au résultat LM Studio.",
                {"count": count, "result": result_label},
            )
        else:
            self.update_abbreviations_status(entries=entries, errors=errors)

        return transformed

    def result_source_key_for_document(self, document_index: int) -> str:
        if document_index == 2:
            return "result_2"
        if document_index == 3:
            return "result_3"
        return "result_1"

    def remember_weda_result_payload(self, source: str, text: str) -> RichTextPayload:
        payload = format_weda_rich_text(text)
        self.rich_result_payloads[source] = payload
        self.generated_result_originals[source] = payload.text
        binding = self.pending_result_patient_bindings.pop(source, None) or self.capture_current_patient_binding()
        self.result_patient_bindings[source] = binding
        return payload

    def capture_current_patient_binding(self) -> dict:
        context = self.context_manager.get_latest()
        return {
            "patient_id": normalize_patient_id(getattr(context, "patient_id", "")) if context else "",
            "patient_identity": str(getattr(context, "patient_identity", "") or "") if context else "",
            "context_received_at": str(getattr(context, "received_at", "") or "") if context else "",
            "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }

    def capture_pending_result_patient_binding(self, source: str) -> None:
        self.pending_result_patient_bindings[source] = self.capture_current_patient_binding()

    def discard_pending_result_patient_binding(self, source: str) -> None:
        self.pending_result_patient_bindings.pop(source, None)

    def get_result_text_by_source(self, source: str) -> str:
        if source == "result_2":
            return self.get_text(self.secondary_result_text).strip()
        if source == "result_3":
            return self.get_text(self.tertiary_result_text).strip() if hasattr(self, "tertiary_result_text") else ""
        if source == "document_now":
            return self.get_text(self.document_now_result_text).strip() if hasattr(self, "document_now_result_text") else ""
        return self.get_text(self.result_text).strip()

    def get_current_rich_result_payload(self, source: str) -> RichTextPayload:
        text = self.get_result_text_by_source(source)
        remembered = self.rich_result_payloads.get(source)
        if remembered and remembered.text.strip() == text.strip():
            return remembered
        return format_weda_rich_text(text)

    def get_result_payload_for_import(self, source: str = "result_1") -> RichTextPayload:
        if source == "result_1_result_2":
            return combine_weda_rich_text_payloads([
                self.get_current_rich_result_payload("result_1"),
                self.get_current_rich_result_payload("result_2"),
            ])
        if source == "result_1_result_2_result_3":
            return combine_weda_rich_text_payloads([
                self.get_current_rich_result_payload("result_1"),
                self.get_current_rich_result_payload("result_2"),
                self.get_current_rich_result_payload("result_3"),
            ])
        return self.get_current_rich_result_payload(source)

    def copy_rich_result_source(self, source: str) -> bool:
        widget = self.get_result_widget_by_source(source)
        if widget is not None:
            payload = self.get_rich_text_widget_payload(widget, source=source)
        else:
            payload = self.get_current_rich_result_payload(source)
        return copy_rich_text_to_clipboard(payload.html, payload.text, self.root)

    def get_result_widget_by_source(self, source: str) -> tk.Text | None:
        if source == "result_2":
            return self.secondary_result_text if hasattr(self, "secondary_result_text") else None
        if source == "result_3":
            return self.tertiary_result_text if hasattr(self, "tertiary_result_text") else None
        if source == "document_now":
            return self.document_now_result_text if hasattr(self, "document_now_result_text") else None
        if source == "result_1":
            return self.result_text if hasattr(self, "result_text") else None
        return None

    def install_rich_result_copy_bindings(self) -> None:
        for source in ("result_1", "result_2", "result_3", "document_now"):
            widget = self.get_result_widget_by_source(source)
            if widget is None:
                continue

            self.configure_rich_result_tags(widget)
            for sequence in ("<<Copy>>", "<Control-c>", "<Control-C>"):
                widget.bind(sequence, lambda event, key=source: self.on_rich_result_copy(event, key))

    def configure_rich_result_tags(self, widget: tk.Text) -> None:
        widget.tag_configure(RICH_RESULT_BOLD_TAG, font=("Segoe UI", 10, "bold"))
        widget.tag_configure(RICH_RESULT_UNDERLINE_TAG, underline=True)
        widget.tag_configure(RICH_RESULT_ITALIC_TAG, font=("Segoe UI", 10, "italic"))
        widget.tag_configure(RICH_RESULT_STRIKE_TAG, overstrike=True)

    def set_rich_result_text(self, widget: tk.Text, payload: RichTextPayload, *, source: str = "") -> None:
        state = str(widget.cget("state"))
        if state == tk.DISABLED:
            widget.configure(state=tk.NORMAL)

        self.configure_rich_result_tags(widget)
        widget.delete("1.0", tk.END)
        for segment_text, tag_names in self.parse_rich_payload_for_tk(payload):
            start = widget.index(tk.INSERT)
            widget.insert(tk.INSERT, segment_text)
            end = widget.index(tk.INSERT)
            for tag_name in tag_names:
                widget.tag_add(tag_name, start, end)

        if state == tk.DISABLED:
            widget.configure(state=tk.DISABLED)

        if source:
            self.rich_result_payloads[source] = payload
        self.schedule_text_widget_dependents(widget)

    def parse_rich_payload_for_tk(self, payload: RichTextPayload) -> list[tuple[str, tuple[str, ...]]]:
        fragment = payload.html or ""
        if fragment:
            parser = RichHtmlToTkParser()
            try:
                parser.feed(fragment)
                parser.close()
            except Exception:
                return [(payload.text or "", ())]
            if parser.segments:
                return parser.segments

        return [(payload.text or "", ())]

    def on_rich_result_copy(self, event, source: str):
        widget = event.widget if isinstance(event.widget, tk.Text) else self.get_result_widget_by_source(source)
        if widget is None:
            return "break"

        payload = self.get_rich_text_widget_payload(widget, source=source, prefer_selection=True)
        ok = copy_rich_text_to_clipboard(payload.html, payload.text, self.root)
        self.set_rich_copy_status(source, ok)
        return "break"

    def get_rich_text_widget_payload(
        self,
        widget: tk.Text,
        *,
        source: str = "",
        prefer_selection: bool = False,
    ) -> RichTextPayload:
        selected_range = self.get_text_selection_range(widget) if prefer_selection else None
        if selected_range is not None:
            start, end = selected_range
        else:
            start, end = "1.0", "end-1c"

        text = widget.get(start, end)
        if not text:
            return RichTextPayload(text="", html="")

        if self.range_has_rich_result_tags(widget, start, end):
            return RichTextPayload(
                text=text,
                html=self.serialize_rich_text_widget_range(widget, start, end),
            )

        if not selected_range and source:
            remembered = self.rich_result_payloads.get(source)
            if remembered and remembered.text.strip() == text.strip():
                return remembered

        return format_weda_rich_text(text)

    def get_text_selection_range(self, widget: tk.Text) -> tuple[str, str] | None:
        try:
            return widget.index("sel.first"), widget.index("sel.last")
        except tk.TclError:
            return None

    def range_has_rich_result_tags(self, widget: tk.Text, start: str, end: str) -> bool:
        if any(tag_name in widget.tag_names(start) for tag_name in RICH_RESULT_TK_TAGS):
            return True

        try:
            return any(
                event_type in ("tagon", "tagoff") and tag_name in RICH_RESULT_TK_TAGS
                for event_type, tag_name, _index in widget.dump(start, end, tag=True)
            )
        except tk.TclError:
            return False

    def serialize_rich_text_widget_range(self, widget: tk.Text, start: str, end: str) -> str:
        active_tags = set(tag_name for tag_name in widget.tag_names(start) if tag_name in RICH_RESULT_TK_TAGS)
        fragments: list[str] = []

        try:
            dump = widget.dump(start, end, text=True, tag=True)
        except tk.TclError:
            dump = []

        for event_type, value, _index in dump:
            if event_type == "tagon" and value in RICH_RESULT_TK_TAGS:
                active_tags.add(value)
            elif event_type == "tagoff" and value in RICH_RESULT_TK_TAGS:
                active_tags.discard(value)
            elif event_type == "text":
                fragments.append(self.wrap_rich_html_text(value, active_tags))

        return "".join(fragments)

    def wrap_rich_html_text(self, value: str, active_tags: set[str]) -> str:
        fragment = html.escape(value, quote=False).replace("\n", "<br>")
        for tag_name, html_tag in reversed(RICH_RESULT_TK_TAG_TO_HTML):
            if tag_name in active_tags:
                fragment = f"<{html_tag}>{fragment}</{html_tag}>"
        return fragment

    def set_rich_copy_status(self, source: str, ok: bool) -> None:
        if source == "result_2":
            self.secondary_status_var.set("Résultat 2 WEDA copié" if ok else "Copie Résultat 2 impossible")
        elif source == "result_3":
            self.tertiary_status_var.set("Résultat 3 WEDA copié" if ok else "Copie Résultat 3 impossible")
        elif source == "document_now":
            self.document_now_status_var.set(
                "Document maintenant: résultat WEDA copié" if ok else "Document maintenant: copie impossible"
            )
        else:
            self.import_status_var.set("Résultat WEDA copié" if ok else "Copie impossible")

    def update_abbreviations_status(
        self,
        *,
        entries: list[tuple[str, str]] | None = None,
        errors: list[str] | None = None,
    ) -> None:
        if entries is None or errors is None:
            entries, errors = self.get_abbreviation_entries()
        suffix = f", {len(errors)} erreur(s)" if errors else ""
        self.abbreviations_status_var.set(f"Abréviations: {len(entries)} règle(s), post-traitement local{suffix}")

    def apply_safe_abbreviations_to_transcription(self) -> None:
        entries, errors = self.get_abbreviation_entries()
        if not entries:
            messagebox.showwarning("Abréviations", "Aucune règle d’abréviation valide.", parent=self.root)
            return
        source = self.get_text(self.transcription_text)
        transformed, count = apply_safe_abbreviation_substitutions_to_text(source, entries)
        if count <= 0:
            self.abbreviations_status_var.set(f"Abréviations: {len(entries)} règle(s), aucune substitution")
            messagebox.showinfo("Abréviations", "Aucune substitution sûre trouvée dans la transcription.", parent=self.root)
            return
        if not messagebox.askyesno(
            "Abréviations",
            f"Appliquer {count} substitution(s) contrôlée(s) dans la transcription ?",
            parent=self.root,
        ):
            return
        self.set_text(self.transcription_text, transformed)
        self.update_abbreviations_status(entries=entries, errors=errors)
        self.log_debug(
            "info",
            "app",
            "abbreviations_safe_postprocess",
            "Substitutions contrôlées appliquées à la transcription.",
            {"count": count},
        )

    def add_message_attachment_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Charger des fichiers pour Gemma",
            filetypes=[
                ("Documents lisibles", "*.pdf *.txt *.md *.csv *.json *.xml *.log *.rtf"),
                ("PDF", "*.pdf"),
                ("Textes", "*.txt *.md *.csv *.json *.xml *.log *.rtf"),
                ("Tous les fichiers", "*.*"),
            ],
        )
        if not paths:
            return

        existing_paths = {item.get("path") for item in self.message_attachments}
        loaded = 0
        errors = []
        for raw_path in paths:
            path = Path(raw_path)
            if str(path) in existing_paths:
                continue
            try:
                attachment = read_message_attachment_file(path)
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")
                continue
            self.message_attachments.append(attachment)
            existing_paths.add(str(path))
            loaded += 1

        self.update_message_attachment_status()
        if loaded:
            self.schedule_message_refresh()
            self.schedule_secondary_message_refresh()
            self.schedule_tertiary_message_refresh()
            self.schedule_document_now_message_refresh()
            self.log_debug(
                "info",
                "app",
                "message_attachments_loaded",
                "Fichiers chargés pour le message Gemma.",
                {
                    "loaded": loaded,
                    "total": len(self.message_attachments),
                    "names": [item.get("name") for item in self.message_attachments[-loaded:]],
                },
            )

        if errors:
            preview = "\n".join(errors[:8])
            if len(errors) > 8:
                preview += f"\n... +{len(errors) - 8} erreur(s)"
            messagebox.showwarning("Fichiers", "Certains fichiers n’ont pas pu être chargés.\n\n" + preview, parent=self.root)
        elif loaded:
            self.lmstudio_status_var.set(f"Fichiers chargés pour Gemma: {len(self.message_attachments)}")

    def clear_message_attachments(self) -> None:
        if not self.message_attachments:
            self.update_message_attachment_status()
            return
        self.message_attachments.clear()
        self.update_message_attachment_status()
        self.schedule_message_refresh()
        self.schedule_secondary_message_refresh()
        self.schedule_tertiary_message_refresh()
        self.schedule_document_now_message_refresh()
        self.lmstudio_status_var.set("Fichiers retirés du message Gemma")

    def update_message_attachment_status(self) -> None:
        if not self.message_attachments:
            self.message_attachment_status_var.set("Fichiers: aucun")
            return
        total_chars = sum(int(item.get("chars") or 0) for item in self.message_attachments)
        self.message_attachment_status_var.set(f"Fichiers: {len(self.message_attachments)} ({total_chars} car.)")

    def get_message_attachments_prompt_text(self) -> str:
        if not self.message_attachments:
            return ""

        parts = []
        used_chars = 0
        for index, item in enumerate(self.message_attachments, start=1):
            text = str(item.get("text") or "").strip()
            if not text:
                continue

            remaining = MESSAGE_ATTACHMENT_MAX_TOTAL_CHARS - used_chars
            if remaining <= 0:
                parts.append("[... autres fichiers ignorés : limite totale atteinte ...]")
                break

            truncated_for_total = len(text) > remaining
            body = text[:remaining].rstrip() if truncated_for_total else text
            used_chars += len(body)
            truncation_note = " ; tronqué" if item.get("truncated") or truncated_for_total else ""
            parts.append(
                f"Fichier {index}: {item.get('name', 'fichier')} ({item.get('kind', 'texte')}{truncation_note})\n{body}"
            )

            if truncated_for_total:
                parts.append("[... contenu tronqué : limite totale des fichiers atteinte ...]")
                break

        return "\n\n---\n\n".join(part for part in parts if part).strip()

    def append_message_attachment_section(self, prompt_content: str, message: str, variables: dict[str, str]) -> str:
        attachments = str(variables.get("attachments") or "").strip()
        if not attachments or self.prompt_contains_variable(prompt_content, "attachments") or self.prompt_contains_variable(prompt_content, "uploaded_files"):
            return message.strip()
        block = "FICHIERS CHARGÉS :\n" + attachments
        if not message.strip():
            return block
        return (message.rstrip() + "\n\n---\n" + block).strip()

    def build_prompt_variables(self) -> dict[str, str]:
        context = self.context_manager.get_latest()
        include_prompt = bool(self.include_prompt_var.get())
        include_context = bool(self.include_context_var.get())
        include_transcription = bool(self.include_transcription_var.get())
        include_context_metadata = include_prompt or include_context
        weda_context = self.get_text(self.context_text).strip() if include_context else ""
        transcription = self.get_clean_transcription_text() if include_transcription else ""
        attachments = self.get_message_attachments_prompt_text()
        return {
            "transcription": transcription,
            "weda_context": weda_context,
            "abbreviations": "",
            "attachments": attachments,
            "uploaded_files": attachments,
            "patient_identity": context.patient_identity if context and include_context_metadata else "",
            "patient_age": context.patient_age if context and include_context_metadata else "",
            "patient_sex": context.patient_sex if context and include_context_metadata else "",
            "antecedents": "",
            "treatments": "",
            "allergies": "",
            "current_date": date.today().strftime("%d/%m/%Y") if include_prompt or include_context else "",
            "doctor_name": "",
            "result_1": self.get_text(self.result_text).strip() if hasattr(self, "result_text") else "",
            "result_2": self.get_text(self.secondary_result_text).strip() if hasattr(self, "secondary_result_text") else "",
            "result_3": self.get_text(self.tertiary_result_text).strip() if hasattr(self, "tertiary_result_text") else "",
            "document_now_result": (
                self.get_text(self.document_now_result_text).strip()
                if hasattr(self, "document_now_result_text")
                else ""
            ),
            "lmstudio_result": self.get_text(self.result_text).strip() if hasattr(self, "result_text") else "",
            "pdf_fields": "",
            "pdf_schema": "",
        }

    def prompt_contains_variable(self, prompt_content: str, variable_name: str) -> bool:
        pattern = r"{{\s*" + re.escape(variable_name) + r"\s*}}"
        return re.search(pattern, prompt_content or "", flags=re.IGNORECASE) is not None

    def append_missing_source_sections(self, prompt_content: str, message: str, variables: dict[str, str]) -> str:
        sections = []

        if not self.prompt_contains_variable(prompt_content, "current_date"):
            sections.append(("DATE DE CONSULTATION", variables.get("current_date", "")))

        if not self.prompt_contains_variable(prompt_content, "patient_identity"):
            patient_lines = [
                variables.get("patient_identity", ""),
                f"Âge : {variables.get('patient_age', '')}" if variables.get("patient_age") else "",
                f"Sexe : {variables.get('patient_sex', '')}" if variables.get("patient_sex") else "",
            ]
            patient_text = "\n".join(line for line in patient_lines if line)
            if patient_text:
                sections.append(("PATIENT", patient_text))

        if not self.prompt_contains_variable(prompt_content, "weda_context") and variables.get("weda_context"):
            sections.append((
                "CONTEXTE WEDA (consultations récentes et données médicales du dossier)",
                variables["weda_context"],
            ))

        if not self.prompt_contains_variable(prompt_content, "transcription") and variables.get("transcription"):
            sections.append(("TRANSCRIPTION DU JOUR (source principale de l’oral)", variables["transcription"]))

        if not sections:
            return message

        source_block = "\n\n".join(f"{title} :\n{content}" for title, content in sections if content)
        if not source_block:
            return message

        if not self.include_prompt_var.get():
            return source_block.strip()

        return (
            message.rstrip()
            + "\n\n---\nDONNÉES CLINIQUES À UTILISER AVEC HIÉRARCHIE\n\n"
            + SOURCE_USAGE_GUIDANCE
            + "\n\n"
            + source_block
        ).strip()

    def preview_message(self) -> str:
        message, variables = self.build_lmstudio_message()
        self.set_text(self.sent_message_text, message, readonly=True)
        self.select_tab_containing_widget(self.sent_message_text)
        self.log_debug(
            "info",
            "app",
            "message_previewed",
            "Message LM Studio prévisualisé.",
            {
                "prompt_name": self.prompt_var.get(),
                "message_length": len(message),
                "transcription_length": len(variables.get("transcription") or ""),
                "weda_context_length": len(variables.get("weda_context") or ""),
            },
        )
        return message

    def preview_secondary_message(self) -> str:
        try:
            message, variables = self.build_secondary_lmstudio_message()
        except Exception as exc:
            messagebox.showwarning("Prompt 2", str(exc), parent=self.root)
            self.refresh_secondary_sent_message()
            self.select_tab_containing_widget(self.secondary_sent_message_text)
            return ""
        self.set_text(self.secondary_sent_message_text, message, readonly=True)
        self.select_tab_containing_widget(self.secondary_sent_message_text)
        self.log_debug(
            "info",
            "app",
            "secondary_message_previewed",
            "Message Prompt 2 prévisualisé.",
            {
                "prompt_2_name": self.secondary_prompt_var.get(),
                "message_length": len(message),
                "result_1_length": len(variables.get("result_1") or ""),
            },
        )
        return message

    def preview_tertiary_message(self) -> str:
        try:
            message, variables = self.build_tertiary_lmstudio_message()
        except Exception as exc:
            messagebox.showwarning("Prompt 3", str(exc), parent=self.root)
            self.refresh_tertiary_sent_message()
            self.select_tab_containing_widget(self.tertiary_sent_message_text)
            return ""
        self.set_text(self.tertiary_sent_message_text, message, readonly=True)
        self.select_tab_containing_widget(self.tertiary_sent_message_text)
        self.log_debug(
            "info",
            "app",
            "tertiary_message_previewed",
            "Message Prompt 3 prévisualisé.",
            {
                "prompt_3_name": self.tertiary_prompt_var.get(),
                "message_length": len(message),
                "result_1_length": len(variables.get("result_1") or ""),
                "result_2_length": len(variables.get("result_2") or ""),
            },
        )
        return message

    def build_lmstudio_client(self, *, max_tokens: int | None = None) -> LmStudioClient:
        lm_config = self.config.get("lmstudio", {})
        configured_max_tokens = max_tokens if max_tokens is not None else lm_config.get("max_tokens")
        return LmStudioClient(
            str(lm_config.get("url") or "http://localhost:1234/v1/chat/completions"),
            model=str(lm_config.get("model") or "local-model"),
            temperature=float(lm_config.get("temperature") or 0.2),
            timeout_seconds=int(lm_config.get("timeout_seconds") or 120),
            system_prompt=str(lm_config.get("default_system_prompt") or "Tu es un assistant médical local."),
            max_tokens=int(configured_max_tokens) if configured_max_tokens else None,
        )

    def refresh_lmstudio_context_window_async(self) -> None:
        lm_config = self.config.get("lmstudio", {})
        url = str(lm_config.get("url") or "http://localhost:1234/v1/chat/completions")
        model = str(lm_config.get("model") or "local-model")
        timeout_seconds = min(8, max(1, int(lm_config.get("timeout_seconds") or 120)))

        def worker():
            try:
                context = fetch_lmstudio_model_context(url, model=model, timeout_seconds=timeout_seconds)
                self.root.after(0, self.on_lmstudio_context_window_detected, context)
            except Exception as exc:
                self.root.after(0, self.on_lmstudio_context_window_error, exc)

        threading.Thread(target=worker, name="lmstudio-context-detect", daemon=True).start()

    def on_lmstudio_context_window_detected(self, context) -> None:
        if not context or not getattr(context, "context_length", 0):
            self.log_debug("warning", "app", "lmstudio_context_window_missing", "Fenêtre de contexte LM Studio non détectée.")
            return

        self.lmstudio_context_window_tokens = int(context.context_length)
        self.lmstudio_context_window_model = str(context.model or "")
        self.lmstudio_context_window_source = str(context.source or "")
        self.lmstudio_status_var.set(f"LM Studio: contexte {self.lmstudio_context_window_tokens} tokens")
        self.log_debug(
            "info",
            "app",
            "lmstudio_context_window_detected",
            "Fenêtre de contexte LM Studio détectée.",
            {
                "model": self.lmstudio_context_window_model,
                "context_length": self.lmstudio_context_window_tokens,
                "max_context_length": getattr(context, "max_context_length", None),
                "source": self.lmstudio_context_window_source,
                "models_url": getattr(context, "models_url", ""),
            },
        )

    def on_lmstudio_context_window_error(self, error: Exception) -> None:
        self.lmstudio_context_window_tokens = 0
        self.lmstudio_context_window_model = ""
        self.lmstudio_context_window_source = ""
        self.log_debug("warning", "app", "lmstudio_context_window_error", str(error))

    def get_lmstudio_context_window_tokens(self) -> int:
        if self.lmstudio_context_window_tokens > 0:
            return self.lmstudio_context_window_tokens
        lm_config = self.config.get("lmstudio", {})
        for key in ("context_window_tokens", "context_window_fallback_tokens"):
            try:
                value = int(lm_config.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                return value
        return 0

    def estimate_lmstudio_tokens(self, text: str) -> int:
        lm_config = self.config.get("lmstudio", {})
        try:
            chars_per_token = float(lm_config.get("context_estimated_chars_per_token") or LMSTUDIO_CONTEXT_ESTIMATED_CHARS_PER_TOKEN)
        except (TypeError, ValueError):
            chars_per_token = LMSTUDIO_CONTEXT_ESTIMATED_CHARS_PER_TOKEN
        chars_per_token = max(1.5, min(chars_per_token, 8.0))
        return int((len(text or "") / chars_per_token) + 0.999)

    def get_lmstudio_input_budget_tokens(self, *, max_tokens: int | None = None) -> int:
        context_tokens = self.get_lmstudio_context_window_tokens()
        if context_tokens <= 0:
            return 0

        lm_config = self.config.get("lmstudio", {})
        try:
            margin_tokens = int(lm_config.get("context_safety_margin_tokens") or LMSTUDIO_CONTEXT_SAFETY_MARGIN_TOKENS)
        except (TypeError, ValueError):
            margin_tokens = LMSTUDIO_CONTEXT_SAFETY_MARGIN_TOKENS
        try:
            reserve_tokens = int(
                max_tokens
                or lm_config.get("context_response_reserve_tokens")
                or lm_config.get("max_tokens")
                or LMSTUDIO_CONTEXT_RESPONSE_RESERVE_TOKENS
            )
        except (TypeError, ValueError):
            reserve_tokens = LMSTUDIO_CONTEXT_RESPONSE_RESERVE_TOKENS

        margin_tokens = max(128, min(margin_tokens, max(128, context_tokens // 4)))
        reserve_tokens = max(256, min(reserve_tokens, max(256, context_tokens // 3)))
        system_tokens = self.estimate_lmstudio_tokens(str(lm_config.get("default_system_prompt") or "Tu es un assistant médical local."))
        return max(LMSTUDIO_CONTEXT_MIN_INPUT_TOKENS, context_tokens - margin_tokens - reserve_tokens - system_tokens)

    def truncate_lmstudio_text_tail(self, text: str, excess_tokens: int) -> str:
        value = str(text or "")
        if not value:
            return ""
        lm_config = self.config.get("lmstudio", {})
        try:
            chars_per_token = float(lm_config.get("context_estimated_chars_per_token") or LMSTUDIO_CONTEXT_ESTIMATED_CHARS_PER_TOKEN)
        except (TypeError, ValueError):
            chars_per_token = LMSTUDIO_CONTEXT_ESTIMATED_CHARS_PER_TOKEN
        marker = "\n\n[... contenu ancien tronqué pour respecter la fenêtre de contexte LM Studio ...]"
        chars_to_remove = max(256, int(max(1, excess_tokens) * max(1.5, min(chars_per_token, 8.0))) + len(marker) + 64)
        keep_chars = max(0, len(value) - chars_to_remove)
        if keep_chars < 160:
            return ""
        return value[:keep_chars].rstrip() + marker

    def apply_lmstudio_context_limit(
        self,
        prompt_content: str,
        variables: dict[str, str],
        render_message,
        *,
        label: str,
        max_tokens: int | None = None,
    ) -> tuple[str, dict[str, str]]:
        working_variables = dict(variables)
        message = render_message(working_variables).strip()
        budget_tokens = self.get_lmstudio_input_budget_tokens(max_tokens=max_tokens)
        if budget_tokens <= 0:
            return message, working_variables

        token_count = self.estimate_lmstudio_tokens(message)
        if token_count <= budget_tokens:
            return message, working_variables

        alias_groups = [
            ("weda_context",),
            ("attachments", "uploaded_files"),
            ("result_1", "lmstudio_result"),
            ("result_2",),
            ("result_3",),
            ("document_now_result",),
            ("transcription", "snapshot_transcription", "snapshot_de_transcription"),
        ]
        truncated_keys = []

        for aliases in alias_groups:
            values = [str(working_variables.get(alias) or "") for alias in aliases]
            current_value = next((value for value in values if value), "")
            if not current_value:
                continue

            for _attempt in range(6):
                excess_tokens = max(1, token_count - budget_tokens)
                next_value = self.truncate_lmstudio_text_tail(current_value, excess_tokens)
                if next_value == current_value:
                    next_value = ""
                for alias in aliases:
                    if working_variables.get(alias):
                        working_variables[alias] = next_value
                truncated_keys.extend(alias for alias in aliases if alias not in truncated_keys)
                message = render_message(working_variables).strip()
                token_count = self.estimate_lmstudio_tokens(message)
                current_value = next_value
                if token_count <= budget_tokens or not current_value:
                    break

            if token_count <= budget_tokens:
                break

        if token_count > budget_tokens:
            message = self.truncate_lmstudio_text_tail(message, token_count - budget_tokens).strip()
            truncated_keys.append("_message_final")
            token_count = self.estimate_lmstudio_tokens(message)

        self.log_debug(
            "warning",
            "app",
            "lmstudio_message_context_truncated",
            "Message LM Studio tronqué pour respecter la fenêtre de contexte.",
            {
                "label": label,
                "context_window_tokens": self.get_lmstudio_context_window_tokens(),
                "budget_tokens": budget_tokens,
                "estimated_tokens_after": token_count,
                "truncated_keys": truncated_keys,
                "prompt_mentions_weda_context": self.prompt_contains_variable(prompt_content, "weda_context"),
            },
        )
        if truncated_keys:
            self.lmstudio_status_var.set(f"LM Studio: contexte tronqué ({token_count}/{budget_tokens} tokens estimés)")
        return message, working_variables

    def adjust_lmstudio_client_for_context(self, client: LmStudioClient, message: str, *, label: str = "") -> None:
        context_tokens = self.get_lmstudio_context_window_tokens()
        if context_tokens <= 0:
            return

        lm_config = self.config.get("lmstudio", {})
        try:
            margin_tokens = int(lm_config.get("context_safety_margin_tokens") or LMSTUDIO_CONTEXT_SAFETY_MARGIN_TOKENS)
        except (TypeError, ValueError):
            margin_tokens = LMSTUDIO_CONTEXT_SAFETY_MARGIN_TOKENS
        input_tokens = self.estimate_lmstudio_tokens(str(client.system_prompt or "") + "\n" + str(message or ""))
        available_output_tokens = context_tokens - input_tokens - max(128, margin_tokens)
        if available_output_tokens <= 0:
            client.max_tokens = 128
            return
        if client.max_tokens and client.max_tokens > available_output_tokens:
            previous = client.max_tokens
            client.max_tokens = max(128, int(available_output_tokens))
            self.log_debug(
                "warning",
                "app",
                "lmstudio_max_tokens_capped",
                "max_tokens LM Studio ajusté à la fenêtre de contexte.",
                {
                    "label": label,
                    "previous_max_tokens": previous,
                    "effective_max_tokens": client.max_tokens,
                    "context_window_tokens": context_tokens,
                    "estimated_input_tokens": input_tokens,
                },
            )

    def is_secondary_auto_run_enabled(self) -> bool:
        secondary_config = normalize_secondary_analysis_config(self.config.get("secondary_analysis", {}))
        return bool(self.secondary_enabled_var.get() and secondary_config.get("auto_run_after_primary", True))

    def is_tertiary_auto_run_enabled(self) -> bool:
        tertiary_config = normalize_tertiary_analysis_config(self.config.get("tertiary_analysis", {}))
        return bool(self.tertiary_enabled_var.get() and tertiary_config.get("auto_run_after_secondary", True))

    def send_to_lmstudio(self) -> None:
        session = self.pending_dictation_session()
        if session:
            self.send_to_lmstudio_after_dictation_flush(session)
            return
        self.send_current_message_to_lmstudio()

    def send_to_lmstudio_after_dictation_flush(self, session) -> None:
        session_was_recording = bool(session and session.is_running())
        if session_was_recording:
            self.stop_dictation()

        self.lmstudio_status_var.set("LM Studio: attente transcription complète")
        self.transcription_status_var.set("Transcription: finalisation avant LM Studio")
        self.set_dictation_buttons_waiting()
        self.start_lmstudio_spinner(LMSTUDIO_MAIN_SPINNER_KEY)
        self.start_lmstudio_spinner(LMSTUDIO_RESULT_RETRY_SPINNER_KEY)
        self.log_debug(
            "info",
            "app",
            "lmstudio_waiting_transcription_flush",
            "Envoi LM Studio différé jusqu’à la fin complète de la transcription.",
            {"session_was_recording": session_was_recording},
        )

        def worker():
            try:
                self.wait_for_dictation_transcription(session)
                def ui_send_after_flush():
                    self.set_dictation_buttons_running(False)
                    self.send_current_message_to_lmstudio()

                self.call_ui_sync(ui_send_after_flush, timeout_seconds=20)
            except Exception as exc:
                def ui_error_after_flush(error=exc):
                    self.set_dictation_buttons_running(False)
                    self.on_lmstudio_error(error)

                self.root.after(0, ui_error_after_flush)

        threading.Thread(target=worker, name="lmstudio-after-dictation-flush", daemon=True).start()

    def send_current_message_to_lmstudio(self) -> None:
        if self.is_lmstudio_request_active("document_1"):
            self.lmstudio_status_var.set("LM Studio: Document 1 déjà en cours")
            return
        if self.include_context_var.get() and not self.require_fresh_patient_context("Génération du Document 1"):
            return
        message = self.refresh_sent_message().strip()
        if not message:
            self.stop_lmstudio_spinner(LMSTUDIO_MAIN_SPINNER_KEY)
            self.stop_lmstudio_spinner(LMSTUDIO_RESULT_RETRY_SPINNER_KEY)
            messagebox.showwarning("LM Studio", "Le message à envoyer est vide.", parent=self.root)
            return

        lm_config = self.config.get("lmstudio", {})
        client = self.build_lmstudio_client()
        self.adjust_lmstudio_client_for_context(client, message, label="message_principal")
        self.lmstudio_status_var.set("LM Studio: envoi en cours")
        self.start_lmstudio_spinner(LMSTUDIO_MAIN_SPINNER_KEY)
        self.start_lmstudio_spinner(LMSTUDIO_RESULT_RETRY_SPINNER_KEY)
        if self.secondary_enabled_var.get():
            self.set_text(self.secondary_result_text, "")
            self.set_text(self.secondary_sent_message_text, "", readonly=True)
            self.secondary_status_var.set("Prompt 2: en attente du Résultat 1")
        if self.tertiary_enabled_var.get():
            self.set_text(self.tertiary_result_text, "")
            self.set_text(self.tertiary_sent_message_text, "", readonly=True)
            self.tertiary_status_var.set("Prompt 3: en attente du Résultat 2")
        self.log_debug(
            "info",
            "app",
            "lmstudio_request_started",
            "Envoi à LM Studio.",
            {
                "url": str(lm_config.get("url") or "http://localhost:1234/v1/chat/completions"),
                "model": str(lm_config.get("model") or "local-model"),
                "message_length": len(message),
            },
        )

        self.launch_lmstudio_request(
            "document_1",
            client,
            message,
            on_success=lambda response: self.on_lmstudio_response(response, message),
            on_error=self.on_lmstudio_error,
            thread_name="lmstudio-request",
            result_source="result_1",
        )

    def on_lmstudio_response(self, response, sent_message: str) -> None:
        self.stop_lmstudio_spinner(LMSTUDIO_MAIN_SPINNER_KEY)
        self.stop_lmstudio_spinner(LMSTUDIO_RESULT_RETRY_SPINNER_KEY)
        result_text = self.apply_abbreviations_to_lmstudio_result(response.text, "Résultat 1")
        result_payload = self.remember_weda_result_payload("result_1", result_text)
        self.record_generation_metric(
            "document_1",
            "result_1",
            status="success",
            elapsed_seconds=response.elapsed_seconds,
            input_chars=len(sent_message or ""),
            result_chars=len(result_payload.text or ""),
        )
        self.set_rich_result_text(self.result_text, result_payload, source="result_1")
        self.select_tab_containing_widget(self.result_text)
        self.lmstudio_status_var.set(f"LM Studio: réponse reçue en {response.elapsed_seconds:.1f}s")
        self.log_debug(
            "info",
            "app",
            "lmstudio_response",
            "Réponse LM Studio reçue.",
            {
                "elapsed_seconds": response.elapsed_seconds,
                "raw_result_length": len(response.text or ""),
                "result_length": len(result_payload.text or ""),
                "result_html_length": len(result_payload.html or ""),
            },
        )
        if self.is_secondary_auto_run_enabled():
            self.run_secondary_analysis(
                trigger="auto",
                primary_sent_message=sent_message,
                primary_result=result_payload.text,
            )
            return

        status = "disabled" if not self.secondary_enabled_var.get() else "skipped_no_result_1"
        self.append_analysis_history(
            sent_message_1=sent_message,
            result_1=result_payload.text,
            prompt_2_status=status,
            prompt_3_status="skipped_no_result_2" if self.tertiary_enabled_var.get() else "disabled",
        )

    def append_analysis_history(
        self,
        *,
        sent_message_1: str,
        result_1: str,
        prompt_2_status: str,
        message_sent_2: str = "",
        result_2: str = "",
        prompt_2_error: str = "",
        prompt_3_status: str = "",
        message_sent_3: str = "",
        result_3: str = "",
        prompt_3_error: str = "",
    ) -> None:
        prompt_1 = self.prompt_manager.get(self.current_prompt_id())
        prompt_2 = self.prompt_manager.get(self.current_secondary_prompt_id())
        prompt_3 = self.prompt_manager.get(self.current_tertiary_prompt_id())
        self.history_manager.append(
            {
                **self.current_stt_history_payload(),
                "whisper_model": self.model_manager.active_label(),
                "prompt_1_id": prompt_1.id if prompt_1 else self.current_prompt_id(),
                "prompt_1_name": prompt_1.name if prompt_1 else self.prompt_var.get(),
                "message_sent_1": sent_message_1,
                "result_1": result_1,
                "prompt_2_enabled": bool(self.secondary_enabled_var.get()),
                "prompt_2_id": prompt_2.id if prompt_2 else self.current_secondary_prompt_id(),
                "prompt_2_name": prompt_2.name if prompt_2 else self.secondary_prompt_var.get(),
                "message_sent_2": message_sent_2,
                "result_2": result_2,
                "prompt_2_status": prompt_2_status,
                "prompt_2_error": prompt_2_error,
                "prompt_3_enabled": bool(self.tertiary_enabled_var.get()),
                "prompt_3_id": prompt_3.id if prompt_3 else self.current_tertiary_prompt_id(),
                "prompt_3_name": prompt_3.name if prompt_3 else self.tertiary_prompt_var.get(),
                "message_sent_3": message_sent_3,
                "result_3": result_3,
                "prompt_3_status": prompt_3_status or ("disabled" if not self.tertiary_enabled_var.get() else ""),
                "prompt_3_error": prompt_3_error,
                "prompt_name": self.prompt_var.get(),
                "transcription": self.get_clean_transcription_text(),
                "weda_context": self.get_text(self.context_text),
                "sent_message": sent_message_1,
                "lmstudio_result": result_1,
                "status": "lmstudio_response",
            }
        )

    def run_secondary_analysis_manual(self) -> None:
        self.run_secondary_analysis(trigger="manual_run")

    def run_secondary_analysis(
        self,
        *,
        trigger: str = "manual_run",
        primary_sent_message: str | None = None,
        primary_result: str | None = None,
    ) -> None:
        if self.secondary_running:
            self.secondary_status_var.set("Prompt 2: déjà en cours")
            return
        if self.context_manager.get_latest() is not None and not self.require_fresh_patient_context("Prompt 2"):
            return
        if not self.validate_result_for_current_patient("result_1", "Prompt 2"):
            return

        result_1 = primary_result if primary_result is not None else self.get_text(self.result_text).strip()
        if not result_1:
            self.secondary_status_var.set("Prompt 2: Résultat 1 vide")
            if trigger == "auto":
                self.append_analysis_history(
                    sent_message_1=primary_sent_message or self.get_text(self.sent_message_text),
                    result_1="",
                    prompt_2_status="skipped_no_result_1",
                )
            else:
                messagebox.showwarning("Prompt 2", "Lance d’abord Prompt 1 : Résultat 1 est vide.", parent=self.root)
            return

        if primary_result is not None:
            self.set_rich_result_text(self.result_text, format_weda_rich_text(primary_result), source="result_1")

        try:
            message_2, variables = self.build_secondary_lmstudio_message()
        except Exception as exc:
            self.set_text(self.secondary_result_text, f"Erreur Prompt 2 : {exc}")
            self.secondary_status_var.set("Prompt 2: erreur de préparation")
            if trigger == "auto":
                self.append_analysis_history(
                    sent_message_1=primary_sent_message or self.get_text(self.sent_message_text),
                    result_1=result_1,
                    prompt_2_status="error",
                    prompt_2_error=str(exc),
                )
            else:
                messagebox.showerror("Prompt 2", str(exc), parent=self.root)
            return

        self.set_text(self.secondary_sent_message_text, message_2, readonly=True)
        self.secondary_status_var.set("Prompt 2: envoi en cours")
        self.secondary_running = True
        self.start_lmstudio_spinner(LMSTUDIO_SECONDARY_RETRY_SPINNER_KEY)
        client = self.build_lmstudio_client()
        self.adjust_lmstudio_client_for_context(client, message_2, label="prompt_2")
        sent_message_1 = primary_sent_message or self.get_text(self.sent_message_text)

        self.log_debug(
            "info",
            "app",
            "secondary_lmstudio_request_started",
            "Envoi Prompt 2 à LM Studio.",
            {
                "trigger": trigger,
                "prompt_2_name": variables.get("prompt_2_name", ""),
                "message_length": len(message_2),
                "result_1_length": len(result_1),
            },
        )

        self.launch_lmstudio_request(
            "document_2",
            client,
            message_2,
            on_success=lambda response: self.on_secondary_lmstudio_response(
                response,
                message_2,
                sent_message_1,
                result_1,
                trigger,
            ),
            on_error=lambda error: self.on_secondary_lmstudio_error(
                error,
                message_2,
                sent_message_1,
                result_1,
                trigger,
            ),
            thread_name="lmstudio-secondary-request",
            result_source="result_2",
        )

    def on_secondary_lmstudio_response(
        self,
        response,
        sent_message_2: str,
        sent_message_1: str,
        result_1: str,
        trigger: str,
    ) -> None:
        self.secondary_running = False
        self.stop_lmstudio_spinner(LMSTUDIO_SECONDARY_RETRY_SPINNER_KEY)
        result_2_text = self.apply_abbreviations_to_lmstudio_result(response.text, "Résultat 2")
        result_2_payload = self.remember_weda_result_payload("result_2", result_2_text)
        self.record_generation_metric(
            "document_2",
            "result_2",
            status="success",
            elapsed_seconds=response.elapsed_seconds,
            input_chars=len(sent_message_2 or ""),
            result_chars=len(result_2_payload.text or ""),
        )
        self.set_rich_result_text(self.secondary_result_text, result_2_payload, source="result_2")
        self.select_tab_containing_widget(self.secondary_result_text)
        self.secondary_status_var.set(f"Prompt 2: réponse reçue en {response.elapsed_seconds:.1f}s")
        self.log_debug(
            "info",
            "app",
            "secondary_lmstudio_response",
            "Réponse Prompt 2 reçue.",
            {
                "trigger": trigger,
                "elapsed_seconds": response.elapsed_seconds,
                "raw_result_2_length": len(response.text or ""),
                "result_2_length": len(result_2_payload.text or ""),
                "result_2_html_length": len(result_2_payload.html or ""),
            },
        )
        self.schedule_tertiary_message_refresh()
        if self.is_tertiary_auto_run_enabled():
            self.run_tertiary_analysis(
                trigger="auto",
                sent_message_1=sent_message_1,
                result_1=result_1,
                sent_message_2=sent_message_2,
                result_2=result_2_payload.text,
                prompt_2_status="manual_run" if trigger == "manual_run" else "success",
            )
            return
        self.append_analysis_history(
            sent_message_1=sent_message_1,
            result_1=result_1,
            prompt_2_status="manual_run" if trigger == "manual_run" else "success",
            message_sent_2=sent_message_2,
            result_2=result_2_payload.text,
            prompt_3_status="disabled" if not self.tertiary_enabled_var.get() else "skipped_no_result_2",
        )

    def on_secondary_lmstudio_error(
        self,
        error: Exception,
        sent_message_2: str,
        sent_message_1: str,
        result_1: str,
        trigger: str,
    ) -> None:
        self.secondary_running = False
        self.discard_pending_result_patient_binding("result_2")
        self.stop_lmstudio_spinner(LMSTUDIO_SECONDARY_RETRY_SPINNER_KEY)
        if self.lmstudio_request_was_cancelled(error):
            self.record_generation_metric(
                "document_2",
                "result_2",
                status="cancelled",
                input_chars=len(sent_message_2 or ""),
                error=error,
            )
            self.secondary_status_var.set("Prompt 2: génération annulée")
            if self.tertiary_enabled_var.get():
                self.tertiary_status_var.set("Prompt 3: non lancé")
            self.log_debug("info", "app", "secondary_lmstudio_cancelled", str(error), {"trigger": trigger})
            return
        self.record_generation_metric(
            "document_2",
            "result_2",
            status="error",
            input_chars=len(sent_message_2 or ""),
            error=error,
        )
        message = f"Erreur Prompt 2 : {error}"
        self.set_text(self.secondary_result_text, message)
        self.select_tab_containing_widget(self.secondary_result_text)
        self.secondary_status_var.set("Prompt 2: erreur")
        if self.tertiary_enabled_var.get():
            self.tertiary_status_var.set("Prompt 3: non lancé, erreur Prompt 2")
        self.log_debug("error", "app", "secondary_lmstudio_error", str(error), {"trigger": trigger})
        self.append_analysis_history(
            sent_message_1=sent_message_1,
            result_1=result_1,
            prompt_2_status="error",
            message_sent_2=sent_message_2,
            prompt_2_error=str(error),
        )
        if trigger != "auto":
            messagebox.showerror("Prompt 2", str(error), parent=self.root)

    def run_tertiary_analysis_manual(self) -> None:
        self.run_tertiary_analysis(trigger="manual_run")

    def run_tertiary_analysis(
        self,
        *,
        trigger: str = "manual_run",
        sent_message_1: str | None = None,
        result_1: str | None = None,
        sent_message_2: str | None = None,
        result_2: str | None = None,
        prompt_2_status: str = "",
    ) -> None:
        if self.tertiary_running:
            self.tertiary_status_var.set("Prompt 3: déjà en cours")
            return
        if self.context_manager.get_latest() is not None and not self.require_fresh_patient_context("Prompt 3"):
            return
        if not self.validate_result_for_current_patient("result_1_result_2", "Prompt 3"):
            return

        result_1_text = result_1 if result_1 is not None else self.get_text(self.result_text).strip()
        result_2_text = result_2 if result_2 is not None else self.get_text(self.secondary_result_text).strip()
        if not result_2_text:
            self.tertiary_status_var.set("Prompt 3: Résultat 2 vide")
            if trigger == "auto":
                self.append_analysis_history(
                    sent_message_1=sent_message_1 or self.get_text(self.sent_message_text),
                    result_1=result_1_text,
                    prompt_2_status=prompt_2_status or "success",
                    message_sent_2=sent_message_2 or self.get_text(self.secondary_sent_message_text),
                    result_2="",
                    prompt_3_status="skipped_no_result_2",
                )
            else:
                messagebox.showwarning("Prompt 3", "Lance d’abord Prompt 2 : Résultat 2 est vide.", parent=self.root)
            return

        if result_1 is not None:
            self.set_rich_result_text(self.result_text, format_weda_rich_text(result_1_text), source="result_1")
        if result_2 is not None:
            self.set_rich_result_text(self.secondary_result_text, format_weda_rich_text(result_2_text), source="result_2")

        try:
            message_3, variables = self.build_tertiary_lmstudio_message()
        except Exception as exc:
            self.set_text(self.tertiary_result_text, f"Erreur Prompt 3 : {exc}")
            self.tertiary_status_var.set("Prompt 3: erreur de préparation")
            if trigger == "auto":
                self.append_analysis_history(
                    sent_message_1=sent_message_1 or self.get_text(self.sent_message_text),
                    result_1=result_1_text,
                    prompt_2_status=prompt_2_status or "success",
                    message_sent_2=sent_message_2 or self.get_text(self.secondary_sent_message_text),
                    result_2=result_2_text,
                    prompt_3_status="error",
                    prompt_3_error=str(exc),
                )
            else:
                messagebox.showerror("Prompt 3", str(exc), parent=self.root)
            return

        self.set_text(self.tertiary_sent_message_text, message_3, readonly=True)
        self.tertiary_status_var.set("Prompt 3: envoi en cours")
        self.tertiary_running = True
        self.start_lmstudio_spinner(LMSTUDIO_TERTIARY_RETRY_SPINNER_KEY)
        client = self.build_lmstudio_client()
        self.adjust_lmstudio_client_for_context(client, message_3, label="prompt_3")
        sent_message_1_text = sent_message_1 or self.get_text(self.sent_message_text)
        sent_message_2_text = sent_message_2 or self.get_text(self.secondary_sent_message_text)

        self.log_debug(
            "info",
            "app",
            "tertiary_lmstudio_request_started",
            "Envoi Prompt 3 à LM Studio.",
            {
                "trigger": trigger,
                "prompt_3_name": variables.get("prompt_3_name", ""),
                "message_length": len(message_3),
                "result_1_length": len(result_1_text),
                "result_2_length": len(result_2_text),
            },
        )

        self.launch_lmstudio_request(
            "document_3",
            client,
            message_3,
            on_success=lambda response: self.on_tertiary_lmstudio_response(
                response,
                message_3,
                sent_message_1_text,
                result_1_text,
                sent_message_2_text,
                result_2_text,
                prompt_2_status,
                trigger,
            ),
            on_error=lambda error: self.on_tertiary_lmstudio_error(
                error,
                message_3,
                sent_message_1_text,
                result_1_text,
                sent_message_2_text,
                result_2_text,
                prompt_2_status,
                trigger,
            ),
            thread_name="lmstudio-tertiary-request",
            result_source="result_3",
        )

    def on_tertiary_lmstudio_response(
        self,
        response,
        sent_message_3: str,
        sent_message_1: str,
        result_1: str,
        sent_message_2: str,
        result_2: str,
        prompt_2_status: str,
        trigger: str,
    ) -> None:
        self.tertiary_running = False
        self.stop_lmstudio_spinner(LMSTUDIO_TERTIARY_RETRY_SPINNER_KEY)
        result_3_text = self.apply_abbreviations_to_lmstudio_result(response.text, "Résultat 3")
        result_3_payload = self.remember_weda_result_payload("result_3", result_3_text)
        self.record_generation_metric(
            "document_3",
            "result_3",
            status="success",
            elapsed_seconds=response.elapsed_seconds,
            input_chars=len(sent_message_3 or ""),
            result_chars=len(result_3_payload.text or ""),
        )
        self.set_rich_result_text(self.tertiary_result_text, result_3_payload, source="result_3")
        self.select_tab_containing_widget(self.tertiary_result_text)
        self.tertiary_status_var.set(f"Prompt 3: réponse reçue en {response.elapsed_seconds:.1f}s")
        self.log_debug(
            "info",
            "app",
            "tertiary_lmstudio_response",
            "Réponse Prompt 3 reçue.",
            {
                "trigger": trigger,
                "elapsed_seconds": response.elapsed_seconds,
                "raw_result_3_length": len(response.text or ""),
                "result_3_length": len(result_3_payload.text or ""),
                "result_3_html_length": len(result_3_payload.html or ""),
            },
        )
        self.append_analysis_history(
            sent_message_1=sent_message_1,
            result_1=result_1,
            prompt_2_status=prompt_2_status or "success",
            message_sent_2=sent_message_2,
            result_2=result_2,
            prompt_3_status="manual_run" if trigger == "manual_run" else "success",
            message_sent_3=sent_message_3,
            result_3=result_3_payload.text,
        )

    def on_tertiary_lmstudio_error(
        self,
        error: Exception,
        sent_message_3: str,
        sent_message_1: str,
        result_1: str,
        sent_message_2: str,
        result_2: str,
        prompt_2_status: str,
        trigger: str,
    ) -> None:
        self.tertiary_running = False
        self.discard_pending_result_patient_binding("result_3")
        self.stop_lmstudio_spinner(LMSTUDIO_TERTIARY_RETRY_SPINNER_KEY)
        if self.lmstudio_request_was_cancelled(error):
            self.record_generation_metric(
                "document_3",
                "result_3",
                status="cancelled",
                input_chars=len(sent_message_3 or ""),
                error=error,
            )
            self.tertiary_status_var.set("Prompt 3: génération annulée")
            self.log_debug("info", "app", "tertiary_lmstudio_cancelled", str(error), {"trigger": trigger})
            return
        self.record_generation_metric(
            "document_3",
            "result_3",
            status="error",
            input_chars=len(sent_message_3 or ""),
            error=error,
        )
        message = f"Erreur Prompt 3 : {error}"
        self.set_text(self.tertiary_result_text, message)
        self.select_tab_containing_widget(self.tertiary_result_text)
        self.tertiary_status_var.set("Prompt 3: erreur")
        self.log_debug("error", "app", "tertiary_lmstudio_error", str(error), {"trigger": trigger})
        self.append_analysis_history(
            sent_message_1=sent_message_1,
            result_1=result_1,
            prompt_2_status=prompt_2_status or "success",
            message_sent_2=sent_message_2,
            result_2=result_2,
            prompt_3_status="error",
            message_sent_3=sent_message_3,
            prompt_3_error=str(error),
        )
        if trigger != "auto":
            messagebox.showerror("Prompt 3", str(error), parent=self.root)

    def on_lmstudio_error(self, error: Exception) -> None:
        self.stop_lmstudio_spinner(LMSTUDIO_MAIN_SPINNER_KEY)
        self.discard_pending_result_patient_binding("result_1")
        self.stop_lmstudio_spinner(LMSTUDIO_RESULT_RETRY_SPINNER_KEY)
        if self.lmstudio_request_was_cancelled(error):
            self.record_generation_metric("document_1", "result_1", status="cancelled", error=error)
            self.lmstudio_status_var.set("LM Studio: génération annulée")
            if self.secondary_enabled_var.get():
                self.secondary_status_var.set("Prompt 2: non lancé")
            if self.tertiary_enabled_var.get():
                self.tertiary_status_var.set("Prompt 3: non lancé")
            self.log_debug("info", "app", "lmstudio_cancelled", str(error))
            return
        self.record_generation_metric("document_1", "result_1", status="error", error=error)
        self.lmstudio_status_var.set("LM Studio: erreur")
        if self.secondary_enabled_var.get():
            self.secondary_status_var.set("Prompt 2: non lancé, erreur Prompt 1")
        if self.tertiary_enabled_var.get():
            self.tertiary_status_var.set("Prompt 3: non lancé, erreur Prompt 1")
        self.log_debug("error", "app", "lmstudio_error", str(error))
        messagebox.showerror("LM Studio", str(error), parent=self.root)

    def current_patient_safety_state(self, *, require_patient_id: bool = False):
        return evaluate_patient_context(
            self.context_manager.get_latest(),
            require_patient_id=require_patient_id,
        )

    def update_patient_safety_banner(self) -> None:
        state = self.current_patient_safety_state()
        self.patient_safety_title_var.set(state.title)
        self.patient_safety_detail_var.set(state.detail)
        if not hasattr(self, "patient_safety_bar"):
            return
        palette = {
            PATIENT_SAFETY_OK: ("#12372a", "#15803d", "PRÊT", "#bbf7d0"),
            "warning": ("#3b2f0b", "#a16207", "ATTENTION", "#fde68a"),
            PATIENT_SAFETY_BLOCKED: ("#3b1014", "#991b1b", "VERROUILLÉ", "#fecaca"),
        }
        background, badge, badge_text, detail_color = palette.get(state.level, palette[PATIENT_SAFETY_BLOCKED])
        self.patient_safety_bar.configure(bg=background)
        self.patient_safety_badge.configure(bg=badge, text=badge_text)
        self.patient_safety_title_label.configure(bg=background)
        self.patient_safety_detail_label.configure(bg=background, fg=detail_color)

    def require_fresh_patient_context(self, action: str, *, require_patient_id: bool = False) -> bool:
        state = self.current_patient_safety_state(require_patient_id=require_patient_id)
        self.update_patient_safety_banner()
        allowed = state.allows_import if require_patient_id else state.allows_generation
        if allowed:
            return True
        if hasattr(self, "context_text"):
            self.select_tab_containing_widget(self.context_text)
        messagebox.showerror(
            "Verrou patient WEDA",
            f"{action} bloqué.\n\n{state.title}\n{state.detail}",
            parent=self.root,
        )
        return False

    def result_binding_sources(self, source: str) -> list[str]:
        if source == "result_1_result_2":
            return ["result_1", "result_2"]
        if source == "result_1_result_2_result_3":
            return ["result_1", "result_2", "result_3"]
        return [source]

    def validate_result_patient_binding(self, source: str) -> bool:
        if not self.require_fresh_patient_context("Import WEDA", require_patient_id=True):
            return False
        context = self.context_manager.get_latest()
        current_patient_id = normalize_patient_id(getattr(context, "patient_id", ""))
        for key in self.result_binding_sources(source):
            binding = self.result_patient_bindings.get(key)
            if not binding or not normalize_patient_id(binding.get("patient_id")):
                messagebox.showerror(
                    "Verrou patient WEDA",
                    "Import bloqué : ce résultat n’est pas rattaché à un dossier WEDA vérifié.\n"
                    "Régénère-le après avoir récupéré le contexte du patient.",
                    parent=self.root,
                )
                return False
            if not patient_ids_match(binding.get("patient_id"), current_patient_id):
                messagebox.showerror(
                    "Verrou patient WEDA",
                    "Import bloqué : le dossier WEDA a changé depuis la génération de ce résultat.\n"
                    "Le résultat reste visible, mais ne peut pas être rattaché au nouveau patient.",
                    parent=self.root,
                )
                self.patient_safety_title_var.set("Dossier changé — résultat précédent verrouillé")
                self.patient_safety_detail_var.set("Régénère le document pour le patient actuellement affiché.")
                return False
        return True

    def validate_result_for_current_patient(self, source: str, action: str) -> bool:
        context = self.context_manager.get_latest()
        if context is None:
            return True
        current_patient_id = normalize_patient_id(getattr(context, "patient_id", ""))
        for key in self.result_binding_sources(source):
            binding = self.result_patient_bindings.get(key)
            bound_patient_id = normalize_patient_id(binding.get("patient_id")) if binding else ""
            if bound_patient_id and current_patient_id and not patient_ids_match(bound_patient_id, current_patient_id):
                messagebox.showerror(
                    "Verrou patient WEDA",
                    f"{action} bloqué : le résultat source appartient au dossier WEDA précédent.",
                    parent=self.root,
                )
                return False
        return True

    def refresh_context_from_manager(self) -> None:
        context = self.context_manager.get_latest()
        if not context:
            self.weda_patient_status_var.set("Patient WEDA: non reçu")
            self.update_patient_safety_banner()
            return
        self.set_text(self.context_text, context.to_prompt_text())
        patient_label = context.patient_identity or context.patient_name or context.patient_id or "reçu"
        self.weda_patient_status_var.set(f"Patient WEDA: {patient_label[:40]}")
        self.update_patient_safety_banner()

    def request_weda_context_refresh(self) -> dict:
        job = {
            "id": uuid.uuid4().hex,
            "status": "pending",
            "message": "Demande envoyée à l’onglet WEDA visible.",
            "requested_at": time.time(),
        }
        with self._weda_context_refresh_lock:
            self.weda_context_refresh_job = job
        self.weda_patient_status_var.set("Patient WEDA: actualisation demandée…")
        self.log_debug(
            "info",
            "app",
            "weda_context_refresh_requested",
            "Nouvelle collecte du contexte demandée à WEDA.",
            {"request_id": job["id"]},
        )
        self.root.after(
            WEDA_CONTEXT_REFRESH_TIMEOUT_MS,
            lambda request_id=job["id"]: self.expire_weda_context_refresh(request_id),
        )
        return dict(job)

    def get_weda_context_refresh_request(self) -> dict | None:
        with self._weda_context_refresh_lock:
            return dict(self.weda_context_refresh_job) if self.weda_context_refresh_job else None

    def claim_weda_context_refresh(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        request_id = str(payload.get("request_id") or payload.get("requestId") or "")
        responder_id = str(payload.get("responder_id") or payload.get("responderId") or "")
        with self._weda_context_refresh_lock:
            job = dict(self.weda_context_refresh_job or {})
            if not job or job.get("id") != request_id:
                return {"claimed": False, "reason": "request_not_found"}
            current_responder = str(job.get("responder_id") or "")
            if job.get("status") == "collecting" and current_responder == responder_id:
                return {"claimed": True, "job": job}
            if job.get("status") != "pending":
                return {"claimed": False, "reason": str(job.get("status") or "not_pending"), "job": job}
            job.update(
                {
                    "status": "collecting",
                    "message": "Collecte en cours dans WEDA.",
                    "responder_id": responder_id,
                    "page_url": str(payload.get("page_url") or ""),
                    "claimed_at": time.time(),
                }
            )
            self.weda_context_refresh_job = job

        self.root.after(0, self.weda_patient_status_var.set, "Patient WEDA: collecte en cours…")
        self.log_debug(
            "info",
            "app",
            "weda_context_refresh_claimed",
            "Demande de contexte prise en charge par un onglet WEDA.",
            {"request_id": request_id, "page_url": job.get("page_url", "")},
        )
        return {"claimed": True, "job": dict(job)}

    def acknowledge_weda_context_refresh(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        request_id = str(payload.get("request_id") or payload.get("requestId") or "")
        responder_id = str(payload.get("responder_id") or payload.get("responderId") or "")
        success = str(payload.get("status") or "").lower() == "success"
        with self._weda_context_refresh_lock:
            job = dict(self.weda_context_refresh_job or {})
            if not job or job.get("id") != request_id:
                return {"accepted": False, "reason": "request_not_found"}
            if job.get("responder_id") and responder_id != job.get("responder_id"):
                return {"accepted": False, "reason": "responder_mismatch", "job": job}
            job.update(
                {
                    "status": "done" if success else "error",
                    "message": (
                        "Contexte WEDA actualisé."
                        if success
                        else str(payload.get("error") or "La collecte WEDA a échoué.")
                    ),
                    "completed_at": time.time(),
                    "visible_text_length": int(payload.get("visible_text_length") or 0),
                    "patient_id_present": bool(payload.get("patient_id_present")),
                }
            )
            self.weda_context_refresh_job = job

        def update_ui():
            if success:
                self.refresh_context_from_manager()
                context = self.context_manager.get_latest()
                patient_label = (
                    context.patient_identity or context.patient_name or context.patient_id or "reçu"
                    if context
                    else "non reçu"
                )
                self.weda_patient_status_var.set(f"Patient WEDA: {patient_label[:32]} — contexte actualisé")
            else:
                self.weda_patient_status_var.set("Patient WEDA: échec de l’actualisation")

        self.root.after(0, update_ui)
        self.log_debug(
            "info" if success else "error",
            "app",
            "weda_context_refresh_acknowledged",
            job["message"],
            {
                "request_id": request_id,
                "visible_text_length": job.get("visible_text_length", 0),
                "patient_id_present": job.get("patient_id_present", False),
            },
        )
        return {"accepted": True, "job": dict(job)}

    def expire_weda_context_refresh(self, request_id: str) -> None:
        with self._weda_context_refresh_lock:
            job = dict(self.weda_context_refresh_job or {})
            if not job or job.get("id") != request_id or job.get("status") not in {"pending", "collecting"}:
                return
            job.update(
                {
                    "status": "timeout",
                    "message": "Aucun onglet WEDA visible n’a répondu à la demande.",
                    "completed_at": time.time(),
                }
            )
            self.weda_context_refresh_job = job
        self.weda_patient_status_var.set("Patient WEDA: aucun onglet n’a répondu")
        self.log_debug(
            "warning",
            "app",
            "weda_context_refresh_timeout",
            job["message"],
            {"request_id": request_id},
        )

    def clear_context(self) -> None:
        self.context_manager.clear()
        self.set_text(self.context_text, "")
        self.weda_patient_status_var.set("Patient WEDA: non reçu")
        self.update_patient_safety_banner()

    def on_server_context(self, _context) -> None:
        self.log_debug(
            "info",
            "app",
            "context_received_callback",
            "Contexte WEDA reçu par l’application.",
            {"patient_id": getattr(_context, "patient_id", ""), "patient_identity": getattr(_context, "patient_identity", "")},
        )
        self.root.after(0, self.refresh_context_from_manager)

    def on_import_status(self, _request, payload: dict) -> None:
        status = str(payload.get("status") or "statut reçu")
        self.log_debug(
            "info",
            "app",
            "import_status_callback",
            "Statut d’import reçu.",
            {
                "status": status,
                "request_id": payload.get("request_id") or "",
                "target": payload.get("target") or {},
                "error": payload.get("error") or "",
            },
        )
        self.root.after(0, self.import_status_var.set, f"Import WEDA: {status}")

    def on_debug_log(self, _entry) -> None:
        self.root.after(0, self.log_status_var.set, "Logs: événement reçu")

    def get_result_text_for_import(self, source: str = "result_1") -> str:
        return self.get_result_payload_for_import(source).text

    def prepare_weda_import(self, source: str = "result_1") -> None:
        if not self.validate_result_patient_binding(source):
            return
        result_payload = self.get_result_payload_for_import(source)
        result = result_payload.text
        if not result:
            label = {
                "result_2": "Résultat 2",
                "result_3": "Résultat 3",
                "document_now": "Document maintenant",
                "result_1_result_2": "résultat 1 + 2",
                "result_1_result_2_result_3": "résultat 1 + 2 + 3",
            }.get(source, "résultat LM Studio")
            messagebox.showwarning("Import WEDA", f"Le {label} est vide.", parent=self.root)
            return
        self.record_import_correction_metrics(source)
        context = self.context_manager.get_latest()
        request = self.import_manager.prepare_result(
            result,
            result_html=result_payload.html,
            patient_id=context.patient_id if context else "",
            patient_identity=context.patient_identity if context else "",
            destination="active_field",
        )
        self.import_status_var.set("Import WEDA: résultat prêt")
        self.log_debug(
            "info",
            "app",
            "weda_import_prepared",
            "Résultat prêt pour import WEDA.",
            {
                "request_id": request.id,
                "patient_id": request.patient_id,
                "patient_identity": request.patient_identity,
                "result_length": len(result),
                "result_html_length": len(result_payload.html or ""),
                "source": source,
                "destination": request.destination,
            },
        )
        messagebox.showinfo(
            "Import WEDA",
            "Résultat préparé.\nDans WEDA, clique sur le bouton du pont local pour l’insérer dans le champ actif.",
            parent=self.root,
        )
        self.history_manager.append(
            {
                **self.current_stt_history_payload(),
                "prompt_name": self.prompt_var.get(),
                "lmstudio_result": result,
                "result_1": self.get_text(self.result_text),
                "result_2": self.get_text(self.secondary_result_text),
                "result_3": self.get_text(self.tertiary_result_text) if hasattr(self, "tertiary_result_text") else "",
                "document_now_result": (
                    self.get_text(self.document_now_result_text)
                    if hasattr(self, "document_now_result_text")
                    else ""
                ),
                "source": source,
                "destination": request.destination,
                "status": "weda_import_prepared",
                "patient_id": request.patient_id,
                "patient_identity": request.patient_identity,
            }
        )

    def prepare_weda_import_result_2(self) -> None:
        self.prepare_weda_import(source="result_2")

    def prepare_weda_import_result_3(self) -> None:
        self.prepare_weda_import(source="result_3")

    def prepare_weda_import_document_now(self) -> None:
        self.prepare_weda_import(source="document_now")

    def copy_result(self) -> None:
        ok = self.copy_rich_result_source("result_1")
        self.import_status_var.set("Résultat WEDA copié" if ok else "Copie impossible")

    def copy_secondary_result(self) -> None:
        ok = self.copy_rich_result_source("result_2")
        self.secondary_status_var.set("Résultat 2 WEDA copié" if ok else "Copie Résultat 2 impossible")

    def copy_tertiary_result(self) -> None:
        ok = self.copy_rich_result_source("result_3")
        self.tertiary_status_var.set("Résultat 3 WEDA copié" if ok else "Copie Résultat 3 impossible")

    def copy_transcription(self) -> None:
        raw = clean_transcription_text(
            self.get_text(self.transcription_text), self.config.get("transcription_cleaning", {})
        )
        ok = copy_text_to_clipboard(raw, self.root)
        self.transcription_status_var.set("Transcription brute copiée" if ok else "Copie impossible")

    def clear_transcription(self) -> None:
        self.set_text(self.transcription_text, "")
        if hasattr(self, "corrected_transcription_text"):
            self.set_text(self.corrected_transcription_text, "")
        if hasattr(self, "correction_review_text"):
            self.set_text(self.correction_review_text, "", readonly=True)
        self.pending_transcription_corrections = []
        self.transcription_draft_store.clear()
        self.transcription_status_var.set("Transcription prête")

    def reset_corrected_transcription(self) -> None:
        raw = self.get_text(self.transcription_text)
        self.set_text(self.corrected_transcription_text, raw)
        self.pending_transcription_corrections = []
        self.set_text(self.correction_review_text, "Aucune correction en attente.", readonly=True)
        self.transcription_status_var.set("Couche corrigée réalignée sur la transcription brute")

    def review_transcription_corrections(self) -> None:
        raw = self.get_text(self.transcription_text)
        corrected = self.get_text(self.corrected_transcription_text)
        self.pending_transcription_corrections = propose_corrections(raw, corrected)
        self.set_text(
            self.correction_review_text,
            format_correction_review(raw, corrected),
            readonly=True,
        )
        self.transcription_status_var.set(
            f"{len(self.pending_transcription_corrections)} correction(s) proposée(s), non encore apprise(s)"
        )

    def validate_transcription_corrections(self) -> None:
        self.review_transcription_corrections()
        if not self.pending_transcription_corrections:
            messagebox.showinfo("Corrections locales", "Aucune correction lexicale à valider.", parent=self.root)
            return
        if not messagebox.askyesno(
            "Valider les corrections",
            f"Mémoriser localement {len(self.pending_transcription_corrections)} correction(s) affichée(s) ?",
            parent=self.root,
        ):
            return
        model = str((self.last_stt_result or {}).get("model") or "")
        for proposal in self.pending_transcription_corrections:
            category = self.guess_transcription_correction_category(proposal.correction)
            self.correction_store.validate(
                proposal.source,
                proposal.correction,
                context_before=proposal.context_before,
                context_after=proposal.context_after,
                category=category,
                whisper_model=model,
            )
        count = len(self.pending_transcription_corrections)
        self.pending_transcription_corrections = []
        self.save_medical_transcription_settings()
        self.set_text(self.correction_review_text, f"{count} correction(s) validée(s) et mémorisée(s) localement.", readonly=True)
        self.transcription_status_var.set(f"{count} correction(s) validée(s)")
        self.log_debug(
            "info",
            "transcription",
            "transcription_corrections_validated",
            "Corrections de transcription validées explicitement.",
            {"count": count},
        )

    def reject_transcription_corrections(self) -> None:
        self.review_transcription_corrections()
        if not self.pending_transcription_corrections:
            return
        for proposal in self.pending_transcription_corrections:
            self.correction_store.reject(
                proposal.source,
                proposal.correction,
                context_before=proposal.context_before,
                context_after=proposal.context_after,
            )
        count = len(self.pending_transcription_corrections)
        self.pending_transcription_corrections = []
        self.set_text(self.correction_review_text, f"{count} correction(s) rejetée(s), aucune n’a été apprise.", readonly=True)
        self.transcription_status_var.set(f"{count} correction(s) rejetée(s)")

    def guess_transcription_correction_category(self, correction: str) -> str:
        value = str(correction or "")
        normalized = value.casefold()
        if any(marker in normalized for marker in ("ine", "ol", "pril", "sartan", "mab", "xaban")):
            return "medicament"
        if any(marker in normalized for marker in ("émie", "urie", "hémoglobine", "bnp", "créatin")):
            return "biologie"
        if value[:1].isupper():
            return "nom_propre"
        return "autre"

    def restore_last_transcription(self) -> None:
        draft = self.transcription_draft_store.load()
        if not draft:
            return
        self.set_text(self.transcription_text, draft.text)
        if hasattr(self, "corrected_transcription_text"):
            corrected = draft.text
            if bool(self.config.get("medical_transcription", {}).get("apply_validated_corrections", False)):
                corrected, _count = self.correction_store.apply_conservative(
                    corrected,
                    min_validations=int(
                        self.config.get("medical_transcription", {}).get(
                            "min_validations_for_automatic_correction",
                            MIN_VALIDATIONS_FOR_AUTOMATIC_CORRECTION,
                        )
                    ),
                )
            self.set_text(self.corrected_transcription_text, corrected)
        self.transcription_status_var.set("Transcription restaurée depuis la dernière fermeture")
        self.log_debug(
            "info",
            "app",
            "transcription_draft_restored",
            "Dernière transcription restaurée.",
            {"saved_at": draft.saved_at, "text_length": len(draft.text)},
        )

    def save_last_transcription(self) -> None:
        text = self.get_text(self.transcription_text)
        draft = self.transcription_draft_store.save(text)
        self.log_debug(
            "info",
            "app",
            "transcription_draft_saved" if draft else "transcription_draft_cleared",
            "Dernière transcription conservée pour le prochain lancement."
            if draft
            else "Aucune transcription à conserver.",
            {"text_length": len(text)},
        )

    def clear_result(self) -> None:
        self.set_text(self.result_text, "")
        self.rich_result_payloads.pop("result_1", None)
        self.result_patient_bindings.pop("result_1", None)
        self.generated_result_originals.pop("result_1", None)
        self.result_generation_metadata.pop("result_1", None)
        self.lmstudio_status_var.set("LM Studio: prêt")
        self.schedule_secondary_message_refresh()
        self.schedule_tertiary_message_refresh()

    def clear_secondary_result(self) -> None:
        self.set_text(self.secondary_result_text, "")
        self.rich_result_payloads.pop("result_2", None)
        self.result_patient_bindings.pop("result_2", None)
        self.generated_result_originals.pop("result_2", None)
        self.result_generation_metadata.pop("result_2", None)
        self.secondary_status_var.set("Prompt 2: résultat effacé")
        if hasattr(self, "tertiary_result_text"):
            self.set_text(self.tertiary_result_text, "")
            self.rich_result_payloads.pop("result_3", None)
            self.result_patient_bindings.pop("result_3", None)
            self.generated_result_originals.pop("result_3", None)
            self.result_generation_metadata.pop("result_3", None)
            self.tertiary_status_var.set("Prompt 3: en attente du Résultat 2")
        self.schedule_tertiary_message_refresh()

    def clear_tertiary_result(self) -> None:
        self.set_text(self.tertiary_result_text, "")
        self.rich_result_payloads.pop("result_3", None)
        self.result_patient_bindings.pop("result_3", None)
        self.generated_result_originals.pop("result_3", None)
        self.result_generation_metadata.pop("result_3", None)
        self.tertiary_status_var.set("Prompt 3: résultat effacé")
        self.schedule_tertiary_message_refresh()

    def use_result_for_pdf(self) -> None:
        result_1 = self.get_text(self.result_text).strip()
        if not result_1:
            messagebox.showwarning("PDF structuré", "Résultat 1 est vide.", parent=self.root)
            return
        self.pdf_source_var.set("Résultat 1")
        self.save_pdf_source_preference()
        self.result_destination_var.set("PDF structuré")
        self.on_result_destination_changed()
        if hasattr(self, "pdf_tab_frame"):
            self.notebook.select(self.pdf_tab_frame)
        self.pdf_status_var.set("PDF: source Résultat 1 sélectionnée")

    def use_secondary_result_for_pdf(self) -> None:
        result_2 = self.get_text(self.secondary_result_text).strip()
        if not result_2:
            messagebox.showwarning("PDF structuré", "Résultat 2 est vide.", parent=self.root)
            return
        self.pdf_source_var.set("Résultat 2")
        self.save_pdf_source_preference()
        self.result_destination_var.set("PDF structuré")
        self.on_result_destination_changed()
        if hasattr(self, "pdf_tab_frame"):
            self.notebook.select(self.pdf_tab_frame)
        self.pdf_status_var.set("PDF: source Résultat 2 sélectionnée")

    def use_tertiary_result_for_pdf(self) -> None:
        result_3 = self.get_text(self.tertiary_result_text).strip()
        if not result_3:
            messagebox.showwarning("PDF structuré", "Résultat 3 est vide.", parent=self.root)
            return
        self.pdf_source_var.set("Résultat 3")
        self.save_pdf_source_preference()
        self.result_destination_var.set("PDF structuré")
        self.on_result_destination_changed()
        if hasattr(self, "pdf_tab_frame"):
            self.notebook.select(self.pdf_tab_frame)
        self.pdf_status_var.set("PDF: source Résultat 3 sélectionnée")

    def use_document_now_result_for_pdf(self) -> None:
        result = self.get_text(self.document_now_result_text).strip()
        if not result:
            messagebox.showwarning("PDF structuré", "Document maintenant est vide.", parent=self.root)
            return
        self.pdf_source_var.set("Document maintenant")
        self.save_pdf_source_preference()
        self.result_destination_var.set("PDF structuré")
        self.on_result_destination_changed()
        if hasattr(self, "pdf_tab_frame"):
            self.notebook.select(self.pdf_tab_frame)
        self.pdf_status_var.set("PDF: source Document maintenant sélectionnée")

    def log_debug(
        self,
        level: str,
        source: str,
        event: str,
        message: str = "",
        details: dict | None = None,
    ) -> None:
        try:
            self.debug_logger.append(level, source, event, message, details or {})
            self.root.after(0, self.log_status_var.set, f"Logs: {event}")
        except Exception:
            try:
                self.root.after(0, self.log_status_var.set, "Logs: erreur")
            except Exception:
                pass

    def refresh_logs(self) -> None:
        self.set_text(self.logs_text, self.debug_logger.format_recent_text(250), readonly=True)
        self.log_status_var.set("Logs: rafraîchis")

    def copy_logs(self) -> None:
        text = self.debug_logger.format_recent_text(250)
        ok = copy_text_to_clipboard(text, self.root)
        self.log_status_var.set("Logs copiés" if ok else "Copie logs impossible")

    def clear_logs(self) -> None:
        self.debug_logger.clear()
        self.debug_logger.append("info", "app", "logs_cleared", "Logs effacés depuis l’application.")
        self.refresh_logs()

    def show_diagnostic_window(self) -> None:
        if self.diagnostic_window and self.diagnostic_window.winfo_exists():
            self.diagnostic_window.deiconify()
            self.diagnostic_window.lift()
            self.run_diagnostics_async()
            return
        window = tk.Toplevel(self.root)
        self.diagnostic_window = window
        window.title("Diagnostic DrFloW")
        window.geometry("900x560")
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", lambda: self.close_diagnostic_window())

        header = ttk.Frame(window, padding=10)
        header.pack(fill=tk.X)
        ttk.Label(header, text="Santé du système", style="Title.TLabel").pack(side=tk.LEFT)
        self.diagnostic_status_var = tk.StringVar(value="Vérification en cours…")
        ttk.Label(header, textvariable=self.diagnostic_status_var).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(header, text="Copier rapport anonymisé", command=self.copy_diagnostic_report).pack(side=tk.RIGHT)
        ttk.Button(header, text="Relancer", command=self.run_diagnostics_async).pack(side=tk.RIGHT, padx=(0, 6))

        columns = ("status", "name", "detail")
        tree = ttk.Treeview(window, columns=columns, show="headings", height=18)
        self.diagnostic_tree = tree
        tree.heading("status", text="État")
        tree.heading("name", text="Contrôle")
        tree.heading("detail", text="Détail")
        tree.column("status", width=90, anchor=tk.CENTER, stretch=False)
        tree.column("name", width=210, stretch=False)
        tree.column("detail", width=560)
        tree.tag_configure("ok", foreground="#86efac")
        tree.tag_configure("warning", foreground="#fde68a")
        tree.tag_configure("error", foreground="#fca5a5")
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.diagnostic_results = []
        self.run_diagnostics_async()

    def close_diagnostic_window(self) -> None:
        if self.diagnostic_window and self.diagnostic_window.winfo_exists():
            self.diagnostic_window.destroy()
        self.diagnostic_window = None

    def run_diagnostics_async(self) -> None:
        if not self.diagnostic_window or not self.diagnostic_window.winfo_exists():
            return
        self.diagnostic_status_var.set("Vérification en cours…")
        self.diagnostic_tree.delete(*self.diagnostic_tree.get_children())
        config_snapshot = json.loads(json.dumps(self.config))
        patient_state = self.current_patient_safety_state().level
        lm_config = config_snapshot.get("lmstudio", {})

        def lmstudio_probe() -> str:
            context = fetch_lmstudio_model_context(
                str(lm_config.get("url") or "http://localhost:1234/v1/chat/completions"),
                model=str(lm_config.get("model") or "local-model"),
                timeout_seconds=5,
            )
            if context is None:
                return "API joignable • fenêtre de contexte non annoncée"
            return f"API joignable • {context.context_length} tokens"

        def worker():
            results = run_drflow_diagnostics(
                base_dir=BASE_DIR,
                data_dir=self.data_dir,
                config=config_snapshot,
                microphone_count=len(self.micro_device_options),
                server_running=bool(self.server),
                fly_hotkey_ready=bool(self._fly_dictation_hook_handles),
                stt_label=str(self.stt_status_var.get() or self.model_manager.active_label()),
                patient_context_state=patient_state,
                lmstudio_probe=lmstudio_probe,
            )
            self.root.after(0, self.render_diagnostic_results, results)

        threading.Thread(target=worker, name="drflow-diagnostics", daemon=True).start()

    def render_diagnostic_results(self, results) -> None:
        if not self.diagnostic_window or not self.diagnostic_window.winfo_exists():
            return
        self.diagnostic_results = list(results)
        self.diagnostic_tree.delete(*self.diagnostic_tree.get_children())
        labels = {"ok": "OK", "warning": "ATTENTION", "error": "ERREUR"}
        for item in results:
            self.diagnostic_tree.insert(
                "",
                tk.END,
                values=(labels.get(item.status, item.status.upper()), item.name, item.detail),
                tags=(item.status,),
            )
        errors = sum(1 for item in results if item.status == "error")
        warnings = sum(1 for item in results if item.status == "warning")
        self.diagnostic_status_var.set(f"{len(results)} contrôles • {errors} erreur(s) • {warnings} attention(s)")

    def copy_diagnostic_report(self) -> None:
        report = sanitized_diagnostic_report(getattr(self, "diagnostic_results", []))
        ok = copy_text_to_clipboard(report, self.root)
        if hasattr(self, "diagnostic_status_var"):
            self.diagnostic_status_var.set("Rapport anonymisé copié" if ok else "Copie impossible")

    def show_quality_window(self) -> None:
        if self.quality_window and self.quality_window.winfo_exists():
            self.quality_window.deiconify()
            self.quality_window.lift()
            self.refresh_quality_window()
            return
        window = tk.Toplevel(self.root)
        self.quality_window = window
        window.title("Versions, comparaisons et qualité")
        window.geometry("1120x720")
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", self.close_quality_window)
        notebook = ttk.Notebook(window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.build_prompt_versions_tab(notebook)
        self.build_result_comparison_tab(notebook)
        self.build_quality_metrics_tab(notebook)
        self.refresh_quality_window()

    def close_quality_window(self) -> None:
        if self.quality_window and self.quality_window.winfo_exists():
            self.quality_window.destroy()
        self.quality_window = None

    def build_prompt_versions_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text="Versions de prompts")
        controls = ttk.Frame(frame)
        controls.pack(fill=tk.X, pady=(0, 8))
        self.version_prompt_var = tk.StringVar(value="")
        self.version_left_var = tk.StringVar(value="")
        self.version_right_var = tk.StringVar(value="")
        ttk.Label(controls, text="Prompt").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        self.version_prompt_combo = ttk.Combobox(controls, textvariable=self.version_prompt_var, width=42, state="readonly")
        self.version_prompt_combo.grid(row=0, column=1, sticky=tk.EW, padx=(0, 8))
        self.version_prompt_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_prompt_version_choices())
        ttk.Label(controls, text="Version A").grid(row=0, column=2, sticky=tk.W, padx=(0, 4))
        self.version_left_combo = ttk.Combobox(controls, textvariable=self.version_left_var, width=31, state="readonly")
        self.version_left_combo.grid(row=0, column=3, sticky=tk.EW, padx=(0, 8))
        ttk.Label(controls, text="Version B").grid(row=0, column=4, sticky=tk.W, padx=(0, 4))
        self.version_right_combo = ttk.Combobox(controls, textvariable=self.version_right_var, width=31, state="readonly")
        self.version_right_combo.grid(row=0, column=5, sticky=tk.EW, padx=(0, 8))
        ttk.Button(controls, text="Comparer", command=self.compare_prompt_versions).grid(row=0, column=6, padx=(0, 6))
        ttk.Button(controls, text="Restaurer A", command=self.restore_selected_prompt_version).grid(row=0, column=7)
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(3, weight=1)
        controls.columnconfigure(5, weight=1)
        self.prompt_version_diff_text = self.create_text_widget(frame, wrap=tk.NONE, undo=False)
        self.prompt_version_diff_text.pack(fill=tk.BOTH, expand=True)
        self.configure_diff_tags(self.prompt_version_diff_text)

    def build_result_comparison_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text="Comparer les résultats")
        controls = ttk.Frame(frame)
        controls.pack(fill=tk.X, pady=(0, 8))
        self.result_compare_left_var = tk.StringVar(value="Résultat 1")
        self.result_compare_right_var = tk.StringVar(value="Résultat 2")
        choices = ["Résultat 1", "Résultat 2", "Résultat 3", "Document maintenant", "Transcription"]
        ttk.Label(controls, text="Texte A").pack(side=tk.LEFT)
        ttk.Combobox(
            controls,
            textvariable=self.result_compare_left_var,
            values=choices,
            width=24,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(controls, text="Texte B").pack(side=tk.LEFT)
        ttk.Combobox(
            controls,
            textvariable=self.result_compare_right_var,
            values=choices,
            width=24,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(4, 12))
        ttk.Button(controls, text="Comparer maintenant", command=self.compare_live_results).pack(side=tk.LEFT)
        self.result_diff_text = self.create_text_widget(frame, wrap=tk.NONE, undo=False)
        self.result_diff_text.pack(fill=tk.BOTH, expand=True)
        self.configure_diff_tags(self.result_diff_text)

    def build_quality_metrics_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text="Métriques locales")
        header = ttk.Frame(frame)
        header.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(
            header,
            text="Uniquement des nombres et états techniques sont conservés — aucun texte ni identifiant patient.",
        ).pack(side=tk.LEFT)
        ttk.Button(header, text="Actualiser", command=self.refresh_quality_metrics).pack(side=tk.RIGHT)
        columns = ("workflow", "prompt", "runs", "success", "errors", "latency", "correction")
        self.quality_metrics_tree = ttk.Treeview(frame, columns=columns, show="headings")
        headings = {
            "workflow": "Workflow",
            "prompt": "Prompt",
            "runs": "Générations",
            "success": "Succès",
            "errors": "Erreurs/annulations",
            "latency": "Durée moyenne",
            "correction": "Correction moyenne",
        }
        widths = {"workflow": 130, "prompt": 280, "runs": 90, "success": 70, "errors": 130, "latency": 120, "correction": 140}
        for key in columns:
            self.quality_metrics_tree.heading(key, text=headings[key])
            self.quality_metrics_tree.column(key, width=widths[key], anchor=tk.W if key in {"workflow", "prompt"} else tk.CENTER)
        self.quality_metrics_tree.pack(fill=tk.BOTH, expand=True)

    def refresh_quality_window(self) -> None:
        if not self.quality_window or not self.quality_window.winfo_exists():
            return
        prompts = list(self.prompt_manager.list_prompts()) + list(self.whisper_initial_prompt_manager.list_prompts())
        self.version_prompt_label_to_id = {}
        labels = []
        for prompt in prompts:
            label = f"{prompt.name} [{prompt.prompt_type}] • {prompt.id[:8]}"
            self.version_prompt_label_to_id[label] = prompt.id
            labels.append(label)
        self.version_prompt_combo["values"] = labels
        if labels and self.version_prompt_var.get() not in labels:
            self.version_prompt_var.set(labels[0])
        self.refresh_prompt_version_choices()
        self.refresh_quality_metrics()

    def refresh_prompt_version_choices(self) -> None:
        prompt_id = getattr(self, "version_prompt_label_to_id", {}).get(self.version_prompt_var.get(), "")
        versions = self.prompt_version_store.list_versions(prompt_id)
        self.version_label_to_entry = {
            f"{item.label} • {item.version_id[:6]}": item
            for item in versions
        }
        labels = list(self.version_label_to_entry)
        self.version_left_combo["values"] = labels
        self.version_right_combo["values"] = labels
        if labels:
            self.version_left_var.set(labels[-2] if len(labels) > 1 else labels[0])
            self.version_right_var.set(labels[-1])
            self.compare_prompt_versions()
        else:
            self.version_left_var.set("")
            self.version_right_var.set("")
            self.set_text(self.prompt_version_diff_text, "Aucune version enregistrée.", readonly=True)

    def compare_prompt_versions(self) -> None:
        left = getattr(self, "version_label_to_entry", {}).get(self.version_left_var.get())
        right = getattr(self, "version_label_to_entry", {}).get(self.version_right_var.get())
        if not left or not right:
            return
        diff = unified_text_diff(left.content, right.content, left_label=left.label, right_label=right.label)
        self.set_text(self.prompt_version_diff_text, diff, readonly=True)
        self.apply_diff_tags(self.prompt_version_diff_text)

    def restore_selected_prompt_version(self) -> None:
        version = getattr(self, "version_label_to_entry", {}).get(self.version_left_var.get())
        if not version:
            return
        if not messagebox.askyesno(
            "Restaurer un prompt",
            f"Restaurer la version du {version.at.replace('T', ' ')[:19]} ?\n"
            "La version actuelle restera conservée dans l’historique.",
            parent=self.quality_window,
        ):
            return
        manager = self.prompt_manager if self.prompt_manager.get(version.prompt_id) else self.whisper_initial_prompt_manager
        manager.update(version.prompt_id, content=version.content)
        self.refresh_common_prompt_combos()
        self._refresh_pdf_prompt_combo()
        self._refresh_whisper_initial_prompt_combo()
        self.refresh_quality_window()

    def live_comparison_text(self, label: str) -> str:
        mapping = {
            "Résultat 1": lambda: self.get_text(self.result_text),
            "Résultat 2": lambda: self.get_text(self.secondary_result_text),
            "Résultat 3": lambda: self.get_text(self.tertiary_result_text),
            "Document maintenant": lambda: self.get_text(self.document_now_result_text),
            "Transcription": self.get_clean_transcription_text,
        }
        getter = mapping.get(label)
        return getter() if getter else ""

    def compare_live_results(self) -> None:
        left_label = self.result_compare_left_var.get()
        right_label = self.result_compare_right_var.get()
        diff = unified_text_diff(
            self.live_comparison_text(left_label),
            self.live_comparison_text(right_label),
            left_label=left_label,
            right_label=right_label,
        )
        self.set_text(self.result_diff_text, diff, readonly=True)
        self.apply_diff_tags(self.result_diff_text)

    def configure_diff_tags(self, widget: tk.Text) -> None:
        widget.tag_configure("diff_add", foreground="#86efac")
        widget.tag_configure("diff_remove", foreground="#fca5a5")
        widget.tag_configure("diff_header", foreground="#93c5fd", font=("Consolas", 10, "bold"))

    def apply_diff_tags(self, widget: tk.Text) -> None:
        state = str(widget.cget("state"))
        if state == tk.DISABLED:
            widget.configure(state=tk.NORMAL)
        for line_number, line in enumerate(widget.get("1.0", tk.END).splitlines(), start=1):
            tag = ""
            if line.startswith(("+++", "---", "@@")):
                tag = "diff_header"
            elif line.startswith("+"):
                tag = "diff_add"
            elif line.startswith("-"):
                tag = "diff_remove"
            if tag:
                widget.tag_add(tag, f"{line_number}.0", f"{line_number}.end")
        if state == tk.DISABLED:
            widget.configure(state=tk.DISABLED)

    def refresh_quality_metrics(self) -> None:
        if not hasattr(self, "quality_metrics_tree"):
            return
        self.quality_metrics_tree.delete(*self.quality_metrics_tree.get_children())
        for item in self.quality_metrics_store.summary():
            latency = "—" if item["average_latency"] is None else f"{item['average_latency']:.2f} s"
            correction = (
                "—"
                if item["average_correction_percent"] is None
                else f"{item['average_correction_percent']:.1f} %"
            )
            self.quality_metrics_tree.insert(
                "",
                tk.END,
                values=(
                    item["workflow"],
                    item["prompt_name"],
                    item["generations"],
                    item["successes"],
                    item["errors"],
                    latency,
                    correction,
                ),
            )

    def quality_prompt_metadata(self, workflow: str) -> tuple[str, str, str]:
        prompt = None
        if workflow in {"document_1", "connector"}:
            prompt = self.prompt_manager.get(self.current_prompt_id())
        elif workflow == "document_2":
            prompt = self.prompt_manager.get(self.current_secondary_prompt_id())
        elif workflow == "document_3":
            prompt = self.prompt_manager.get(self.current_tertiary_prompt_id())
        elif workflow == "document_now":
            prompt = self.prompt_manager.get(self.current_document_now_prompt_id())
        elif workflow == "pdf_form":
            prompt = self.prompt_manager.get(self.current_pdf_prompt_id())
        if not prompt:
            return "", "Sans prompt", ""
        return prompt.id, prompt.name, content_hash(prompt.content)

    def record_generation_metric(
        self,
        workflow: str,
        source: str,
        *,
        status: str,
        elapsed_seconds: float | None = None,
        input_chars: int = 0,
        result_chars: int = 0,
        error: Exception | None = None,
    ) -> dict:
        prompt_id, prompt_name, prompt_version = self.quality_prompt_metadata(workflow)
        entry = self.quality_metrics_store.record_generation(
            workflow=workflow,
            source=source,
            prompt_id=prompt_id,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            status=status,
            elapsed_seconds=elapsed_seconds,
            input_chars=input_chars,
            result_chars=result_chars,
            error_type=type(error).__name__ if error else "",
        )
        if status == "success" and source:
            self.result_generation_metadata[source] = entry
        return entry

    def record_import_correction_metrics(self, source: str) -> None:
        for key in self.result_binding_sources(source):
            metadata = self.result_generation_metadata.get(key)
            original = self.generated_result_originals.get(key)
            if not metadata or original is None:
                continue
            final_text = self.get_result_text_by_source(key)
            final_hash = content_hash(final_text)
            if metadata.get("last_correction_hash") == final_hash:
                continue
            self.quality_metrics_store.record_correction(
                workflow=str(metadata.get("workflow") or key),
                source=key,
                generation_id=str(metadata.get("generation_id") or ""),
                prompt_id=str(metadata.get("prompt_id") or ""),
                prompt_name=str(metadata.get("prompt_name") or ""),
                generated_text=original,
                final_text=final_text,
            )
            metadata["last_correction_hash"] = final_hash

    def get_text(self, widget: tk.Text) -> str:
        state = str(widget.cget("state"))
        if state == tk.DISABLED:
            widget.configure(state=tk.NORMAL)
            value = widget.get("1.0", tk.END).strip()
            widget.configure(state=tk.DISABLED)
            return value
        return widget.get("1.0", tk.END).strip()

    def set_text(self, widget: tk.Text, value: str, *, readonly: bool = False) -> None:
        state = str(widget.cget("state"))
        if state == tk.DISABLED:
            widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value or "")
        if readonly or state == tk.DISABLED:
            widget.configure(state=tk.DISABLED)
        self.schedule_text_widget_dependents(widget)

    def schedule_text_widget_dependents(self, widget: tk.Text) -> None:
        if hasattr(self, "_message_source_widgets") and widget in self._message_source_widgets:
            self.schedule_message_refresh()
        if hasattr(self, "_secondary_message_source_widgets") and widget in self._secondary_message_source_widgets:
            self.schedule_secondary_message_refresh()
        if hasattr(self, "_tertiary_message_source_widgets") and widget in self._tertiary_message_source_widgets:
            self.schedule_tertiary_message_refresh()
        if hasattr(self, "_document_now_message_source_widgets") and widget in self._document_now_message_source_widgets:
            self.schedule_document_now_message_refresh()

    def get_clean_transcription_text(self) -> str:
        widget = self.transcription_text
        if hasattr(self, "corrected_transcription_text") and self.get_text(self.corrected_transcription_text).strip():
            widget = self.corrected_transcription_text
        return clean_transcription_text(self.get_text(widget), self.config.get("transcription_cleaning", {}))

    def close(self) -> None:
        self._closing = True
        self.cancel_all_lmstudio_requests()
        for job in (self._lmstudio_progress_job,):
            if job:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
        try:
            self.save_last_transcription()
        except Exception as exc:
            self.log_debug("error", "app", "transcription_draft_save_error", str(exc))
        try:
            self.save_all_runtime_settings("close")
        except Exception as exc:
            self.log_debug("error", "app", "runtime_settings_close_save_error", str(exc))
        self.set_recording_indicator(False)
        self.uninstall_fly_dictation_hotkey()
        if self._fly_recorder:
            try:
                self._fly_recorder.stop()
            except Exception:
                pass
        if self.session:
            self.session.stop()
        if self.server:
            self.server.stop()
        self.stop_tray_icon()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    _app = AssistantApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
