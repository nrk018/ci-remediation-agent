import json
from types import SimpleNamespace

from app.config import Settings
from app.graph import OpenAIDiagnoser, RetrievalDiagnoser, Services, build_graph
from app.logs import extract
from app.memory import FailureRecord, InMemoryStore
from app.patches import make_unified_diff
from app.tools import open_fix_pr, propose_fix


BEFORE = "name: ci\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
AFTER = "name: ci\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-22.04\n"
PATH = ".github/workflows/ci.yml"
LOG = (
    "2024-11-01T12:00:00.0000000Z ##[group]Run bash\n"
    "2024-11-01T12:00:01.0000000Z Affected file: .github/workflows/ci.yml\n"
    "2024-11-01T12:00:02.0000000Z ERROR: dependency resolution failed cannot satisfy pinned versions runner image\n"
    "2024-11-01T12:00:03.0000000Z ##[error]Process completed with exit code 1.\n"
)


def _services(diff: str, *, retry_cap: int = 2) -> Services:
    settings = Settings(offline=True, confidence_threshold=0.55, similarity_floor=0.35, retry_cap=retry_cap)
    store = InMemoryStore(settings)
    store.add(
        FailureRecord(
            repo="acme/app",
            run_id=1,
            signature=extract(LOG).signature,
            category="dependency",
            root_cause="runner image pin",
            fix_diff=diff,
            fix_worked=True,
        )
    )
    services = Services(settings=settings, memory=store, diagnoser=RetrievalDiagnoser())
    services.graph = build_graph(services)
    return services


def test_low_confidence_stops_before_a_patch():
    settings = Settings(offline=True, confidence_threshold=0.55, similarity_floor=0.35, retry_cap=2)
    services = Services(
        settings=settings,
        memory=InMemoryStore(settings),
        diagnoser=RetrievalDiagnoser(),
    )
    services.graph = build_graph(services)
    result = propose_fix(
        "acme/app",
        9,
        services=services,
        raw_log=LOG,
        file_path=PATH,
        file_contents=BEFORE,
    )
    assert result["declined"] is True
    assert result["diff"] in (None, "")
    assert result["outcome"] == "declined"


def test_valid_patch_waits_for_approval_and_retry_cap_stops():
    diff = make_unified_diff(PATH, BEFORE, AFTER)
    proposed = propose_fix(
        "acme/app",
        9,
        services=_services(diff),
        raw_log=LOG,
        file_path=PATH,
        file_contents=BEFORE,
    )
    assert proposed["declined"] is False
    assert proposed["patch_valid"] is True
    assert proposed["outcome"] == "proposed"
    assert proposed["attempts"] == 1

    broken = make_unified_diff(PATH, BEFORE, "runs-on: [\n")
    failed = propose_fix(
        "acme/app",
        9,
        services=_services(broken),
        raw_log=LOG,
        file_path=PATH,
        file_contents=BEFORE,
    )
    assert failed["patch_valid"] is False
    assert failed["attempts"] == 2
    assert failed["outcome"] == "fix_failed"


class FakeGitHub:
    def __init__(self):
        self.branch = None
        self.content = None

    def open_pull_request(self, repo, path, content, branch, title, body, base="main", commit_message=None):
        self.branch = branch
        self.content = content
        assert "Category" in body
        return "https://github.com/acme/app/pull/4"


def test_approved_open_pr_and_refusal():
    refused = open_fix_pr("acme/app", 9, approved=False)
    assert refused["ok"] is False
    assert refused["pr_url"] is None

    github = FakeGitHub()
    services = _services(make_unified_diff(PATH, BEFORE, AFTER))
    services.github = github
    services.graph = build_graph(services)
    opened = open_fix_pr(
        "acme/app",
        9,
        approved=True,
        services=services,
        raw_log=LOG,
        file_path=PATH,
        file_contents=BEFORE,
    )
    assert opened["ok"] is True
    assert opened["pr_url"] == "https://github.com/acme/app/pull/4"
    assert github.branch == "ci-fix/9"
    assert github.content == AFTER


def test_openai_diagnoser_parses_structured_json():
    def create(**kwargs):
        if "unified diff" in kwargs["messages"][1]["content"]:
            content = json.dumps({"diff": "--- a/x\n+++ b/x\n"})
        else:
            content = json.dumps(
                {"category": "timeout", "root_cause": "step timed out", "confidence": 0.91}
            )
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    diagnoser = OpenAIDiagnoser(client, "gpt-4o-mini")
    diagnosis = diagnoser.diagnose("signature", "window", [])
    assert diagnosis.category == "timeout"
    assert diagnosis.confidence == 0.91
    assert diagnoser.propose_fix(
        file_path="requirements.txt",
        file_contents="a\n",
        matches=[],
        diagnosis=diagnosis,
    ).startswith("---")
