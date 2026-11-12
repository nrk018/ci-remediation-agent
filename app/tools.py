"""Tool functions shared by the LangGraph agent and the MCP server."""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.github_client import GitHubClient
from app.graph import OpenAIDiagnoser, RetrievalDiagnoser, Services, build_graph
from app.logs import extract, extract_from_zip
from app.memory import InMemoryStore, PgVectorStore

_services: Services | None = None


def configure(services: Services) -> None:
    global _services
    _services = services


def get_services() -> Services:
    if _services is None:
        configure(build_default_services())
    assert _services is not None
    return _services


def build_default_services(settings: Settings | None = None) -> Services:
    settings = settings or Settings.from_env()
    github = GitHubClient(settings.github_token) if settings.github_token else None
    diagnoser = _build_diagnoser(settings)
    memory = _build_store(settings)
    services = Services(settings=settings, memory=memory, diagnoser=diagnoser, github=github)
    services.graph = build_graph(services)
    return services


def _build_diagnoser(settings: Settings):
    if not settings.use_openai:
        return RetrievalDiagnoser()
    from openai import OpenAI

    return OpenAIDiagnoser(OpenAI(api_key=settings.openai_api_key), settings.chat_model)


def _build_store(settings: Settings):
    if not settings.database_url:
        return InMemoryStore(settings)
    try:
        store = PgVectorStore(settings)
        store.ensure_schema()
        return store
    except Exception:
        return InMemoryStore(settings)


def _invoke(services: Services, payload: dict) -> dict:
    if services.graph is None:
        services.graph = build_graph(services)
    return services.graph.invoke(payload)


def get_failed_runs(repo: str, limit: int = 10, *, services: Services | None = None) -> list[dict[str, Any]]:
    services = services or get_services()
    if services.github is None:
        raise RuntimeError("GITHUB_TOKEN is not configured")
    runs = services.github.list_failed_runs(repo, limit)
    for run in runs:
        run.setdefault("run_id", run.get("id"))
    return runs


def fetch_logs(repo: str, run_id: int, *, services: Services | None = None, raw_log: str | None = None) -> dict[str, Any]:
    services = services or get_services()
    if raw_log is None:
        if services.github is None:
            raise RuntimeError("GITHUB_TOKEN is not configured")
        blob = services.github.download_logs(repo, run_id)
        extracted = extract_from_zip(blob) if blob[:2] == b"PK" else extract(blob.decode("utf-8", errors="replace"))
    else:
        extracted = extract(raw_log, tail=services.settings.log_tail_lines)
    return {
        "repo": repo,
        "run_id": run_id,
        "error_window": extracted.error_window,
        "signature": extracted.signature,
        "job_name": extracted.job_name,
    }


def search_similar_failures(signature: str, k: int = 3, *, services: Services | None = None) -> list[dict[str, Any]]:
    services = services or get_services()
    return services.memory.search(signature, k=k)


def diagnose_failure(
    repo: str,
    run_id: int,
    *,
    services: Services | None = None,
    raw_log: str | None = None,
    file_path: str | None = None,
    file_contents: str | None = None,
) -> dict[str, Any]:
    services = services or get_services()
    result = _invoke(
        services,
        {
            "repo": repo,
            "run_id": run_id,
            "approved": False,
            "mode": "diagnose",
            "raw_log": raw_log,
            "file_path": file_path,
            "file_contents": file_contents,
        },
    )
    return {
        "repo": repo,
        "run_id": run_id,
        "category": result.get("category"),
        "root_cause": result.get("root_cause"),
        "confidence": result.get("confidence"),
        "declined": result.get("declined"),
        "signature": result.get("signature"),
        "report": result.get("report"),
    }


def propose_fix(
    repo: str,
    run_id: int,
    *,
    services: Services | None = None,
    raw_log: str | None = None,
    file_path: str | None = None,
    file_contents: str | None = None,
) -> dict[str, Any]:
    services = services or get_services()
    result = _invoke(
        services,
        {
            "repo": repo,
            "run_id": run_id,
            "approved": False,
            "mode": "propose",
            "raw_log": raw_log,
            "file_path": file_path,
            "file_contents": file_contents,
        },
    )
    return {
        "repo": repo,
        "run_id": run_id,
        "diff": result.get("patch"),
        "patch_valid": bool(result.get("patch_valid")),
        "validation_error": result.get("validation_error"),
        "category": result.get("category"),
        "root_cause": result.get("root_cause"),
        "confidence": result.get("confidence"),
        "declined": bool(result.get("declined")),
        "attempts": result.get("attempts"),
        "outcome": result.get("outcome"),
    }


def open_fix_pr(
    repo: str,
    run_id: int,
    approved: bool = False,
    *,
    services: Services | None = None,
    raw_log: str | None = None,
    file_path: str | None = None,
    file_contents: str | None = None,
) -> dict[str, Any]:
    if not approved:
        return {
            "ok": False,
            "error": "Refusing to open a pull request without approved=true",
            "pr_url": None,
        }
    services = services or get_services()
    result = _invoke(
        services,
        {
            "repo": repo,
            "run_id": run_id,
            "approved": True,
            "mode": "remediate",
            "raw_log": raw_log,
            "file_path": file_path,
            "file_contents": file_contents,
        },
    )
    pr_url = result.get("pr_url")
    return {
        "ok": bool(pr_url),
        "pr_url": pr_url,
        "error": None if pr_url else (result.get("report") or result.get("validation_error") or result.get("outcome")),
        "category": result.get("category"),
        "root_cause": result.get("root_cause"),
        "confidence": result.get("confidence"),
        "outcome": result.get("outcome"),
    }
