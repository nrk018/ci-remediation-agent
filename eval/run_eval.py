"""Score the agent on seeded failures, with and without failure memory."""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.config import Settings
from app.graph import RetrievalDiagnoser, Services, build_graph
from app.logs import extract
from app.memory import FailureRecord, InMemoryStore
from app.patches import PatchError, apply_unified_diff
from app.tools import propose_fix

CASES_DIR = Path(__file__).resolve().parent / "cases"


def load_cases() -> list[dict]:
    cases = [json.loads(path.read_text()) for path in sorted(CASES_DIR.glob("*.json"))]
    if len(cases) < 25:
        raise SystemExit(f"Expected at least 25 cases, found {len(cases)}")
    return cases


def _signature(case: dict) -> str:
    return extract(case["log"]).signature


def _settings() -> Settings:
    return Settings(offline=True, confidence_threshold=0.35, similarity_floor=0.35)


def _services(cases: list[dict], *, use_memory: bool, exclude_id: str | None) -> Services:
    settings = _settings()
    store = InMemoryStore(settings)
    if use_memory:
        for case in cases:
            if case["id"] == exclude_id or case["expect_decline"]:
                continue
            store.add(
                FailureRecord(
                    repo=case["repo"],
                    run_id=case["run_id"],
                    signature=_signature(case),
                    category=case["category"],
                    root_cause=case["root_cause"],
                    fix_diff=case["fix_diff"],
                    fix_worked=True,
                )
            )
    services = Services(
        settings=settings,
        memory=store,
        diagnoser=RetrievalDiagnoser(),
        github=None,
    )
    services.graph = build_graph(services)
    return services


def _cause_matches(case: dict, root_cause: str | None) -> bool:
    text = (root_cause or "").lower()
    return all(marker.lower() in text for marker in case["cause_markers"])


def score(cases: list[dict] | None = None, *, use_memory: bool = True) -> dict:
    cases = cases or load_cases()
    rows = []
    started = time.perf_counter()
    for case in cases:
        services = _services(cases, use_memory=use_memory, exclude_id=case["id"])
        case_started = time.perf_counter()
        result = propose_fix(
            case["repo"],
            case["run_id"],
            services=services,
            raw_log=case["log"],
            file_path=case["file_path"],
            file_contents=case["file_before"],
        )
        elapsed = time.perf_counter() - case_started
        matches = services.memory.search(_signature(case), k=3)
        categories = [match["category"] for match in matches]
        fix_ok = False
        if result.get("patch_valid") and result.get("diff"):
            try:
                patched = apply_unified_diff(case["file_before"], result["diff"])
            except PatchError:
                patched = None
            expected = case["file_after"] if case["file_after"].endswith("\n") else case["file_after"] + "\n"
            fix_ok = patched == expected
        diagnosis_ok = (
            not result.get("declined")
            and result.get("category") == case["category"]
            and _cause_matches(case, result.get("root_cause"))
        )
        rows.append(
            {
                "id": case["id"],
                "category": case["category"],
                "expect_decline": case["expect_decline"],
                "declined": bool(result.get("declined")),
                "predicted": result.get("category"),
                "diagnosis_ok": diagnosis_ok,
                "retrieved": case["category"] in categories,
                "fix_ok": fix_ok,
                "seconds": round(elapsed, 4),
            }
        )
    clear = [row for row in rows if not row["expect_decline"]]
    ambiguous = [row for row in rows if row["expect_decline"]]
    def rate(items: list[dict], key: str) -> float:
        if not items:
            return 0.0
        return sum(1 for item in items if item[key]) / len(items)

    return {
        "use_memory": use_memory,
        "cases": len(rows),
        "clear_cases": len(clear),
        "ambiguous_cases": len(ambiguous),
        "top1_accuracy": rate(clear, "diagnosis_ok"),
        "retrieval_hit_rate_at_3": rate(clear, "retrieved"),
        "fix_success": rate(clear, "fix_ok"),
        "decline_rate_on_ambiguous": rate(ambiguous, "declined"),
        "false_decline_rate": rate(clear, "declined"),
        "mean_seconds": round(sum(row["seconds"] for row in rows) / len(rows), 4),
        "wall_seconds": round(time.perf_counter() - started, 4),
        "misses": [
            row["id"]
            for row in rows
            if (row["expect_decline"] and not row["declined"])
            or (not row["expect_decline"] and (not row["diagnosis_ok"] or not row["fix_ok"]))
        ],
        "rows": rows,
    }


def render(report: dict) -> str:
    memory = "with retrieval" if report["use_memory"] else "without retrieval"
    lines = [
        f"Dataset: {report['cases']} seeded failures ({memory})",
        f"Top-1 root-cause accuracy on clear cases: {report['top1_accuracy']:.0%}",
        f"Retrieval hit rate @3 on clear cases: {report['retrieval_hit_rate_at_3']:.0%}",
        f"First-run fix success on clear cases: {report['fix_success']:.0%}",
        f"Correct decline rate on ambiguous cases: {report['decline_rate_on_ambiguous']:.0%}",
        f"False decline rate on clear cases: {report['false_decline_rate']:.0%}",
        f"Mean seconds per case: {report['mean_seconds']}",
    ]
    if report["misses"]:
        lines.append("Misses: " + ", ".join(report["misses"]))
    else:
        lines.append("Misses: none")
    return "\n".join(lines)


def main() -> None:
    cases = load_cases()
    with_memory = score(cases, use_memory=True)
    without_memory = score(cases, use_memory=False)
    print(render(with_memory))
    print()
    print(render(without_memory))
    print()
    print(
        "Notes: failures are seeded, not organic production incidents. "
        "Five cases are intentionally ambiguous and should be declined. "
        "This run uses the offline retrieval diagnoser and hash embeddings. "
        "Set OPENAI_API_KEY to use gpt-4o-mini and text-embedding-3-small."
    )


if __name__ == "__main__":
    main()
