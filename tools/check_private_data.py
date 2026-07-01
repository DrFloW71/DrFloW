from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PRIVATE_DIR_NAMES = {
    "data",
    "export",
    "exports",
    "output",
    "outputs",
    "tmp",
    "temp",
}

PRIVATE_EXTENSIONS = {
    ".bak",
    ".csv",
    ".db",
    ".doc",
    ".docx",
    ".flac",
    ".jsonl",
    ".key",
    ".log",
    ".m4a",
    ".mp3",
    ".ods",
    ".ogg",
    ".p12",
    ".pdf",
    ".pem",
    ".pfx",
    ".sqlite",
    ".sqlite3",
    ".tmp",
    ".wav",
    ".webm",
    ".xls",
    ".xlsx",
}

ALLOWED_PRIVATE_EXTENSION_PATHS = {
    "abbreviations.csv",
}

BINARY_EXTENSIONS = {
    ".ico",
    ".jpg",
    ".jpeg",
    ".png",
    ".pyc",
    ".zip",
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
FRENCH_PHONE_RE = re.compile(r"(?<!\d)(?:\+33|0)[1-9](?:[ .-]?\d{2}){4}(?!\d)")
FRENCH_NIR_RE = re.compile(
    r"(?<!\d)[12]\s?\d{2}\s?(?:0[1-9]|1[0-2]|2[ABab])\s?\d{2}\s?\d{3}\s?\d{3}\s?\d{2}(?!\d)"
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"""(?ix)
    \b(?:api[_-]?key|client_secret|secret|password|passwd|pwd|access_token|refresh_token|authorization|bearer)\b
    \s*[:=]\s*
    (?P<quote>['"]?)
    (?P<value>[^\s'",;}]{8,})
    """
)

LINE_ALLOWLIST = (
    "API_KEY: '',",
    "headers.Authorization = `Bearer ${CONFIG.API_KEY}`;",
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    snippet: str


def run_git(args: list[str]) -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def collect_paths(staged: bool) -> list[Path]:
    if staged:
        names = run_git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    else:
        names = run_git(["ls-files", "--cached", "--others", "--exclude-standard"])

    paths: list[Path] = []
    seen: set[Path] = set()

    for name in names:
        path = (ROOT / name).resolve()
        try:
            path.relative_to(ROOT)
        except ValueError:
            continue
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        paths.append(path)

    return paths


def repo_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def is_allowed_private_extension(path: Path) -> bool:
    return repo_path(path) in ALLOWED_PRIVATE_EXTENSION_PATHS


def path_findings(path: Path) -> list[Finding]:
    rel = repo_path(path)
    parts = {part.lower() for part in Path(rel).parts[:-1]}
    findings: list[Finding] = []

    private_part = next((part for part in parts if part in PRIVATE_DIR_NAMES), "")
    if private_part:
        findings.append(Finding(rel, 0, "private directory", f"path contains {private_part}/"))

    if path.suffix.lower() in PRIVATE_EXTENSIONS and not is_allowed_private_extension(path):
        findings.append(Finding(rel, 0, "private file type", f"extension {path.suffix.lower()}"))

    return findings


def is_binary_or_too_large(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return True

    try:
        return path.stat().st_size > 5 * 1024 * 1024
    except OSError:
        return True


def clean_snippet(line: str) -> str:
    text = " ".join(line.strip().split())
    if len(text) > 180:
        return f"{text[:177]}..."
    return text


def is_line_allowed(line: str) -> bool:
    return any(allowed in line for allowed in LINE_ALLOWLIST)


def content_findings(path: Path) -> list[Finding]:
    if is_binary_or_too_large(path):
        return []

    rel = repo_path(path)
    findings: list[Finding] = []

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return findings

    for index, line in enumerate(lines, start=1):
        if is_line_allowed(line):
            continue

        checks = (
            ("email address", EMAIL_RE),
            ("French phone number", FRENCH_PHONE_RE),
            ("French social security number", FRENCH_NIR_RE),
            ("secret-like assignment", SECRET_ASSIGNMENT_RE),
        )

        for kind, pattern in checks:
            if pattern.search(line):
                findings.append(Finding(rel, index, kind, clean_snippet(line)))

    return findings


def scan(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []

    for path in paths:
        findings.extend(path_findings(path))
        findings.extend(content_findings(path))

    return findings


def print_findings(findings: list[Finding]) -> None:
    print("[privacy-check] Donnees potentiellement privees detectees:")
    for finding in findings:
        location = finding.path if finding.line == 0 else f"{finding.path}:{finding.line}"
        print(f"- {location} [{finding.kind}] {finding.snippet}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect private/patient data before committing DrFloW.")
    parser.add_argument("--staged", action="store_true", help="scan only staged files")
    args = parser.parse_args()

    try:
        paths = collect_paths(staged=args.staged)
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        print(f"[privacy-check] Impossible de lire la liste Git: {error}", file=sys.stderr)
        return 2

    if not paths:
        print("[privacy-check] OK: aucun fichier a scanner.")
        return 0

    findings = scan(paths)

    if findings:
        print_findings(findings)
        print()
        print("Commit bloque. Deplacer les fichiers prives dans data/ ou anonymiser les lignes signalees.")
        return 1

    print(f"[privacy-check] OK: aucun motif prive detecte dans {len(paths)} fichier(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
