"""Apply a unified diff and reject patches that do not parse."""

from __future__ import annotations

import ast
import difflib
import json
import re
import tomllib

import yaml


class PatchError(ValueError):
    pass


class ParseError(ValueError):
    pass


_REQUIREMENT = re.compile(
    r"^(-r|--requirement)\s+\S+$|"
    r"^(-e|--editable)\s+\S+$|"
    r"^[A-Za-z0-9][A-Za-z0-9._\-]*(\[[^\]]+\])?\s*([=<>!~]=|[<>]=?|==|@).+$|"
    r"^[A-Za-z0-9][A-Za-z0-9._\-]*$"
)


def make_unified_diff(path: str, before: str, after: str) -> str:
    if not before.endswith("\n"):
        before += "\n"
    if not after.endswith("\n"):
        after += "\n"
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
    if not diff:
        raise PatchError(f"no difference for {path}")
    return diff


def path_from_diff(diff: str) -> str | None:
    match = re.search(r"^\+\+\+ b/(.+)$", diff, re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()


def _content(line: str) -> str:
    return line[1:].rstrip("\r\n")


def apply_unified_diff(original: str, diff: str) -> str:
    original_lines = original.splitlines()
    diff_lines = diff.splitlines()
    output: list[str] = []
    index = 0
    cursor = 0
    saw_hunk = False
    while cursor < len(diff_lines):
        line = diff_lines[cursor]
        if line.startswith(("---", "+++", "diff ", "index ", "\\")):
            cursor += 1
            continue
        if not line.startswith("@@"):
            cursor += 1
            continue
        match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if not match:
            raise PatchError(f"unreadable hunk header: {line}")
        saw_hunk = True
        old_start = int(match.group(1))
        # A start of 0 means the original file was empty.
        target = 0 if old_start == 0 else old_start - 1
        if target < index:
            raise PatchError("hunk overlaps an earlier hunk")
        output.extend(original_lines[index:target])
        index = target
        cursor += 1
        while cursor < len(diff_lines) and not diff_lines[cursor].startswith("@@"):
            hunk_line = diff_lines[cursor]
            if hunk_line.startswith("\\"):
                cursor += 1
                continue
            if hunk_line.startswith(" "):
                if index >= len(original_lines) or original_lines[index] != _content(hunk_line):
                    raise PatchError("context line does not match the file")
                output.append(original_lines[index])
                index += 1
            elif hunk_line.startswith("-"):
                if index >= len(original_lines) or original_lines[index] != _content(hunk_line):
                    raise PatchError("removed line does not match the file")
                index += 1
            elif hunk_line.startswith("+"):
                output.append(_content(hunk_line))
            else:
                break
            cursor += 1
    if not saw_hunk:
        raise PatchError("diff did not contain a hunk")
    output.extend(original_lines[index:])
    text = "\n".join(output)
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def ensure_parses(path: str, content: str) -> None:
    try:
        if path.endswith((".yml", ".yaml")):
            loaded = yaml.safe_load(content)
            if loaded is None:
                raise ParseError(f"{path} parsed as empty YAML")
        elif path.endswith(".json"):
            json.loads(content)
        elif path.endswith(".toml"):
            tomllib.loads(content)
        elif path.endswith(".py"):
            ast.parse(content)
        elif path.endswith("requirements.txt") or path.endswith(".txt"):
            for line_number, raw in enumerate(content.splitlines(), start=1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if not _REQUIREMENT.match(line):
                    raise ParseError(f"{path}:{line_number} is not a requirement")
    except (yaml.YAMLError, json.JSONDecodeError, tomllib.TOMLDecodeError, SyntaxError) as exc:
        raise ParseError(str(exc)) from exc


FIXABLE_NAMES = {
    "requirements.txt",
    "requirements-dev.txt",
    "package.json",
    "pyproject.toml",
    "Pipfile",
    "Dockerfile",
    "docker-compose.yml",
}


def is_fixable_path(path: str) -> bool:
    normalized = path[2:] if path.startswith("./") else path
    if normalized.startswith(".github/workflows/") and normalized.endswith((".yml", ".yaml")):
        return True
    return normalized.split("/")[-1] in FIXABLE_NAMES


def validate_patch(path: str, original: str, diff: str) -> tuple[bool, str | None, str | None]:
    """Return whether the diff applies, stays in scope, and still parses."""
    from app.logs import redact

    if not diff or not diff.strip():
        return False, "Empty patch", None
    if not is_fixable_path(path):
        return False, f"Refusing to patch {path}; only workflows and manifests are in scope", None
    added = "\n".join(
        line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")
    )
    if redact(added) != added:
        return False, "Patch contains a secret-like string", None
    try:
        patched = apply_unified_diff(original, diff)
        ensure_parses(path, patched)
    except (PatchError, ParseError) as exc:
        return False, str(exc), None
    comparable = original if original.endswith("\n") else original + "\n"
    if patched == comparable:
        return False, "Patch does not change the file", None
    return True, None, patched


def first_applicable_diff(get_file, matches: list[dict]) -> dict | None:
    """Return the highest-ranked remembered fix that applies and still parses."""
    for match in matches:
        diff = match.get("fix_diff") or ""
        path = path_from_diff(diff)
        if not diff or not path:
            continue
        try:
            original = get_file(path)
        except Exception:
            continue
        try:
            patched = apply_unified_diff(original, diff)
            ensure_parses(path, patched)
        except (PatchError, ParseError):
            continue
        if patched == original:
            continue
        return {
            "diff": diff,
            "file_path": path,
            "file_contents": original,
            "patched_contents": patched,
            "source_root_cause": match.get("root_cause"),
        }
    return None
