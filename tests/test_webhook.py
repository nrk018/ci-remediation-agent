import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.graph import RetrievalDiagnoser, Services
from app.main import create_app
from app.memory import InMemoryStore


def _app(secret: str = "shh"):
    calls = []
    settings = Settings(github_webhook_secret=secret, offline=True)
    services = Services(settings=settings, memory=InMemoryStore(settings), diagnoser=RetrievalDiagnoser())
    app = create_app(
        services,
        settings=Settings(github_webhook_secret=secret),
        runner=lambda repo, run_id: calls.append((repo, run_id)),
    )
    return TestClient(app), calls


def _signed(body: bytes, secret: str = "shh") -> dict[str, str]:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {
        "X-Hub-Signature-256": f"sha256={digest}",
        "X-GitHub-Event": "workflow_run",
        "Content-Type": "application/json",
    }


def test_webhook_accepts_failure_and_ignores_success():
    client, calls = _app()
    failure = {
        "repository": {"full_name": "acme/app"},
        "workflow_run": {"id": 7, "conclusion": "failure"},
    }
    body = json.dumps(failure).encode()
    response = client.post("/webhook", content=body, headers=_signed(body))
    assert response.status_code == 202
    assert calls == [("acme/app", 7)]

    success = {
        "repository": {"full_name": "acme/app"},
        "workflow_run": {"id": 8, "conclusion": "success"},
    }
    body = json.dumps(success).encode()
    response = client.post("/webhook", content=body, headers=_signed(body))
    assert response.status_code == 200
    assert response.json()["ignored"] is True
    assert calls == [("acme/app", 7)]


def test_webhook_rejects_bad_signature():
    client, calls = _app()
    body = b'{"workflow_run": {"conclusion": "failure", "id": 1}, "repository": {"full_name": "acme/app"}}'
    response = client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=deadbeef", "X-GitHub-Event": "workflow_run"},
    )
    assert response.status_code == 401
    assert calls == []
