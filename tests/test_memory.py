from app.config import Settings
from app.memory import FailureRecord, InMemoryStore


def test_search_ranks_the_known_failure_first_and_rejects_noise():
    settings = Settings(offline=True, similarity_floor=0.35)
    store = InMemoryStore(settings)
    store.add(
        FailureRecord(
            repo="example/ci-fixtures",
            run_id=1,
            signature="dependency resolution failed cannot satisfy pinned versions numpy pandas",
            category="dependency",
            root_cause="pin conflict",
            fix_diff="diff --git a/requirements.txt",
            fix_worked=True,
        )
    )
    store.add(
        FailureRecord(
            repo="example/ci-fixtures",
            run_id=2,
            signature="lint format checker rejected whitespace style ruff",
            category="other",
            root_cause="format",
            fix_diff="diff --git a/workflow.yml",
            fix_worked=True,
        )
    )
    matches = store.search(
        "dependency resolution failed cannot satisfy pinned versions numpy pandas wheelhouse",
        k=3,
    )
    assert matches
    assert matches[0]["category"] == "dependency"
    assert matches[0]["run_id"] == 1
    assert store.search("quartz mailbox drifted sideways", k=3) == []
