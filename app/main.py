"""FastAPI webhook that accepts failed workflow_run events."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Callable

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.graph import Services
from app.harness_client import probe_harness
from app.memory import probe_database
from app.tools import build_default_services, configure

Runner = Callable[[str, int], None]


def verify_signature(body: bytes, header: str, secret: str) -> bool:
    if not secret or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def create_app(
    services: Services | None = None,
    *,
    settings: Settings | None = None,
    runner: Runner | None = None,
) -> FastAPI:
    settings = settings or (services.settings if services else Settings.from_env())
    if services is None:
        services = build_default_services(settings)
    configure(services)

    app = FastAPI(title="CI Failure Remediation Agent")
    app.state.services = services

    def default_runner(repo: str, run_id: int) -> None:
        assert services is not None and services.graph is not None
        services.graph.invoke(
            {
                "repo": repo,
                "run_id": run_id,
                "approved": False,
                "mode": "remediate",
            }
        )

    app.state.runner = runner or default_runner

    @app.get("/health")
    def health() -> dict[str, str]:
        database = probe_database(settings)
        harness = probe_harness(settings)
        degraded = database == "down" or harness == "down"
        return {
            "status": "degraded" if degraded else "ok",
            "database": database,
            "harness": harness,
        }

    @app.post("/webhook")
    async def webhook(request: Request, background: BackgroundTasks) -> JSONResponse:
        body = await request.body()
        header = request.headers.get("X-Hub-Signature-256", "")
        if not verify_signature(body, header, settings.github_webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid signature")
        event = request.headers.get("X-GitHub-Event", "")
        if event != "workflow_run":
            return JSONResponse({"ignored": True, "reason": "unsupported event"})
        payload: dict[str, Any] = json.loads(body)
        workflow_run = payload.get("workflow_run") or {}
        if workflow_run.get("conclusion") != "failure":
            return JSONResponse({"ignored": True, "reason": "run did not fail"})
        repo = (payload.get("repository") or {}).get("full_name")
        run_id = workflow_run.get("id")
        if not repo or run_id is None:
            raise HTTPException(status_code=400, detail="Missing repository or run id")
        background.add_task(app.state.runner, repo, int(run_id))
        return JSONResponse({"accepted": True, "repo": repo, "run_id": run_id}, status_code=202)

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
