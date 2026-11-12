"""Seeded failure definitions. Run this module to refresh eval/cases/*.json."""

from __future__ import annotations

import json
from pathlib import Path

from app.patches import make_unified_diff as make_diff

CASES_DIR = Path(__file__).resolve().parent / "cases"

REQ_BEFORE = "numpy==1.24.0\npandas==2.2.0\n"
REQ_AFTER = "numpy==1.26.4\npandas==2.2.2\n"
PKG_BEFORE = (
    '{\n  "name": "demo",\n  "dependencies": {\n'
    '    "react": "18.2.0",\n    "react-dom": "17.0.2"\n  }\n}\n'
)
PKG_AFTER = (
    '{\n  "name": "demo",\n  "dependencies": {\n'
    '    "react": "18.2.0",\n    "react-dom": "18.2.0"\n  }\n}\n'
)

FLAKY_A_BEFORE = (
    "name: test\non: [push]\njobs:\n  unit:\n    runs-on: ubuntu-latest\n"
    "    steps:\n      - run: pytest --random-order\n"
)
FLAKY_A_AFTER = (
    "name: test\non: [push]\njobs:\n  unit:\n    runs-on: ubuntu-latest\n"
    "    steps:\n      - run: pytest\n"
)
FLAKY_B_BEFORE = (
    "name: test\non: [push]\njobs:\n  unit:\n    runs-on: ubuntu-latest\n"
    "    steps:\n      - run: pytest -p no:randomly\n"
)
FLAKY_B_AFTER = (
    "name: test\non: [push]\njobs:\n  unit:\n    runs-on: ubuntu-latest\n"
    "    steps:\n      - run: pytest --reruns 2\n"
)

CONFIG_A_BEFORE = (
    "name: ci\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
    "    enviornment: production\n    steps:\n      - run: echo hi\n"
)
CONFIG_A_AFTER = (
    "name: ci\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
    "    environment: production\n    steps:\n      - run: echo hi\n"
)
CONFIG_B_BEFORE = (
    "name: ci\non: [push]\njobs:\n  build:\n    runs-on: self-hosted-gpu\n"
    "    steps:\n      - run: echo hi\n"
)
CONFIG_B_AFTER = (
    "name: ci\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
    "    steps:\n      - run: echo hi\n"
)

TIMEOUT_A_BEFORE = (
    "name: ci\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
    "    timeout-minutes: 1\n    steps:\n      - run: echo hi\n"
)
TIMEOUT_A_AFTER = (
    "name: ci\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
    "    timeout-minutes: 15\n    steps:\n      - run: echo hi\n"
)
TIMEOUT_B_BEFORE = (
    "name: ci\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
    "    steps:\n      - run: docker compose up --wait\n"
    "        timeout-minutes: 1\n"
)
TIMEOUT_B_AFTER = (
    "name: ci\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
    "    steps:\n      - run: docker compose up --wait\n"
    "        timeout-minutes: 15\n"
)

LINT_A_BEFORE = (
    "name: ci\non: [push]\njobs:\n  lint:\n    runs-on: ubuntu-latest\n"
    "    steps:\n      - run: ruff check .\n"
)
LINT_A_AFTER = (
    "name: ci\non: [push]\njobs:\n  lint:\n    runs-on: ubuntu-latest\n"
    "    steps:\n      - run: ruff format .\n      - run: ruff check .\n"
)
LINT_B_BEFORE = (
    "name: ci\non: [push]\njobs:\n  lint:\n    runs-on: ubuntu-latest\n"
    "    steps:\n      - run: prettier --check .\n"
)
LINT_B_AFTER = (
    "name: ci\non: [push]\njobs:\n  lint:\n    runs-on: ubuntu-latest\n"
    "    steps:\n      - run: prettier --write .\n"
)


def _log(command: str, error_line: str, path: str | None) -> str:
    rows = [
        "2024-11-01T12:00:00.0000000Z Current runner version: '2.320.0'",
        f"2024-11-01T12:00:01.0000000Z ##[group]Run {command}",
        "2024-11-01T12:00:01.1000000Z 40% downloading wheels",
        "2024-11-01T12:00:01.2000000Z 40% downloading wheels",
    ]
    if path:
        rows.append(f"2024-11-01T12:00:01.3000000Z Affected file: {path}")
    rows.append(f"2024-11-01T12:00:01.4000000Z {error_line}")
    rows.append("2024-11-01T12:00:01.5000000Z ##[error]Process completed with exit code 1.")
    rows.append("2024-11-01T12:00:01.6000000Z ##[endgroup]")
    return "\n".join(rows) + "\n"


def _case(
    case_id: str,
    category: str,
    path: str,
    before: str,
    after: str,
    error_line: str,
    root_cause: str,
    markers: list[str],
    *,
    expect_decline: bool = False,
    run_id: int,
) -> dict:
    diff = "" if expect_decline else make_diff(path, before, after)
    return {
        "id": case_id,
        "category": category,
        "root_cause": root_cause,
        "cause_markers": markers,
        "expect_decline": expect_decline,
        "repo": "example/ci-fixtures",
        "run_id": run_id,
        "file_path": path,
        "file_before": before,
        "file_after": after,
        "fix_diff": diff,
        "log": _log("bash ci-step", error_line, None if expect_decline else path),
    }


