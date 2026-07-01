from __future__ import annotations

import csv
import io
import json
import re
import tempfile
import threading
import time
import tkinter as tk
import uuid
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from audio_recorder import AudioRecorder, PushToTalkRecorder, list_input_devices
from clipboard_tools import copy_text_to_clipboard
from debug_logger import DebugLogger
from history_manager import HistoryManager
from lmstudio_client import LmStudioClient
from local_server import LocalServer
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
from transcription_cleaner import WHISPER_MEDICAL_INITIAL_PROMPT, clean_transcription_text
from weda_context_manager import WedaContextManager
from weda_import_manager import WedaImportManager
from whisper_model_manager import WhisperModelManager, WhisperSettings, canonical_french_whisper_model_name


BASE_DIR = Path(__file__).resolve().parent
APP_NAME = "DrFloW"
APP_SUBTITLE = "Assistant local de consultation médicale :)"
APP_WINDOW_TITLE = f"{APP_NAME} - {APP_SUBTITLE}"
DEFAULT_WHISPER_INITIAL_PROMPT = WHISPER_MEDICAL_INITIAL_PROMPT
ABBREVIATIONS_PATH = BASE_DIR / "abbreviations.csv"
MESSAGE_ATTACHMENT_MAX_CHARS_PER_FILE = 30000
MESSAGE_ATTACHMENT_MAX_TOTAL_CHARS = 90000
LMSTUDIO_MAIN_SPINNER_KEY = "main"
LMSTUDIO_SPINNER_FRAMES = ("◐", "◓", "◑", "◒")
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
PDF_SOURCE_CHOICES = (
    "Contexte + transcription",
    "Transcription seule",
    "Résultat 1",
    "Résultat 2",
    "Résultat 3",
    "Résultat 1 + Résultat 2",
    "Résultat 1 + Résultat 2 + Résultat 3",
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
DEFAULT_FLY_WHISPER_INITIAL_PROMPT = (
    "Dictée médicale courte en français. Respecter les termes médicaux, médicaments, posologies, "
    "unités et abréviations usuelles. Ne pas traduire. Ne pas produire d’anglais."
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


class AssistantApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.base_window_title = APP_WINDOW_TITLE
        self.root.title(self.base_window_title)
        self.main_thread_id = threading.get_ident()
        self.config = load_json(BASE_DIR / "config.json", {})
        self.ensure_stt_config()
        self.ensure_message_composition_config()
        self.ensure_pdf_config()
        self.ensure_secondary_analysis_config()
        self.ensure_tertiary_analysis_config()
        self.root.geometry(self.get_saved_window_geometry())
        self.configure_material_theme()
        self.data_dir = BASE_DIR / "data"
        self.prompt_manager = PromptManager(BASE_DIR / "prompts.json")
        self.ensure_pdf_form_fill_prompt()
        self.ensure_secondary_analysis_prompt()
        self.ensure_tertiary_analysis_prompt()
        self.whisper_initial_prompt_manager = PromptManager(BASE_DIR / "whisper_initial_prompts.json")
        self.ensure_whisper_initial_prompts()
        pdf_config = self.config.get("pdf", {})
        self.pdf_template_manager = PdfTemplateManager(self.resolve_app_path(pdf_config.get("templates_dir"), "data/pdf_templates"))
        self.pdf_fill_manager = PdfFillManager()
        self.pdf_export_manager = PdfExportManager(self.resolve_app_path(pdf_config.get("outputs_dir"), "data/pdf_outputs"))
        self.context_manager = WedaContextManager(self.data_dir / "weda_context.json")
        self.import_manager = WedaImportManager(self.data_dir / "import_request.json")
        self.debug_logger = DebugLogger(self.data_dir / "debug.log.jsonl")
        self.history_manager = HistoryManager(
            self.data_dir / "history.jsonl",
            enabled=bool(self.config.get("ui", {}).get("save_history", True)),
        )
        self.model_manager = WhisperModelManager()
        self.stt_engine_manager = STTEngineManager(self.model_manager)
        self.transcriber = Transcriber(self.model_manager, self.get_stt_settings, stt_manager=self.stt_engine_manager)
        self.session: SegmentedDictationSession | None = None
        self.server: LocalServer | None = None
        self.prompt_name_to_id: dict[str, str] = {}
        self.secondary_prompt_name_to_id: dict[str, str] = {}
        self.tertiary_prompt_name_to_id: dict[str, str] = {}
        self.pdf_prompt_name_to_id: dict[str, str] = {}
        self.pdf_template_name_to_id: dict[str, str] = {}
        self.whisper_initial_prompt_name_to_id: dict[str, str] = {}
        self._window_geometry_save_job = None
        self._message_refresh_job = None
        self._secondary_message_refresh_job = None
        self._tertiary_message_refresh_job = None
        self.message_attachments: list[dict] = []
        self._message_source_widgets = []
        self._secondary_message_source_widgets = []
        self._tertiary_message_source_widgets = []
        self.secondary_running = False
        self.tertiary_running = False
        self._connector_lock = threading.Lock()
        self.connector_job: dict | None = None
        self.dictation_run_id = 0
        self._recording_indicator_active = False
        self._recording_indicator_source = ""
        self.last_stt_result: dict = {}
        self.last_stt_audio_path = ""
        self.stt_benchmark_results: list[dict] = []
        self.lmstudio_spinner_vars: dict[str, tk.StringVar] = {}
        self.lmstudio_spinner_jobs: dict[str, str] = {}
        self.lmstudio_spinner_frame_indexes: dict[str, int] = {}

        whisper_config = self.config.get("whisper", {})
        stt_config = self.config.get("stt", {})
        active_stt_engine = normalize_engine_id(stt_config.get("default_engine") or FASTER_WHISPER_ENGINE_ID)
        active_stt_backend_config = backend_config_for(self.config, active_stt_engine)
        connector_config = self.config.get("connector", {})
        fly_dictation_config = self.config.get("fly_dictation", {})
        message_composition_config = self.config.get("message_composition", {})
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
        self.stt_compare_faster_var = tk.BooleanVar(value=True)
        self.stt_compare_qwen_var = tk.BooleanVar(value=False)
        self.stt_compare_voxtral_var = tk.BooleanVar(value=False)
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
        self.whisper_initial_prompt_var = tk.StringVar(value="")
        self.include_prompt_var = tk.BooleanVar(value=bool(message_composition_config.get("include_prompt", True)))
        self.include_context_var = tk.BooleanVar(value=bool(message_composition_config.get("include_weda_context", True)))
        self.include_transcription_var = tk.BooleanVar(
            value=bool(message_composition_config.get("include_transcription", True))
        )
        self.context_delay_seconds_var = tk.StringVar(value=str(self.get_context_capture_delay_seconds()))
        self.connector_enabled_var = tk.BooleanVar(value=bool(connector_config.get("enabled", False)))
        self.connector_start_key_var = tk.StringVar(value=str(connector_config.get("start_key") or "PageUp"))
        self.connector_stop_key_var = tk.StringVar(value=str(connector_config.get("stop_key") or "PageDown"))
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
        self.result_destination_var = tk.StringVar(value="WEDA consultation")
        self.pdf_template_var = tk.StringVar(value="")
        self.pdf_prompt_var = tk.StringVar(value="")
        self.pdf_source_var = tk.StringVar(value=str(self.config.get("pdf", {}).get("preferred_source") or "Résultat 1 + Résultat 2"))
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
        self.whisper_initial_prompt_status_var = tk.StringVar(value="Prompt Whisper: aucun")
        self.abbreviations_status_var = tk.StringVar(value="Abréviations: non chargées")
        self.message_attachment_status_var = tk.StringVar(value="Fichiers: aucun")
        self.fly_dictation_status_var = tk.StringVar(value="Volée: initialisation")
        self.lmstudio_status_var = tk.StringVar(value="LM Studio: prêt")
        self.weda_patient_status_var = tk.StringVar(value="Patient WEDA: non reçu")
        self.import_status_var = tk.StringVar(value="Import WEDA: aucun")
        self.server_status_var = tk.StringVar(value="Serveur local: arrêté")
        self.log_status_var = tk.StringVar(value="Logs: prêts")
        self.pdf_status_var = tk.StringVar(value="PDF: aucun modèle")

        self._fly_dictation_lock = threading.Lock()
        self._fly_dictation_key_down = False
        self._fly_dictation_hook_handles = []
        self._fly_keyboard = None
        self._fly_recording = False
        self._fly_busy = False
        self._fly_recorder: PushToTalkRecorder | None = None

        self._build_ui()
        self.install_live_message_refresh()
        self._refresh_prompt_combo()
        self._refresh_secondary_prompt_combo()
        self._refresh_tertiary_prompt_combo()
        self._refresh_pdf_prompt_combo()
        self.refresh_pdf_template_combo()
        self._refresh_whisper_initial_prompt_combo()
        self.load_abbreviations_text()
        self.refresh_context_from_manager()
        self.start_server()
        self.install_fly_dictation_hotkey()
        self.preload_fly_dictation_model()
        self.root.bind("<Configure>", self.on_root_configure, add="+")
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

        ttk.Label(top, text="Modèle").pack(side=tk.LEFT)
        ttk.Combobox(
            top,
            textvariable=self.model_var,
            values=WHISPER_MODEL_CHOICES,
            width=16,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(4, 8))

        ttk.Label(top, text="Device").pack(side=tk.LEFT)
        ttk.Combobox(top, textvariable=self.device_var, values=("cpu", "cuda"), width=8, state="readonly").pack(
            side=tk.LEFT,
            padx=(4, 8),
        )

        ttk.Label(top, text="Compute").pack(side=tk.LEFT)
        ttk.Combobox(
            top,
            textvariable=self.compute_var,
            values=("int8", "int8_float16", "float16", "float32"),
            width=12,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(4, 8))

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
        ttk.Label(fly_bar, text="relâcher pour transcrire et coller").pack(side=tk.LEFT)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self.context_text = self._add_text_tab(
            "Contexte WEDA",
            buttons=[
                ("Rafraîchir", self.refresh_context_from_manager),
                ("Effacer contexte", self.clear_context),
            ],
            check_context=True,
        )
        self.transcription_text = self._add_text_tab(
            "Transcription",
            buttons=[
                ("Copier transcription", self.copy_transcription),
                ("Effacer transcription", self.clear_transcription),
            ],
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
                ("Réessayer", self.send_to_lmstudio),
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
                ("Réessayer Prompt 2", self.run_secondary_analysis_manual),
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
                ("Réessayer Prompt 3", self.run_tertiary_analysis_manual),
                ("Effacer Résultat 3", self.clear_tertiary_result),
                ("Importer Résultat 3 dans WEDA", self.prepare_weda_import_result_3),
            ],
            destination_controls=True,
            destination_buttons=[
                ("Utiliser Résultat 3 pour PDF structuré", self.use_tertiary_result_for_pdf),
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
        self.refresh_logs()

        self._message_source_widgets = [
            self.context_text,
            self.transcription_text,
            self.prompt_text,
        ]
        self._secondary_message_source_widgets = [
            self.context_text,
            self.transcription_text,
            self.prompt_text,
            self.result_text,
            self.secondary_prompt_text,
        ]
        self._tertiary_message_source_widgets = [
            self.context_text,
            self.transcription_text,
            self.prompt_text,
            self.result_text,
            self.secondary_prompt_text,
            self.secondary_result_text,
            self.tertiary_prompt_text,
        ]

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
        ttk.Checkbutton(controls, text="faster-whisper", variable=self.stt_compare_faster_var).grid(row=3, column=4, sticky=tk.W)
        ttk.Checkbutton(controls, text="Qwen3-ASR", variable=self.stt_compare_qwen_var).grid(row=3, column=5, sticky=tk.W)
        ttk.Checkbutton(controls, text="Voxtral", variable=self.stt_compare_voxtral_var).grid(row=3, column=6, sticky=tk.W)
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
        check_context: bool = False,
        message_controls: bool = False,
        message_document_index: int = 1,
        destination_controls: bool = False,
        destination_buttons=None,
    ) -> tk.Text:
        notebook = parent_notebook or self.notebook
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text=title)

        toolbar = ttk.Frame(frame)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
        for label, command in buttons or []:
            ttk.Button(toolbar, text=label, command=command).pack(side=tk.LEFT, padx=(0, 6))
        if message_controls:
            self.add_message_composition_controls(toolbar, document_index=message_document_index)
        if destination_controls:
            self.add_result_destination_controls(toolbar)
            for label, command in destination_buttons or []:
                ttk.Button(toolbar, text=label, command=command).pack(side=tk.LEFT, padx=(0, 6))
        if check_context:
            ttk.Checkbutton(
                toolbar,
                text="Inclure dans Message 1",
                variable=self.include_context_var,
                command=self.save_message_composition_settings,
            ).pack(side=tk.LEFT, padx=(8, 0))

        text = self.create_text_widget(frame, wrap=tk.WORD, undo=True, height=10)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(frame, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.configure(yscrollcommand=scrollbar.set)
        if readonly:
            text.configure(state=tk.DISABLED)
        return text

    def add_message_composition_controls(self, toolbar: ttk.Frame, document_index: int = 1) -> None:
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
            text="Envoyer à LM Studio",
            command=lambda index=document_index: self.send_document_to_lmstudio(index),
            style="Accent.TButton",
        ).pack(side=tk.LEFT, padx=(0, 6))
        self.register_lmstudio_spinner(toolbar, self.document_lmstudio_spinner_key(document_index))
        ttk.Label(toolbar, textvariable=self.message_attachment_status_var).pack(side=tk.LEFT, padx=(0, 6))

    def add_result_destination_controls(self, toolbar: ttk.Frame) -> None:
        ttk.Label(toolbar, text="Destination du résultat").pack(side=tk.LEFT, padx=(12, 4))
        combo = ttk.Combobox(
            toolbar,
            textvariable=self.result_destination_var,
            values=("WEDA consultation", "WEDA courrier", "Presse-papiers", "PDF structuré"),
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
        self.prompt_combo.bind("<<ComboboxSelected>>", lambda _event: self.load_selected_prompt())

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
        self.secondary_prompt_combo.bind("<<ComboboxSelected>>", lambda _event: self.load_selected_secondary_prompt())

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
        self.tertiary_prompt_combo.bind("<<ComboboxSelected>>", lambda _event: self.load_selected_tertiary_prompt())

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
        ):
            ttk.Button(toolbar, text=label, command=command).pack(side=tk.LEFT, padx=(0, 6))

        text = self.create_text_widget(frame, wrap=tk.WORD, undo=True, height=10)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(frame, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.configure(yscrollcommand=scrollbar.set)
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

        for label, command in (
            ("Importer modèle PDF", self.import_pdf_template),
            ("Renommer", self.rename_pdf_template),
            ("Supprimer", self.delete_pdf_template),
            ("Enregistrer champ", self.save_selected_pdf_field),
            ("Générer valeurs avec Gemma", self.generate_pdf_values_with_gemma),
            ("Copier JSON", self.copy_pdf_json),
            ("Remplir / exporter PDF", self.fill_and_export_pdf),
            ("Ouvrir PDF final", self.open_last_pdf_output),
            ("Purger historique local", self.purge_local_history),
        ):
            ttk.Button(
                toolbar,
                text=label,
                command=command,
                style="Accent.TButton" if label in {"Générer valeurs avec Gemma", "Remplir / exporter PDF"} else "TButton",
            ).pack(side=tk.LEFT, padx=(0, 6))

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
        self.pdf_template_combo.bind("<<ComboboxSelected>>", lambda _event: self.load_selected_pdf_template())

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

    def on_result_destination_changed(self) -> None:
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
        self.config.setdefault("pdf", {})["default_prompt_id"] = prompt.id
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

        selected_label = next(
            (label for label, template_id in self.pdf_template_name_to_id.items() if template_id == selected_id),
            labels[0],
        )
        self.pdf_template_var.set(selected_label)
        self.load_selected_pdf_template()

    def current_pdf_template_id(self) -> str:
        return self.pdf_template_name_to_id.get(self.pdf_template_var.get(), "")

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
        pdf_config = self.config.setdefault("pdf", {})
        source = self.pdf_source_var.get() or "Résultat 1 + Résultat 2"
        if source not in PDF_SOURCE_CHOICES:
            source = "Résultat 1 + Résultat 2"
            self.pdf_source_var.set(source)
        pdf_config["preferred_source"] = source
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
                "pdf_fields": json.dumps(self.pdf_current_fields, ensure_ascii=False, indent=2),
                "pdf_schema": json.dumps(schema, ensure_ascii=False, indent=2),
            }
        )
        return self.prompt_manager.render_prompt(prompt_content, variables)

    def generate_pdf_values_with_gemma(self) -> None:
        if not self.current_pdf_template_id():
            messagebox.showwarning("PDF structuré", "Sélectionne ou importe d’abord un modèle PDF.", parent=self.root)
            return
        try:
            message = self.build_pdf_lmstudio_message()
        except Exception as exc:
            messagebox.showerror("PDF structuré", str(exc), parent=self.root)
            return
        self.set_text(self.sent_message_text, message, readonly=True)
        self.result_destination_var.set("PDF structuré")
        self.lmstudio_status_var.set("LM Studio: génération JSON PDF")
        self.pdf_status_var.set("PDF: demande Gemma en cours")
        pdf_config = self.config.get("pdf", {})
        client = self.build_lmstudio_client(max_tokens=int(pdf_config.get("max_tokens") or 8192))
        response_format = self.build_pdf_response_format()

        def worker():
            try:
                response = client.chat(message, response_format=response_format)
                self.root.after(0, self.on_pdf_lmstudio_response, response, message)
            except Exception as exc:
                self.root.after(0, self.on_pdf_lmstudio_error, exc)

        threading.Thread(target=worker, name="lmstudio-pdf-form", daemon=True).start()

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

    def on_pdf_lmstudio_response(self, response, sent_message: str) -> None:
        try:
            parsed_json = parse_json_object_result(response.text)
            raw_values = parsed_json.values
            values, issues = validate_pdf_field_values(raw_values, self.pdf_current_fields)
        except Exception as exc:
            self.lmstudio_status_var.set("LM Studio: JSON PDF invalide")
            self.pdf_status_var.set("PDF: réponse JSON invalide")
            self.set_text(self.pdf_json_text, response.text)
            messagebox.showerror("JSON PDF", str(exc), parent=self.root)
            return

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
                "pdf_source": self.pdf_source_var.get(),
                "pdf_template_id": self.pdf_current_template_id,
                "pdf_template_name": self.pdf_current_metadata.get("name", ""),
                "pdf_fields": self.pdf_current_fields,
                "pdf_generated_json": values,
                "pdf_export_status": "preview",
                "status": "pdf_values_generated",
            }
        )

    def on_pdf_lmstudio_error(self, error: Exception) -> None:
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

    def fill_and_export_pdf(self) -> None:
        if not self.current_pdf_template_id() or not self.pdf_current_fields:
            messagebox.showwarning("PDF structuré", "Sélectionne un modèle PDF.", parent=self.root)
            return
        if not self.parse_pdf_json_from_editor():
            return
        if not self.pdf_current_values:
            messagebox.showwarning("PDF structuré", "Aucune valeur PDF à remplir.", parent=self.root)
            return

        issue_lines = [f"- {issue.get('field')}: {issue.get('message')}" for issue in self.pdf_current_issues]
        details = "\n".join(issue_lines[:8])
        if len(issue_lines) > 8:
            details += f"\n... +{len(issue_lines) - 8} autre(s) alerte(s)"

        pdf_config = self.config.get("pdf", {})
        if bool(pdf_config.get("require_manual_validation", True)):
            message = "Générer le PDF final avec les valeurs affichées ?\n\nLe modèle original restera intact."
            if details:
                message += "\n\nAlertes à vérifier :\n" + details
            if not messagebox.askyesno("Validation humaine requise", message, parent=self.root):
                return

        context = self.context_manager.get_latest()
        patient_identity = context.patient_identity if context else ""
        template_name = str(self.pdf_current_metadata.get("name") or self.pdf_current_template_id)
        output_path = self.pdf_export_manager.build_output_path(
            template_name=template_name,
            patient_identity=patient_identity,
        )

        try:
            result = self.pdf_fill_manager.fill_pdf(
                self.pdf_current_metadata.get("template_path") or self.pdf_template_manager.template_pdf_path(self.pdf_current_template_id),
                self.pdf_current_values,
                output_path,
                fields=self.pdf_current_fields,
            )
        except Exception as exc:
            self.pdf_status_var.set("PDF: export impossible")
            messagebox.showerror("PDF structuré", str(exc), parent=self.root)
            return

        self.pdf_last_output_path = str(result.output_path)
        self.pdf_status_var.set(f"PDF: exporté {result.output_path.name}")
        self.history_manager.append(
            {
                **self.current_stt_history_payload(),
                "prompt_name": self.pdf_prompt_var.get(),
                "prompt_type": "pdf_form_fill",
                "pdf_template_id": self.pdf_current_template_id,
                "pdf_template_name": template_name,
                "pdf_fields": self.pdf_current_fields,
                "pdf_generated_json": self.pdf_current_values,
                "pdf_final_path": str(result.output_path),
                "pdf_export_status": "exported",
                "pdf_warnings": result.warnings,
                "result_1": self.get_text(self.result_text),
                "result_2": self.get_text(self.secondary_result_text),
                "result_3": self.get_text(self.tertiary_result_text) if hasattr(self, "tertiary_result_text") else "",
                "pdf_source": self.pdf_source_var.get(),
                "status": "pdf_exported",
            }
        )
        if result.warnings:
            self.log_debug("warning", "pdf", "pdf_export_warnings", "PDF exporté avec alertes.", {"warnings": result.warnings})
        if bool(pdf_config.get("open_after_export", True)):
            self.open_last_pdf_output()

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
        self.include_prompt_var.trace_add("write", lambda *_args: self.schedule_message_refresh())
        self.include_prompt_var.trace_add("write", lambda *_args: self.schedule_secondary_message_refresh())
        self.include_prompt_var.trace_add("write", lambda *_args: self.schedule_tertiary_message_refresh())
        self.include_context_var.trace_add("write", lambda *_args: self.schedule_message_refresh())
        self.include_context_var.trace_add("write", lambda *_args: self.schedule_secondary_message_refresh())
        self.include_context_var.trace_add("write", lambda *_args: self.schedule_tertiary_message_refresh())
        self.include_transcription_var.trace_add("write", lambda *_args: self.schedule_message_refresh())
        self.include_transcription_var.trace_add("write", lambda *_args: self.schedule_secondary_message_refresh())
        self.include_transcription_var.trace_add("write", lambda *_args: self.schedule_tertiary_message_refresh())
        self.secondary_enabled_var.trace_add("write", lambda *_args: self.schedule_secondary_message_refresh())
        self.secondary_enabled_var.trace_add("write", lambda *_args: self.schedule_tertiary_message_refresh())
        self.tertiary_enabled_var.trace_add("write", lambda *_args: self.schedule_tertiary_message_refresh())
        self.schedule_message_refresh()
        self.schedule_secondary_message_refresh()
        self.schedule_tertiary_message_refresh()

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

    def save_message_composition_settings(self) -> None:
        message_config = self.config.setdefault("message_composition", {})
        message_config["include_prompt"] = bool(self.include_prompt_var.get())
        message_config["include_weda_context"] = bool(self.include_context_var.get())
        message_config["include_transcription"] = bool(self.include_transcription_var.get())
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
        message = self.prompt_manager.render_prompt(prompt_content, variables) if prompt_content.strip() else ""
        message = self.append_missing_source_sections(prompt_content, message, variables)
        message = self.append_message_attachment_section(prompt_content, message, variables)
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

        message = self.prompt_manager.render_prompt(prompt_content, variables) if prompt_content.strip() else ""
        message = self.append_missing_source_sections(prompt_content, message, variables)
        message = self.append_message_attachment_section(prompt_content, message, variables)
        return message, variables

    def send_document_to_lmstudio(self, document_index: int) -> None:
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

        def worker():
            try:
                response = client.chat(message)
                self.root.after(0, self.on_document_lmstudio_response, document_index, response, message)
            except Exception as exc:
                self.root.after(0, self.on_document_lmstudio_error, document_index, exc, message)

        threading.Thread(target=worker, name=f"lmstudio-document-{document_index}-request", daemon=True).start()

    def on_document_lmstudio_response(self, document_index: int, response, sent_message: str) -> None:
        self.stop_lmstudio_spinner(self.document_lmstudio_spinner_key(document_index))
        result_text = self.apply_abbreviations_to_lmstudio_result(response.text, f"Résultat {document_index}")
        result_widget = self.document_result_widget(document_index)
        self.set_text(result_widget, result_text)
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
                "result_length": len(result_text or ""),
            },
        )
        if document_index == 1:
            self.schedule_secondary_message_refresh()
            self.schedule_tertiary_message_refresh()
        elif document_index == 2:
            self.schedule_tertiary_message_refresh()
        self.append_independent_document_history(document_index, sent_message, result_text)

    def on_document_lmstudio_error(self, document_index: int, error: Exception, sent_message: str) -> None:
        self.stop_lmstudio_spinner(self.document_lmstudio_spinner_key(document_index))
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
                "transcription": self.get_clean_transcription_text(),
                "weda_context": self.get_text(self.context_text),
            }
        )

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

        if self.include_prompt_var.get():
            message = self.prompt_manager.render_prompt(prompt_2_content, variables)
            message = append_missing_secondary_sections(prompt_2_content, message, variables)
        else:
            source_sections = []
            for variable_name, title in (
                ("current_date", "DATE DU JOUR"),
                ("patient_identity", "PATIENT"),
                ("weda_context", "CONTEXTE WEDA"),
                ("transcription", "TRANSCRIPTION INITIALE"),
                ("result_1", "RÉSULTAT 1"),
            ):
                value = str(variables.get(variable_name) or "").strip()
                if value:
                    source_sections.append(f"{title} :\n{value}")
            message = "\n\n".join(source_sections)
        message = self.append_message_attachment_section(prompt_2_content, message, variables)
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

        if self.include_prompt_var.get():
            message = self.prompt_manager.render_prompt(prompt_3_content, variables)
            message = append_missing_tertiary_sections(prompt_3_content, message, variables)
        else:
            source_sections = []
            for variable_name, title in (
                ("current_date", "DATE DU JOUR"),
                ("patient_identity", "PATIENT"),
                ("weda_context", "CONTEXTE WEDA"),
                ("transcription", "TRANSCRIPTION INITIALE"),
                ("result_1", "RÉSULTAT 1"),
                ("result_2", "RÉSULTAT 2"),
            ):
                value = str(variables.get(variable_name) or "").strip()
                if value:
                    source_sections.append(f"{title} :\n{value}")
            message = "\n\n".join(source_sections)
        message = self.append_message_attachment_section(prompt_3_content, message, variables)
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
        stt_config = self.config.setdefault("stt", {})
        stt_config["default_engine"] = engine_id
        stt_config["allow_experimental_engines"] = bool(self.stt_allow_experimental_var.get())
        stt_config["keep_audio_for_benchmark"] = bool(self.stt_keep_audio_var.get())
        stt_config["auto_fallback_to_faster_whisper"] = bool(self.stt_auto_fallback_var.get())
        stt_config["show_engine_warnings"] = bool(self.stt_show_warnings_var.get())
        if hasattr(self, "stt_context_bias_text"):
            stt_config["stt_context_bias"] = self.get_text(self.stt_context_bias_text).strip()
        if hasattr(self, "stt_speaker_map_text"):
            stt_config["speaker_map"] = self.parse_stt_speaker_map(self.get_text(self.stt_speaker_map_text))

        faster = self.config.setdefault("faster_whisper", {})
        whisper = self.config.setdefault("whisper", {})
        if engine_id == FASTER_WHISPER_ENGINE_ID:
            selected_model = canonical_french_whisper_model_name(
                self.stt_model_var.get() or self.model_var.get() or "medium"
            )
            selected_device = self.stt_device_var.get() or self.device_var.get() or "cpu"
            self.stt_model_var.set(selected_model)
            self.model_var.set(selected_model)
            self.device_var.set(selected_device)
            faster.update(
                {
                    "enabled": True,
                    "model": selected_model,
                    "device": selected_device,
                    "compute_type": self.compute_var.get() or "int8",
                    "language": "fr",
                    "task": "transcribe",
                    "force_language": True,
                    "disable_language_detection": True,
                    "condition_on_previous_text": False,
                    "initial_prompt": self.get_active_whisper_initial_prompt_text() or DEFAULT_WHISPER_INITIAL_PROMPT,
                }
            )
            whisper["default_model"] = faster["model"]
            whisper["device"] = faster["device"]
            whisper["compute_type"] = faster["compute_type"]
            whisper["language"] = "fr"
            whisper["task"] = "transcribe"
            whisper["condition_on_previous_text"] = False
        else:
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
            "segment_seconds": faster.get("segment_seconds", legacy.get("segment_seconds", 15)),
            "overlap_seconds": faster.get("overlap_seconds", legacy.get("overlap_seconds", 1)),
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
                "initial_prompt": str(
                    fly_config.get("initial_prompt", DEFAULT_FLY_WHISPER_INITIAL_PROMPT)
                    or ""
                ),
            }
        )
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
        self.config.setdefault("whisper", {})["input_device"] = value
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
        return {
            "enabled": enabled,
            "key": key,
            "model": model,
            "min_seconds": max(0.05, min(5.0, min_seconds)),
            "paste_delay_ms": max(0, min(1000, paste_delay_ms)),
        }

    def save_fly_dictation_settings(self) -> None:
        settings = self.get_fly_dictation_settings()
        self.fly_dictation_key_var.set(settings["key"])
        self.fly_dictation_model_var.set(settings["model"])
        fly_config = self.config.setdefault("fly_dictation", {})
        fly_config["enabled"] = settings["enabled"]
        fly_config["key"] = settings["key"]
        fly_config["model"] = settings["model"]
        fly_config.setdefault("min_seconds", settings["min_seconds"])
        fly_config.setdefault("paste_delay_ms", settings["paste_delay_ms"])
        fly_config.setdefault("beam_size", 1)
        fly_config.setdefault("best_of", 1)
        fly_config.setdefault("temperature", 0.0)
        fly_config.setdefault("condition_on_previous_text", False)
        fly_config.setdefault("vad_filter", False)
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
                self.model_manager.load(whisper_settings)
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

        settings = self.get_fly_dictation_settings()
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
            args=(audio, recorder.sample_rate, recorder.channels, duration_seconds, fly_whisper_settings),
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
        temp_dir = None
        audio_path = None
        auto_delete_audio = bool(self.config.get("security", {}).get("auto_delete_audio", True))
        try:
            try:
                result = self.transcriber.transcribe_audio_array(
                    audio,
                    sample_rate=sample_rate,
                    channels=channels,
                    segment_index=0,
                    settings_override=whisper_settings,
                )
            except Exception as memory_exc:
                self.log_debug(
                    "warning",
                    "app",
                    "fly_dictation_memory_transcribe_fallback",
                    "Transcription directe depuis la mémoire impossible, fallback WAV.",
                    {"error": str(memory_exc), "sample_rate": sample_rate, "channels": channels},
                )
                temp_dir = Path(tempfile.mkdtemp(prefix="gemma_weda_fly_"))
                audio_path = temp_dir / "dictee_volee.wav"
                AudioRecorder(sample_rate=sample_rate, channels=channels).write_wav(audio_path, audio)
                result = self.transcriber.transcribe_file(
                    audio_path,
                    segment_index=0,
                    settings_override=whisper_settings,
                )
            self.root.after(0, self.on_fly_dictation_result, result, duration_seconds)
        except Exception as exc:
            self.root.after(0, self.on_fly_dictation_error, exc)
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

        copied = copy_text_to_clipboard(value, self.root)
        if not copied:
            self.fly_dictation_status_var.set("Volée: copie impossible")
            self.log_debug("error", "app", "fly_dictation_clipboard_error", "Impossible de copier la dictée à la volée.")
            return

        delay_ms = int(self.get_fly_dictation_settings().get("paste_delay_ms", 0))
        self.fly_dictation_status_var.set("Volée: collage en cours")
        self.root.after(delay_ms, lambda: self.send_fly_dictation_paste(value))

    def send_fly_dictation_paste(self, text: str) -> None:
        try:
            keyboard_module = self._fly_keyboard
            if keyboard_module is None:
                import keyboard as keyboard_module
            keyboard_module.send("ctrl+v")
            self.fly_dictation_status_var.set(f"Volée: texte collé ({len(text.split())} mot(s))")
            self.log_debug(
                "info",
                "app",
                "fly_dictation_pasted",
                "Dictée à la volée copiée puis collée dans la cible active.",
                {"text_length": len(text or "")},
            )
        except Exception as exc:
            self.fly_dictation_status_var.set("Volée: texte copié, collage impossible")
            self.log_debug("error", "app", "fly_dictation_paste_error", str(exc))

    def on_fly_dictation_error(self, error: Exception) -> None:
        self._fly_busy = False
        self.fly_dictation_status_var.set("Volée: erreur transcription")
        self.log_debug("error", "app", "fly_dictation_error", str(error))
        messagebox.showerror("Dictée à la volée", str(error), parent=self.root)

    def save_connector_settings(self) -> None:
        start_key = self.connector_start_key_var.get() or "PageUp"
        stop_key = self.connector_stop_key_var.get() or "PageDown"
        if start_key == stop_key:
            messagebox.showwarning(
                "Connecteur WEDA",
                "La touche de déclenchement et la touche d’arrêt doivent être différentes.",
                parent=self.root,
            )
            stop_key = "PageDown" if start_key != "PageDown" else "PageUp"
            self.connector_stop_key_var.set(stop_key)

        connector_config = self.config.setdefault("connector", {})
        connector_config["enabled"] = bool(self.connector_enabled_var.get())
        connector_config["start_key"] = start_key
        connector_config["stop_key"] = stop_key
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

    def stop_dictation(self) -> None:
        if self.session and self.session.is_running():
            self.session.stop()
        self.set_dictation_buttons_running(False)
        self.set_recording_indicator(False)
        self.micro_status_var.set("Micro: arrêt demandé")

    def set_dictation_buttons_running(self, running: bool) -> None:
        state_start = tk.DISABLED if running else tk.NORMAL
        state_stop = tk.NORMAL if running else tk.DISABLED
        self.continue_dictation_button.configure(state=state_start)
        self.new_dictation_button.configure(state=state_start)
        self.stop_dictation_button.configure(state=state_stop)

    def reset_session_fields(self) -> None:
        self.dictation_run_id += 1
        if self.session and self.session.is_running():
            self.session.stop()
        self.set_recording_indicator(False)

        self.context_manager.clear()
        self.import_manager.clear()
        self.set_text(self.context_text, "")
        self.set_text(self.transcription_text, "")
        self.set_text(self.result_text, "")
        self.set_text(self.sent_message_text, "", readonly=True)
        self.set_text(self.secondary_result_text, "")
        self.set_text(self.secondary_sent_message_text, "", readonly=True)
        self.set_text(self.tertiary_result_text, "")
        self.set_text(self.tertiary_sent_message_text, "", readonly=True)
        self.weda_patient_status_var.set("Patient WEDA: non reçu")
        self.transcription_status_var.set("Transcription prête")
        self.lmstudio_status_var.set("LM Studio: prêt")
        self.update_secondary_status()
        self.update_tertiary_status()
        self.import_status_var.set("Import WEDA: aucun")
        self.schedule_message_refresh()
        self.schedule_secondary_message_refresh()
        self.schedule_tertiary_message_refresh()
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
            self.call_ui_sync(self.stop_dictation)
        except Exception as exc:
            job = self.set_connector_job({"status": "error", "message": str(exc), "error": str(exc)})
            self.log_debug("error", "connector", "connector_stop_error", str(exc), job)
            return job

        threading.Thread(
            target=self.run_connector_stop_worker,
            args=(job_id, payload),
            name="weda-connector-stop",
            daemon=True,
        ).start()
        return job

    def run_connector_stop_worker(self, job_id: str, payload: dict) -> None:
        try:
            settings = self.get_connector_settings()
            grace_seconds = float(settings.get("stop_transcription_grace_seconds", 2))
            if grace_seconds > 0:
                self.set_connector_job({
                    "status": "waiting_transcription_flush",
                    "message": f"Attente du dernier segment Whisper ({grace_seconds:.1f}s).",
                })
                time.sleep(grace_seconds)

            self.set_connector_job({"status": "generating", "message": "Envoi à LM Studio."})
            self.call_ui_sync(self.refresh_context_from_manager, timeout_seconds=10)
            message = self.call_ui_sync(lambda: self.refresh_sent_message().strip(), timeout_seconds=10)
            if not message:
                raise RuntimeError("Message LM Studio vide après arrêt de la dictée.")

            response = self.build_lmstudio_client().chat(message)
            context = self.context_manager.get_latest()
            patient_id = context.patient_id if context else str(payload.get("patient_id") or "")
            patient_identity = context.patient_identity if context else str(payload.get("patient_identity") or "")
            request = self.import_manager.prepare_result(
                response.text,
                patient_id=patient_id,
                patient_identity=patient_identity,
                destination="connector_auto",
            )

            def ui_done():
                self.set_text(self.result_text, response.text)
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
                        "lmstudio_result": response.text,
                        "status": "connector_result_ready",
                        "patient_id": patient_id,
                        "patient_identity": patient_identity,
                    }
                )

            self.call_ui_sync(ui_done, timeout_seconds=10)
            job = self.set_connector_job(
                {
                    "status": "result_ready",
                    "message": "Résultat prêt pour insertion WEDA.",
                    "request_id": request.id,
                    "patient_id": patient_id,
                    "patient_identity": patient_identity,
                    "result_length": len(response.text or ""),
                    "elapsed_seconds": response.elapsed_seconds,
                    "auto_return_home": bool(settings.get("auto_return_home", True)),
                }
            )
            self.log_debug("info", "connector", "connector_result_ready", "Résultat connecteur prêt.", job)
        except Exception as exc:
            job = self.set_connector_job({"status": "error", "message": str(exc), "error": str(exc)})
            self.log_debug("error", "connector", "connector_generation_error", str(exc), job)

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
        if result.text:
            self.append_transcription_line(result.text)
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
            },
        )

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
            "speech_segment_without_text": "segment sans texte",
        }
        return labels.get(reason, reason or "aucun texte")

    def on_session_error(self, error: Exception, run_id: int) -> None:
        if run_id != self.dictation_run_id:
            return
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
        }
        self._refresh_prompt_combo(selected_id if target == "primary" else current_ids.get("primary") or None)
        self._refresh_secondary_prompt_combo(selected_id if target == "secondary" else current_ids.get("secondary") or None)
        self._refresh_tertiary_prompt_combo(selected_id if target == "tertiary" else current_ids.get("tertiary") or None)

    def is_protected_common_prompt(self, prompt_id: str, *, title: str = "Prompt") -> bool:
        protected = {
            SECONDARY_ANALYSIS_PROMPT_ID: "Le prompt secondaire par défaut ne peut pas être supprimé.",
            TERTIARY_ANALYSIS_PROMPT_ID: "Le prompt tertiaire par défaut ne peut pas être supprimé.",
        }
        message = protected.get(prompt_id)
        if not message:
            return False
        messagebox.showwarning(title, message, parent=self.root)
        return True

    def reset_prompt_references_after_delete(self, prompt_id: str) -> None:
        changed = False
        secondary_config = normalize_secondary_analysis_config(self.config.get("secondary_analysis", {}))
        if secondary_config.get("default_prompt_id") == prompt_id:
            secondary_config["default_prompt_id"] = SECONDARY_ANALYSIS_PROMPT_ID
            self.config["secondary_analysis"] = secondary_config
            changed = True
        tertiary_config = normalize_tertiary_analysis_config(self.config.get("tertiary_analysis", {}))
        if tertiary_config.get("default_prompt_id") == prompt_id:
            tertiary_config["default_prompt_id"] = TERTIARY_ANALYSIS_PROMPT_ID
            self.config["tertiary_analysis"] = tertiary_config
            changed = True
        if changed:
            save_json(BASE_DIR / "config.json", self.config)

    def _refresh_prompt_combo(self, selected_id: str | None = None) -> None:
        prompts = self.list_common_lmstudio_prompts()
        self.prompt_name_to_id = {prompt.name: prompt.id for prompt in prompts}
        self.prompt_combo["values"] = [prompt.name for prompt in prompts] if hasattr(self, "prompt_combo") else []

        selected = self.prompt_manager.get(selected_id) if selected_id else self.prompt_manager.get_default("generic")
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
        self.refresh_common_prompt_combos(target="primary", selected_id=prompt_id)

    def _refresh_secondary_prompt_combo(self, selected_id: str | None = None) -> None:
        prompts = self.list_common_lmstudio_prompts()
        self.secondary_prompt_name_to_id = {prompt.name: prompt.id for prompt in prompts}
        if hasattr(self, "secondary_prompt_combo"):
            self.secondary_prompt_combo["values"] = [prompt.name for prompt in prompts]

        secondary_config = normalize_secondary_analysis_config(self.config.get("secondary_analysis", {}))
        selected = self.prompt_manager.get(selected_id) if selected_id else None
        if selected is None:
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

        tertiary_config = normalize_tertiary_analysis_config(self.config.get("tertiary_analysis", {}))
        selected = self.prompt_manager.get(selected_id) if selected_id else None
        if selected is None:
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
        self.config["tertiary_analysis"] = tertiary_config
        try:
            save_json(BASE_DIR / "config.json", self.config)
        except Exception as exc:
            self.log_debug("error", "app", "tertiary_default_prompt_save_error", str(exc))
        self.refresh_common_prompt_combos(target="tertiary", selected_id=prompt.id)

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
        self._refresh_whisper_initial_prompt_combo(prompt.id)
        self.whisper_initial_prompt_status_var.set(f"Prompt Whisper enregistré: {prompt.name}")
        self.log_debug(
            "info",
            "app",
            "whisper_initial_prompt_saved",
            "Prompt initial Whisper enregistré.",
            {"prompt_name": prompt.name, "prompt_length": len(prompt.content or "")},
        )

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

    def is_secondary_auto_run_enabled(self) -> bool:
        secondary_config = normalize_secondary_analysis_config(self.config.get("secondary_analysis", {}))
        return bool(self.secondary_enabled_var.get() and secondary_config.get("auto_run_after_primary", True))

    def is_tertiary_auto_run_enabled(self) -> bool:
        tertiary_config = normalize_tertiary_analysis_config(self.config.get("tertiary_analysis", {}))
        return bool(self.tertiary_enabled_var.get() and tertiary_config.get("auto_run_after_secondary", True))

    def send_to_lmstudio(self) -> None:
        message = self.refresh_sent_message().strip()
        if not message:
            messagebox.showwarning("LM Studio", "Le message à envoyer est vide.", parent=self.root)
            return

        lm_config = self.config.get("lmstudio", {})
        client = self.build_lmstudio_client()
        self.lmstudio_status_var.set("LM Studio: envoi en cours")
        self.start_lmstudio_spinner(LMSTUDIO_MAIN_SPINNER_KEY)
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

        def worker():
            try:
                response = client.chat(message)
                self.root.after(0, self.on_lmstudio_response, response, message)
            except Exception as exc:
                self.root.after(0, self.on_lmstudio_error, exc)

        threading.Thread(target=worker, name="lmstudio-request", daemon=True).start()

    def on_lmstudio_response(self, response, sent_message: str) -> None:
        self.stop_lmstudio_spinner(LMSTUDIO_MAIN_SPINNER_KEY)
        result_text = self.apply_abbreviations_to_lmstudio_result(response.text, "Résultat 1")
        self.set_text(self.result_text, result_text)
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
                "result_length": len(result_text or ""),
            },
        )
        if self.is_secondary_auto_run_enabled():
            self.run_secondary_analysis(
                trigger="auto",
                primary_sent_message=sent_message,
                primary_result=result_text,
            )
            return

        status = "disabled" if not self.secondary_enabled_var.get() else "skipped_no_result_1"
        self.append_analysis_history(
            sent_message_1=sent_message,
            result_1=result_text,
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
            self.set_text(self.result_text, primary_result)

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
        client = self.build_lmstudio_client()
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

        def worker():
            try:
                response = client.chat(message_2)
                self.root.after(
                    0,
                    self.on_secondary_lmstudio_response,
                    response,
                    message_2,
                    sent_message_1,
                    result_1,
                    trigger,
                )
            except Exception as exc:
                self.root.after(
                    0,
                    self.on_secondary_lmstudio_error,
                    exc,
                    message_2,
                    sent_message_1,
                    result_1,
                    trigger,
                )

        threading.Thread(target=worker, name="lmstudio-secondary-request", daemon=True).start()

    def on_secondary_lmstudio_response(
        self,
        response,
        sent_message_2: str,
        sent_message_1: str,
        result_1: str,
        trigger: str,
    ) -> None:
        self.secondary_running = False
        result_2_text = self.apply_abbreviations_to_lmstudio_result(response.text, "Résultat 2")
        self.set_text(self.secondary_result_text, result_2_text)
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
                "result_2_length": len(result_2_text or ""),
            },
        )
        self.schedule_tertiary_message_refresh()
        if self.is_tertiary_auto_run_enabled():
            self.run_tertiary_analysis(
                trigger="auto",
                sent_message_1=sent_message_1,
                result_1=result_1,
                sent_message_2=sent_message_2,
                result_2=result_2_text,
                prompt_2_status="manual_run" if trigger == "manual_run" else "success",
            )
            return
        self.append_analysis_history(
            sent_message_1=sent_message_1,
            result_1=result_1,
            prompt_2_status="manual_run" if trigger == "manual_run" else "success",
            message_sent_2=sent_message_2,
            result_2=result_2_text,
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
            self.set_text(self.result_text, result_1_text)
        if result_2 is not None:
            self.set_text(self.secondary_result_text, result_2_text)

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
        client = self.build_lmstudio_client()
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

        def worker():
            try:
                response = client.chat(message_3)
                self.root.after(
                    0,
                    self.on_tertiary_lmstudio_response,
                    response,
                    message_3,
                    sent_message_1_text,
                    result_1_text,
                    sent_message_2_text,
                    result_2_text,
                    prompt_2_status,
                    trigger,
                )
            except Exception as exc:
                self.root.after(
                    0,
                    self.on_tertiary_lmstudio_error,
                    exc,
                    message_3,
                    sent_message_1_text,
                    result_1_text,
                    sent_message_2_text,
                    result_2_text,
                    prompt_2_status,
                    trigger,
                )

        threading.Thread(target=worker, name="lmstudio-tertiary-request", daemon=True).start()

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
        result_3_text = self.apply_abbreviations_to_lmstudio_result(response.text, "Résultat 3")
        self.set_text(self.tertiary_result_text, result_3_text)
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
                "result_3_length": len(result_3_text or ""),
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
            result_3=result_3_text,
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
        self.lmstudio_status_var.set("LM Studio: erreur")
        if self.secondary_enabled_var.get():
            self.secondary_status_var.set("Prompt 2: non lancé, erreur Prompt 1")
        if self.tertiary_enabled_var.get():
            self.tertiary_status_var.set("Prompt 3: non lancé, erreur Prompt 1")
        self.log_debug("error", "app", "lmstudio_error", str(error))
        messagebox.showerror("LM Studio", str(error), parent=self.root)

    def refresh_context_from_manager(self) -> None:
        context = self.context_manager.get_latest()
        if not context:
            self.weda_patient_status_var.set("Patient WEDA: non reçu")
            return
        self.set_text(self.context_text, context.to_prompt_text())
        patient_label = context.patient_identity or context.patient_name or context.patient_id or "reçu"
        self.weda_patient_status_var.set(f"Patient WEDA: {patient_label[:40]}")

    def clear_context(self) -> None:
        self.context_manager.clear()
        self.set_text(self.context_text, "")
        self.weda_patient_status_var.set("Patient WEDA: non reçu")

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
        result_1 = self.get_text(self.result_text).strip()
        result_2 = self.get_text(self.secondary_result_text).strip()
        result_3 = self.get_text(self.tertiary_result_text).strip() if hasattr(self, "tertiary_result_text") else ""
        if source == "result_2":
            return result_2
        if source == "result_3":
            return result_3
        if source == "result_1_result_2":
            return "\n\n".join(part for part in (result_1, result_2) if part).strip()
        if source == "result_1_result_2_result_3":
            return "\n\n".join(part for part in (result_1, result_2, result_3) if part).strip()
        return result_1

    def prepare_weda_import(self, source: str = "result_1") -> None:
        result = self.get_result_text_for_import(source)
        if not result:
            label = {
                "result_2": "Résultat 2",
                "result_3": "Résultat 3",
                "result_1_result_2": "résultat 1 + 2",
                "result_1_result_2_result_3": "résultat 1 + 2 + 3",
            }.get(source, "résultat LM Studio")
            messagebox.showwarning("Import WEDA", f"Le {label} est vide.", parent=self.root)
            return
        context = self.context_manager.get_latest()
        request = self.import_manager.prepare_result(
            result,
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

    def copy_result(self) -> None:
        ok = copy_text_to_clipboard(self.get_text(self.result_text), self.root)
        self.import_status_var.set("Résultat copié" if ok else "Copie impossible")

    def copy_secondary_result(self) -> None:
        ok = copy_text_to_clipboard(self.get_text(self.secondary_result_text), self.root)
        self.secondary_status_var.set("Résultat 2 copié" if ok else "Copie Résultat 2 impossible")

    def copy_tertiary_result(self) -> None:
        ok = copy_text_to_clipboard(self.get_text(self.tertiary_result_text), self.root)
        self.tertiary_status_var.set("Résultat 3 copié" if ok else "Copie Résultat 3 impossible")

    def copy_transcription(self) -> None:
        ok = copy_text_to_clipboard(self.get_clean_transcription_text(), self.root)
        self.transcription_status_var.set("Transcription copiée" if ok else "Copie impossible")

    def clear_transcription(self) -> None:
        self.set_text(self.transcription_text, "")
        self.transcription_status_var.set("Transcription prête")

    def clear_result(self) -> None:
        self.set_text(self.result_text, "")
        self.lmstudio_status_var.set("LM Studio: prêt")
        self.schedule_secondary_message_refresh()
        self.schedule_tertiary_message_refresh()

    def clear_secondary_result(self) -> None:
        self.set_text(self.secondary_result_text, "")
        self.secondary_status_var.set("Prompt 2: résultat effacé")
        if hasattr(self, "tertiary_result_text"):
            self.set_text(self.tertiary_result_text, "")
            self.tertiary_status_var.set("Prompt 3: en attente du Résultat 2")
        self.schedule_tertiary_message_refresh()

    def clear_tertiary_result(self) -> None:
        self.set_text(self.tertiary_result_text, "")
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
        if hasattr(self, "pdf_tab_frame"):
            self.notebook.select(self.pdf_tab_frame)
        self.pdf_status_var.set("PDF: source Résultat 3 sélectionnée")

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
        if hasattr(self, "_message_source_widgets") and widget in self._message_source_widgets:
            self.schedule_message_refresh()
        if hasattr(self, "_secondary_message_source_widgets") and widget in self._secondary_message_source_widgets:
            self.schedule_secondary_message_refresh()
        if hasattr(self, "_tertiary_message_source_widgets") and widget in self._tertiary_message_source_widgets:
            self.schedule_tertiary_message_refresh()

    def get_clean_transcription_text(self) -> str:
        return clean_transcription_text(self.get_text(self.transcription_text), self.config.get("transcription_cleaning", {}))

    def close(self) -> None:
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
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = AssistantApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
