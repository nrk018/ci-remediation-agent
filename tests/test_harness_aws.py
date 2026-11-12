import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.graph import RetrievalDiagnoser, Services
from app.harness_client import probe_harness
from app.main import create_app
from app.memory import InMemoryStore, probe_database, with_ssl

TOKEN = "pat.secret-value"


def test_missing_harness_token_is_unconfigured():
    assert probe_harness(Settings()) == "unconfigured"


def test_harness_probe_sends_the_key_and_does_not_return_it():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == TOKEN
        assert request.headers["Harness-Account"] == "acct"
        assert request.url.path == "/gateway/ng/api/user/currentUser"
        return httpx.Response(401, text=f"rejected {TOKEN}")

    status = probe_harness(
        Settings(harness_api_token=TOKEN, harness_account_id="acct"),
        transport=httpx.MockTransport(handler),
    )
    assert status == "down"
    assert TOKEN not in status


def test_harness_probe_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "SUCCESS"})

    status = probe_harness(
        Settings(harness_api_token=TOKEN),
        transport=httpx.MockTransport(handler),
    )
    assert status == "ok"


def test_rds_url_requires_ssl_and_local_does_not():
    remote = "postgresql://ciadmin:supersecret@ci.xxxx.ap-south-1.rds.amazonaws.com:5432/ci_remediation"
    assert with_ssl(remote).endswith("?sslmode=require")
    assert with_ssl(remote + "?sslmode=require") == remote + "?sslmode=require"
    local = "postgresql://ci:ci@localhost:5432/ci_remediation"
    assert with_ssl(local) == local
    assert with_ssl("postgresql://ci:ci@db:5432/ci_remediation") == "postgresql://ci:ci@db:5432/ci_remediation"


def test_database_down_does_not_echo_the_password():
    status = probe_database(Settings(database_url="postgresql://ci:supersecret@127.0.0.1:1/ci"))
    assert status == "down"
    assert "supersecret" not in status


def test_health_reports_unconfigured_dependencies():
    settings = Settings(offline=True, github_webhook_secret="shh")
    services = Services(settings=settings, memory=InMemoryStore(settings), diagnoser=RetrievalDiagnoser())
    client = TestClient(create_app(services, settings=settings, runner=lambda *_args: None))
    body = client.get("/health").json()
    assert body == {"status": "ok", "database": "unconfigured", "harness": "unconfigured"}
    assert "shh" not in str(body)
