"""LangGraph that diagnoses a failed run and optionally opens a fix pull request."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, StateGraph

from app.config import Settings
from app.github_client import GitHubClient, GitHubError
from app.logs import affected_file, extract, extract_from_zip
from app.memory import FailureRecord
from app.patches import PatchError, apply_unified_diff, validate_patch


@dataclass
class Diagnosis:
    category: str
    root_cause: str
    confidence: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "root_cause": self.root_cause,
            "confidence": round(self.confidence, 4),
        }


class Diagnoser(Protocol):
    def diagnose(self, signature: str, error_window: str, matches: list[dict]) -> Diagnosis:
        ...

    def propose_fix(
        self,
        *,
        file_path: str | None,
        file_contents: str | None,
        matches: list[dict],
        diagnosis: Diagnosis,
    ) -> str:
        ...


class RetrievalDiagnoser:
    """Use similar past failures when no LLM client is configured."""

    def diagnose(self, signature: str, error_window: str, matches: list[dict]) -> Diagnosis:
        if not matches:
            return Diagnosis(
                category="other",
                root_cause="No similar past failure was above the similarity threshold.",
                confidence=0.1,
            )
        top = matches[0]
        cause = signature or top.get("root_cause") or "Unclassified failure"
        return Diagnosis(top.get("category") or "other", cause, float(top.get("similarity") or 0.0))

    def propose_fix(
        self,
        *,
        file_path: str | None,
        file_contents: str | None,
        matches: list[dict],
        diagnosis: Diagnosis,
    ) -> str:
        if not file_path or file_contents is None:
            return ""
        for match in matches:
            diff = match.get("fix_diff") or ""
            if not diff:
                continue
            try:
                apply_unified_diff(file_contents, diff)
            except PatchError:
                continue
            return diff
        return ""


class OpenAIDiagnoser:
    def __init__(self, client: Any, model: str):
        self.client = client
        self.model = model

    def diagnose(self, signature: str, error_window: str, matches: list[dict]) -> Diagnosis:
        context = [
            {
                "category": match.get("category"),
                "root_cause": match.get("root_cause"),
                "similarity": match.get("similarity"),
            }
            for match in matches
        ]
        prompt = (
            "You diagnose failed GitHub Actions runs. "
            "Allowed categories: dependency, flaky_test, config, timeout, other. "
            "Scope is build, dependency, configuration, and test-infrastructure failures. "
            "Use the similar past failures as evidence. "
            "If the evidence is weak, set confidence below 0.55 and do not guess a specific fix. "
            "Return JSON with keys category, root_cause, and confidence (a number from 0 to 1).\n\n"
            f"Error signature:\n{signature}\n\n"
            f"Error window:\n{error_window}\n\n"
            f"Similar past failures:\n{json.dumps(context)}"
        )
        payload = self._complete(prompt)
        return Diagnosis(
            category=str(payload.get("category") or "other"),
            root_cause=str(payload.get("root_cause") or signature),
            confidence=float(payload.get("confidence") or 0.0),
        )

    def propose_fix(
        self,
        *,
        file_path: str | None,
        file_contents: str | None,
        matches: list[dict],
        diagnosis: Diagnosis,
    ) -> str:
        examples = [match.get("fix_diff") for match in matches if match.get("fix_diff")][:2]
        prompt = (
            "Propose a unified diff that fixes this CI failure. "
            "Only change a workflow file or a dependency/config manifest. "
            "The diff must apply to the file contents below. "
            "Return JSON with a single key, diff.\n\n"
            f"File path: {file_path}\n"
            f"File contents:\n{file_contents}\n\n"
            f"Diagnosis: {diagnosis.category}: {diagnosis.root_cause}\n"
            f"Example diffs from similar failures:\n{json.dumps(examples)}"
        )
        payload = self._complete(prompt)
        return str(payload.get("diff") or "")

    def _complete(self, prompt: str) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Reply with a single JSON object and nothing else."},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)


class AgentState(TypedDict, total=False):
    repo: str
    run_id: int
    approved: bool
    mode: str
    raw_log: str
    signature: str
    error_window: str
    file_path: str | None
    file_contents: str | None
    attempts: int
    matches: list
    category: str
    root_cause: str
    confidence: float
    declined: bool
    report: str | None
    patch: str | None
    patch_valid: bool
    validation_error: str | None
    patched: str | None
    pr_url: str | None
    outcome: str


@dataclass
class Services:
    settings: Settings
    memory: Any
    diagnoser: Diagnoser
    github: GitHubClient | None = None
    graph: Any = None


def build_graph(services: Services):
    settings = services.settings

    def ingest(state: dict) -> dict:
        if state.get("raw_log"):
            raw = state["raw_log"]
            extracted = extract(raw, tail=settings.log_tail_lines)
        elif services.github is None:
            raise RuntimeError("No log was provided and no GitHub client is configured")
        else:
            blob = services.github.download_logs(state["repo"], int(state["run_id"]))
            if blob[:2] == b"PK":
                extracted = extract_from_zip(blob, tail=settings.log_tail_lines)
                raw = extracted.error_window
            else:
                raw = blob.decode("utf-8", errors="replace")
                extracted = extract(raw, tail=settings.log_tail_lines)
        file_path = state.get("file_path") or affected_file(raw) or affected_file(extracted.error_window)
        file_contents = state.get("file_contents")
        if file_contents is None and file_path and services.github is not None:
            try:
                file_contents = services.github.get_file(state["repo"], file_path)
            except GitHubError:
                file_contents = None
        return {
            "signature": extracted.signature,
            "error_window": extracted.error_window,
            "file_path": file_path,
            "file_contents": file_contents,
            "attempts": state.get("attempts") or 0,
        }

    def retrieve(state: dict) -> dict:
        matches = services.memory.search(state.get("signature") or "", k=3)
        return {"matches": matches}

    def diagnose(state: dict) -> dict:
        diagnosis = services.diagnoser.diagnose(
            state.get("signature") or "",
            state.get("error_window") or "",
            state.get("matches") or [],
        )
        return diagnosis.as_dict()

    def route(state: dict) -> dict:
        confidence = float(state.get("confidence") or 0.0)
        declined = confidence < settings.confidence_threshold or not state.get("matches")
        report = None
        if declined:
            report = (
                "Declined to draft a fix because confidence "
                f"{confidence:.2f} is below {settings.confidence_threshold:.2f}. "
                f"category={state.get('category')}. {state.get('root_cause')}"
            )
        return {"declined": declined, "report": report}

    def draft_fix(state: dict) -> dict:
        diagnosis = Diagnosis(
            category=state.get("category") or "other",
            root_cause=state.get("root_cause") or "",
            confidence=float(state.get("confidence") or 0.0),
        )
        diff = services.diagnoser.propose_fix(
            file_path=state.get("file_path"),
            file_contents=state.get("file_contents"),
            matches=state.get("matches") or [],
            diagnosis=diagnosis,
        )
        return {"patch": diff}

    def validate(state: dict) -> dict:
        ok, error, patched = validate_patch(
            state.get("file_path") or "",
            state.get("file_contents") or "",
            state.get("patch") or "",
        )
        return {
            "attempts": int(state.get("attempts") or 0) + 1,
            "patch_valid": ok,
            "validation_error": error,
            "patched": patched,
        }

    def open_pr(state: dict) -> dict:
        if services.github is None:
            return {"outcome": "pr_failed", "report": "GitHub client is not configured"}
        repo = state["repo"]
        run_id = state["run_id"]
        branch = f"ci-fix/{run_id}"
        body = (
            "## Diagnosis\n\n"
            f"- Category: {state.get('category')}\n"
            f"- Confidence: {float(state.get('confidence') or 0):.2f}\n"
            f"- Root cause: {state.get('root_cause')}\n\n"
            "This pull request was opened by the CI remediation agent. "
            "It does not merge itself.\n"
        )
        try:
            url = services.github.open_pull_request(
                repo,
                state["file_path"],
                state["patched"],
                branch,
                f"Fix CI failure #{run_id} ({state.get('category')})",
                body,
            )
        except GitHubError as exc:
            return {"outcome": "pr_failed", "report": str(exc)}
        return {"pr_url": url, "outcome": "pr_opened"}

    def record(state: dict) -> dict:
        if state.get("declined"):
            return {"outcome": "declined"}
        if state.get("mode") == "diagnose":
            return {"outcome": "diagnosed"}
        if not state.get("patch_valid"):
            return {
                "outcome": "fix_failed",
                "report": state.get("report") or state.get("validation_error") or "Patch did not validate",
            }
        services.memory.add(
            FailureRecord(
                repo=state["repo"],
                run_id=int(state["run_id"]),
                signature=state.get("signature") or "",
                category=state.get("category"),
                root_cause=state.get("root_cause"),
                fix_diff=state.get("patch"),
                fix_worked=None,
            )
        )
        outcome = state.get("outcome")
        if outcome is None:
            if state.get("mode") == "propose":
                outcome = "proposed"
            elif not state.get("approved"):
                outcome = "awaiting_approval"
            else:
                outcome = "recorded"
        return {"outcome": outcome}

    def after_route(state: dict) -> str:
        if state.get("declined") or state.get("mode") == "diagnose":
            return "record"
        return "draft_fix"

    def after_validate(state: dict) -> str:
        if state.get("patch_valid"):
            if state.get("approved") and state.get("mode") != "propose":
                return "open_pr"
            return "record"
        if int(state.get("attempts") or 0) < settings.retry_cap:
            return "draft_fix"
        return "record"

    builder = StateGraph(AgentState)
    for name, node in (
        ("ingest", ingest),
        ("retrieve", retrieve),
        ("diagnose", diagnose),
        ("route", route),
        ("draft_fix", draft_fix),
        ("validate", validate),
        ("open_pr", open_pr),
        ("record", record),
    ):
        builder.add_node(name, node)
    builder.set_entry_point("ingest")
    builder.add_edge("ingest", "retrieve")
    builder.add_edge("retrieve", "diagnose")
    builder.add_edge("diagnose", "route")
    builder.add_conditional_edges("route", after_route, {"record": "record", "draft_fix": "draft_fix"})
    builder.add_edge("draft_fix", "validate")
    builder.add_conditional_edges(
        "validate",
        after_validate,
        {"draft_fix": "draft_fix", "open_pr": "open_pr", "record": "record"},
    )
    builder.add_edge("open_pr", "record")
    builder.add_edge("record", END)
    return builder.compile()
