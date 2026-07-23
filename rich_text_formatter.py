from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class RichTextPayload:
    text: str
    html: str


_ALLOWED_INLINE_TAG_RE = re.compile(r"</?\s*(strong|b|em|i|u|s|strike|del|br)\b[^>]*>", re.IGNORECASE)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^(\s*)[-*]\s+(.+?)\s*$")
_NUMBERED_RE = re.compile(r"^(\s*\d+[.)])\s+(.+?)\s*$")
_HORIZONTAL_RULE_RE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_SECTION_HEADING_LABELS = {
    "allergies",
    "antecedents",
    "atcd",
    "avis",
    "biologie",
    "cat",
    "compte rendu",
    "conclusion",
    "conduite a tenir",
    "constantes",
    "contexte",
    "courrier",
    "diagnostic",
    "diagnostics",
    "documents",
    "evolution",
    "examen",
    "examen clinique",
    "histoire",
    "imagerie",
    "interrogatoire",
    "motif",
    "ordonnance",
    "plan",
    "prise en charge",
    "resume",
    "resultats",
    "suivi",
    "surveillance",
    "synthese",
    "traitement",
    "traitements",
}


def format_weda_rich_text(value: str) -> RichTextPayload:
    """Build WEDA-friendly rich text without rewriting prompt-authored line breaks."""
    source = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    plain_lines: list[str] = []
    html_lines: list[str] = []

    for raw_line in source.split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            plain_lines.append("")
            html_lines.append("")
            continue

        if _HORIZONTAL_RULE_RE.match(line):
            plain_lines.append("")
            html_lines.append("")
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            heading_text = heading.group(1)
            plain_lines.append(_markdown_inline_to_text(heading_text))
            html_lines.append(f"<strong><u>{_markdown_inline_to_safe_html(heading_text)}</u></strong>")
            continue

        section_heading = _split_section_heading_line(line)
        if section_heading:
            label, suffix = section_heading
            plain_lines.append(_markdown_inline_to_text(line))
            label_html = f"<strong><u>{_markdown_inline_to_safe_html(label)}</u></strong>"
            if suffix:
                html_lines.append(f"{label_html} {_markdown_inline_to_safe_html(suffix)}")
            else:
                html_lines.append(label_html)
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            item = bullet.group(2)
            plain_lines.append(f"- {_markdown_inline_to_text(item)}")
            html_lines.append(f"&#8226; {_markdown_inline_to_safe_html(item)}")
            continue

        numbered = _NUMBERED_RE.match(line)
        if numbered:
            prefix = numbered.group(1).strip()
            item = numbered.group(2)
            plain_lines.append(f"{prefix} {_markdown_inline_to_text(item)}")
            html_lines.append(f"{html.escape(prefix)} {_markdown_inline_to_safe_html(item)}")
            continue

        plain_lines.append(_markdown_inline_to_text(line))
        html_lines.append(_markdown_inline_to_safe_html(line))

    text = "\n".join(plain_lines)
    fragment = "<br>".join(html_lines)
    return RichTextPayload(text=text, html=fragment)


def combine_weda_rich_text_payloads(payloads: list[RichTextPayload]) -> RichTextPayload:
    usable = [payload for payload in payloads if payload and (payload.text.strip() or payload.html.strip())]
    if not usable:
        return RichTextPayload(text="", html="")
    return RichTextPayload(
        text="\n\n".join(payload.text.strip() for payload in usable if payload.text.strip()).strip(),
        html="<br><br>".join((payload.html or html.escape(payload.text)).strip() for payload in usable).strip(),
    )


def _markdown_inline_to_text(value: str) -> str:
    source = _strip_unsafe_html_to_text(str(value or ""))
    source = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", source)
    source = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", source)
    source = re.sub(r"`([^`]*)`", r"\1", source)

    replacements = [
        (r"\*\*\*([^*]+)\*\*\*", r"\1"),
        (r"\*\*([^*]+)\*\*", r"\1"),
        (r"__([^_]+)__", r"\1"),
        (r"\+\+([^+]+)\+\+", r"\1"),
        (r"~~([^~]+)~~", r"\1"),
        (r"\*([^*]+)\*", r"\1"),
        (r"_([^_]+)_", r"\1"),
    ]
    for pattern, repl in replacements:
        source = re.sub(pattern, repl, source)

    return html.unescape(source).strip()


def _markdown_inline_to_safe_html(value: str) -> str:
    placeholders: list[str] = []

    def preserve_tag(match: re.Match[str]) -> str:
        raw = match.group(0)
        tag_match = re.match(r"</?\s*([a-z0-9]+)", raw, re.IGNORECASE)
        if not tag_match:
            return html.escape(raw)

        name = tag_match.group(1).lower()
        if name == "br":
            normalized = "<br>"
        else:
            mapped = {"b": "strong", "i": "em", "strike": "s", "del": "s"}.get(name, name)
            normalized = f"</{mapped}>" if raw.lstrip().startswith("</") else f"<{mapped}>"

        placeholders.append(normalized)
        return f"@@DRFLOWTAG{len(placeholders) - 1}@@"

    source = _ALLOWED_INLINE_TAG_RE.sub(preserve_tag, str(value or ""))
    source = html.escape(source)
    source = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", source)
    source = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", source)
    source = re.sub(r"`([^`]*)`", r"\1", source)
    source = re.sub(r"\*\*\*([^*]+)\*\*\*", r"<strong><em>\1</em></strong>", source)
    source = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", source)
    source = re.sub(r"__([^_]+)__", r"<u>\1</u>", source)
    source = re.sub(r"\+\+([^+]+)\+\+", r"<u>\1</u>", source)
    source = re.sub(r"~~([^~]+)~~", r"<s>\1</s>", source)
    source = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", source)
    source = re.sub(r"_([^_]+)_", r"<em>\1</em>", source)

    def restore_tag(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return placeholders[index] if 0 <= index < len(placeholders) else ""

    return re.sub(r"@@DRFLOWTAG(\d+)@@", restore_tag, source)


def _split_section_heading_line(line: str) -> tuple[str, str] | None:
    stripped = str(line or "").strip()
    if not stripped:
        return None

    colon_match = re.match(r"^(.{2,60}?)(\s*:\s*)(.*)$", stripped)
    if colon_match:
        label = colon_match.group(1).strip()
        if _is_section_heading_label(label):
            formatted_label = f"{label}{colon_match.group(2).rstrip()}"
            return formatted_label, colon_match.group(3).strip()
        return None

    if len(stripped) <= 60 and _is_section_heading_label(stripped):
        return stripped, ""

    return None


def _is_section_heading_label(value: str) -> bool:
    return _normalize_section_heading_label(value) in _SECTION_HEADING_LABELS


def _normalize_section_heading_label(value: str) -> str:
    text = _markdown_inline_to_text(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_unsafe_html_to_text(value: str) -> str:
    def replace_tag(match: re.Match[str]) -> str:
        name = match.group(1).lower()
        return "\n" if name == "br" else ""

    source = _ALLOWED_INLINE_TAG_RE.sub(replace_tag, value)
    return re.sub(r"<[^>]+>", "", source)