def build_cases() -> list[dict]:
    dep = "dependency resolution failed: cannot satisfy pinned versions"
    flaky = "flaky nondeterministic test order race condition"
    config = "configuration key missing environment variable runner label"
    timeout = "timeout exceeded service container unhealthy deadline"
    lint = "lint format checker rejected whitespace style"
    cases = [
        _case(
            "dependency-01",
            "dependency",
            "requirements.txt",
            REQ_BEFORE,
            REQ_AFTER,
            f"ERROR: {dep} numpy==1.24.0 pandas==2.2.0 resolver backtracked",
            "Conflicting pins numpy==1.24.0 and pandas==2.2.0",
            ["dependency resolution failed", "numpy==1.24.0", "resolver backtracked"],
            run_id=1001,
        ),
        _case(
            "dependency-02",
            "dependency",
            "requirements.txt",
            REQ_BEFORE,
            REQ_AFTER,
            f"ERROR: {dep} numpy==1.24.0 pandas==2.2.0 wheelhouse conflict",
            "Conflicting pins numpy==1.24.0 and pandas==2.2.0",
            ["dependency resolution failed", "numpy==1.24.0", "wheelhouse conflict"],
            run_id=1002,
        ),
        _case(
            "dependency-03",
            "dependency",
            "package.json",
            PKG_BEFORE,
            PKG_AFTER,
            f"ERROR: {dep} react-dom 17 peer of react 18 eresolve",
            "react-dom 17 does not satisfy the react 18 peer dependency",
            ["dependency resolution failed", "eresolve", "react-dom"],
            run_id=1003,
        ),
        _case(
            "dependency-04",
            "dependency",
            "package.json",
            PKG_BEFORE,
            PKG_AFTER,
            f"ERROR: {dep} react-dom 17 peer of react 18 lockfile mismatch",
            "react-dom 17 does not satisfy the react 18 peer dependency",
            ["dependency resolution failed", "lockfile mismatch"],
            run_id=1004,
        ),
        _case(
            "dependency-05",
            "dependency",
            "requirements.txt",
            REQ_BEFORE,
            REQ_AFTER,
            "quartz mailbox drifted sideways without a diagnostic",
            "Ambiguous failure with no dependency evidence",
            ["quartz mailbox"],
            expect_decline=True,
            run_id=1005,
        ),
        _case(
            "flaky-01",
            "flaky_test",
            ".github/workflows/test.yml",
            FLAKY_A_BEFORE,
            FLAKY_A_AFTER,
            f"ERROR: {flaky} random-order-bucket random-order-bucket assertion missed the timing window",
            "Test depends on random order and a short timing window",
            ["flaky nondeterministic", "timing window"],
            run_id=2001,
        ),
        _case(
            "flaky-02",
            "flaky_test",
            ".github/workflows/test.yml",
            FLAKY_A_BEFORE,
            FLAKY_A_AFTER,
            f"ERROR: {flaky} random-order-bucket random-order-bucket shared state leaked across tests",
            "Test depends on random order and leaked shared state",
            ["flaky nondeterministic", "shared state"],
            run_id=2002,
        ),
        _case(
            "flaky-03",
            "flaky_test",
            ".github/workflows/retry.yml",
            FLAKY_B_BEFORE,
            FLAKY_B_AFTER,
            f"ERROR: {flaky} rerun-bucket rerun-bucket eventually-consistent assertion failed once",
            "A single nondeterministic assertion failed with no retry",
            ["flaky nondeterministic", "eventually-consistent"],
            run_id=2003,
        ),
        _case(
            "flaky-04",
            "flaky_test",
            ".github/workflows/retry.yml",
            FLAKY_B_BEFORE,
            FLAKY_B_AFTER,
            f"ERROR: {flaky} rerun-bucket rerun-bucket order-dependent fixture collided",
            "Order-dependent fixture collision with no retry",
            ["flaky nondeterministic", "fixture collided"],
            run_id=2004,
        ),
        _case(
            "flaky-05",
            "flaky_test",
            ".github/workflows/test.yml",
            FLAKY_A_BEFORE,
            FLAKY_A_AFTER,
            "velvet kiln hummed while the archive cooled",
            "Ambiguous failure with no flaky-test evidence",
            ["velvet kiln"],
            expect_decline=True,
            run_id=2005,
        ),
        _case(
            "config-01",
            "config",
            ".github/workflows/ci.yml",
            CONFIG_A_BEFORE,
            CONFIG_A_AFTER,
            f"ERROR: {config} unexpected key enviornment",
            "Workflow uses the misspelled key enviornment",
            ["configuration key missing", "enviornment"],
            run_id=3001,
        ),
        _case(
            "config-02",
            "config",
            ".github/workflows/ci.yml",
            CONFIG_A_BEFORE,
            CONFIG_A_AFTER,
            f"ERROR: {config} database url was not set",
            "DATABASE_URL is missing from the job environment",
            ["configuration key missing", "database url"],
            run_id=3002,
        ),
        _case(
            "config-03",
            "config",
            ".github/workflows/runners.yml",
            CONFIG_B_BEFORE,
            CONFIG_B_AFTER,
            f"ERROR: {config} unable to find runner self-hosted-gpu",
            "The job requests a runner label that does not exist",
            ["configuration key missing", "self-hosted-gpu"],
            run_id=3003,
        ),
        _case(
            "config-04",
            "config",
            ".github/workflows/runners.yml",
            CONFIG_B_BEFORE,
            CONFIG_B_AFTER,
            f"ERROR: {config} no online runner matched the label",
            "No online runner matches the requested label",
            ["configuration key missing", "no online runner"],
            run_id=3004,
        ),
        _case(
            "config-05",
            "config",
            ".github/workflows/ci.yml",
            CONFIG_A_BEFORE,
            CONFIG_A_AFTER,
            "cinder harp moss folded into paper",
            "Ambiguous failure with no configuration evidence",
            ["cinder harp"],
            expect_decline=True,
            run_id=3005,
        ),
        _case(
            "timeout-01",
            "timeout",
            ".github/workflows/ci.yml",
            TIMEOUT_A_BEFORE,
            TIMEOUT_A_AFTER,
            f"ERROR: {timeout} job-limit-bucket job-limit-bucket the job has exceeded its limit",
            "The job timeout is shorter than the build",
            ["timeout exceeded", "exceeded its limit"],
            run_id=4001,
        ),
        _case(
            "timeout-02",
            "timeout",
            ".github/workflows/ci.yml",
            TIMEOUT_A_BEFORE,
            TIMEOUT_A_AFTER,
            f"ERROR: {timeout} job-limit-bucket job-limit-bucket step cancelled after the job limit",
            "The job timeout cancelled the step",
            ["timeout exceeded", "step cancelled"],
            run_id=4002,
        ),
        _case(
            "timeout-03",
            "timeout",
            ".github/workflows/services.yml",
            TIMEOUT_B_BEFORE,
            TIMEOUT_B_AFTER,
            f"ERROR: {timeout} port-wait-bucket port-wait-bucket postgres did not become ready",
            "The service container was not ready before the step timeout",
            ["timeout exceeded", "postgres did not become ready"],
            run_id=4003,
        ),
        _case(
            "timeout-04",
            "timeout",
            ".github/workflows/services.yml",
            TIMEOUT_B_BEFORE,
            TIMEOUT_B_AFTER,
            f"ERROR: {timeout} port-wait-bucket port-wait-bucket port 5432 was still closed",
            "Port 5432 was still closed when the step timed out",
            ["timeout exceeded", "5432"],
            run_id=4004,
        ),
        _case(
            "timeout-05",
            "timeout",
            ".github/workflows/ci.yml",
            TIMEOUT_A_BEFORE,
            TIMEOUT_A_AFTER,
            "pluto orchard lantern skipped the meadow",
            "Ambiguous failure with no timeout evidence",
            ["pluto orchard"],
            expect_decline=True,
            run_id=4005,
        ),
        _case(
            "other-01",
            "other",
            ".github/workflows/lint.yml",
            LINT_A_BEFORE,
            LINT_A_AFTER,
            f"ERROR: {lint} ruff would reformat three files",
            "Ruff format check failed because files were not formatted",
            ["lint format checker", "ruff would reformat"],
            run_id=5001,
        ),
        _case(
            "other-02",
            "other",
            ".github/workflows/lint.yml",
            LINT_A_BEFORE,
            LINT_A_AFTER,
            f"ERROR: {lint} black-compatible whitespace drift",
            "Formatter whitespace drift failed the lint step",
            ["lint format checker", "whitespace drift"],
            run_id=5002,
        ),
        _case(
            "other-03",
            "other",
            ".github/workflows/prettier.yml",
            LINT_B_BEFORE,
            LINT_B_AFTER,
            f"ERROR: {lint} prettier found formatting issues",
            "Prettier check failed on formatting",
            ["lint format checker", "prettier found"],
            run_id=5003,
        ),
        _case(
            "other-04",
            "other",
            ".github/workflows/prettier.yml",
            LINT_B_BEFORE,
            LINT_B_AFTER,
            f"ERROR: {lint} prettier reported unwritten files",
            "Prettier reported files that were not written",
            ["lint format checker", "unwritten files"],
            run_id=5004,
        ),
        _case(
            "other-05",
            "other",
            ".github/workflows/lint.yml",
            LINT_A_BEFORE,
            LINT_A_AFTER,
            "amber spool tango under glass",
            "Ambiguous failure with no lint evidence",
            ["amber spool"],
            expect_decline=True,
            run_id=5005,
        ),
    ]
    return cases


def write_cases() -> None:
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    for stale in CASES_DIR.glob("*.json"):
        stale.unlink()
    for case in build_cases():
        (CASES_DIR / f"{case['id']}.json").write_text(json.dumps(case, indent=2) + "\n")


if __name__ == "__main__":
    write_cases()
