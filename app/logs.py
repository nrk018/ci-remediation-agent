"""Trim GitHub Actions logs down to an error window and a stable signature."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass

TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s?")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
NOISE = re.compile(
    r"(current runner version|runner image provisioner|operating system|"
    r"##\[group\]|##\[endgroup\]|##\[command\]|##\[warning\]|"
    r"\bdownloading\b|download action repository|^\s*\d+%|#{8,}|={8,})",
    re.IGNORECASE,
)
GENERIC_EXIT = re.compile(r"process completed with exit code \d+", re.IGNORECASE)
ERROR_HINT = re.compile(
    r"(error|fail|exception|traceback|timeout|timed out|conflict|yanked|eresolve|"
    r"not set|invalid|cannot install|resolutionimpossible|exceeded|unhealthy|"
    r"ruff|eslint|prettier|incompatible|resolver|flaky|race|missing|"
    r"did not become healthy|maximum execution time)",
    re.IGNORECASE,
)
PROGRESS = re.compile(r"^[\s#=.]*$")


@dataclass(frozen=True)
class LogExtract:
    error_window: str
    signature: str
    job_name: str


def redact(text: str) -> str:
    """Remove credential-shaped strings before anything is embedded or sent to a model."""
    text = re.sub(
        r"(?i)\b(password|passwd|token|secret|api_key|apikey)\b(\s*[:=]\s*)"
        r"('[^']*'|\"[^\"]*\"|\S+)",
        r"\1\2[REDACTED]",
        text,
    )
    text = re.sub(r"(?i)(authorization:\s*bearer\s+)\S+", r"\1[REDACTED]", text)
    text = re.sub(r"ghp_[A-Za-z0-9]{16,}", "[REDACTED]", text)
    text = re.sub(r"github_pat_[A-Za-z0-9_]{16,}", "[REDACTED]", text)
    text = re.sub(r"sk-(?:proj-)?[A-Za-z0-9_\-]{16,}", "[REDACTED]", text)
    text = re.sub(r"AKIA[0-9A-Z]{16}", "[REDACTED]", text)
    return text


def strip_line(line: str) -> str:
    line = ANSI.sub("", line).rstrip("\n")
    return TIMESTAMP.sub("", line).rstrip()


def _split_steps(lines: list[str]) -> list[list[str]]:
    steps: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("##[group]"):
            if current:
                steps.append(current)
            current = [line]
            continue
        current.append(line)
        if line.startswith("##[endgroup]"):
            steps.append(current)
            current = []
    if current:
        steps.append(current)
    return steps or [lines]


def _step_failed(step: list[str]) -> bool:
    text = "\n".join(step).lower()
    return "##[error]" in text or "exit code 1" in text


def _clean(step: list[str]) -> list[str]:
    cleaned: list[str] = []
    for line in step:
        if not line or NOISE.search(line) or PROGRESS.match(line):
            continue
        if GENERIC_EXIT.search(line):
            continue
        if cleaned and cleaned[-1] == line:
            continue
        cleaned.append(line)
    return cleaned


def _window(lines: list[str], tail: int) -> str:
    picked = list(lines[-tail:])
    for line in lines:
        if ERROR_HINT.search(line) and line not in picked:
            picked.append(line)
    return redact("\n".join(picked))


def _signature(lines: list[str]) -> str:
    picked: list[str] = []
    for line in lines:
        if GENERIC_EXIT.search(line) or not ERROR_HINT.search(line):
            continue
        normalized = re.sub(r"\s+", " ", redact(line)).strip().lower()
        if normalized and normalized not in picked:
            picked.append(normalized)
    if not picked:
        for line in lines[-8:]:
            normalized = re.sub(r"\s+", " ", redact(line)).strip().lower()
            if normalized and normalized not in picked:
                picked.append(normalized)
    return "\n".join(picked)[:2000]


def affected_file(text: str) -> str | None:
    match = re.search(r"Affected file:\s+(\S+)", text, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def extract(text: str, tail: int = 40) -> LogExtract:
    stripped = [strip_line(line) for line in text.splitlines()]
    steps = _split_steps(stripped)
    failed = [step for step in steps if _step_failed(step)]
    chosen = failed[-1] if failed else (steps[-1] if steps else [])
    cleaned = _clean(chosen)
    job_name = chosen[0].removeprefix("##[group]").strip() if chosen else "job"
    return LogExtract(error_window=_window(cleaned, tail), signature=_signature(cleaned), job_name=job_name)


def failed_job_text(data: bytes) -> str:
    """Return the raw log of the failed job inside a GitHub log archive."""
    chosen: str | None = None
    fallback: str | None = None
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = sorted(name for name in archive.namelist() if name.endswith(".txt"))
        if not names:
            raise ValueError("log archive contained no job logs")
        for name in names:
            text = archive.read(name).decode("utf-8", errors="replace")
            fallback = text
            if "##[error]" in text.lower() or "exit code 1" in text.lower():
                chosen = text
    if chosen is None and fallback is None:
        raise ValueError("log archive contained no job logs")
    return chosen or fallback or ""


def extract_from_zip(data: bytes, tail: int = 40) -> LogExtract:
    chosen: LogExtract | None = None
    fallback: LogExtract | None = None
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = sorted(name for name in archive.namelist() if name.endswith(".txt"))
        if not names:
            raise ValueError("log archive contained no job logs")
        for name in names:
            text = archive.read(name).decode("utf-8", errors="replace")
            item = extract(text, tail=tail)
            item = LogExtract(item.error_window, item.signature, name)
            fallback = item
            if "##[error]" in text.lower() or "exit code 1" in text.lower():
                chosen = item
    if chosen is None and fallback is None:
        raise ValueError("log archive contained no job logs")
    return chosen or fallback
