"""Apply the pgvector schema and confirm a similarity search against DATABASE_URL."""

from __future__ import annotations

from app.config import Settings
from app.memory import FailureRecord, PgVectorStore


def apply_and_verify(store: PgVectorStore) -> None:
    store.ensure_schema()
    record = store.add(
        FailureRecord(
            repo="example/schema-check",
            run_id=0,
            signature="schema check dependency resolution failed pinned versions",
            category="dependency",
            root_cause="schema check",
            fix_diff="diff --git a/requirements.txt",
            fix_worked=True,
        )
    )
    try:
        matches = store.search(record.signature, k=1, threshold=0.99)
        if not matches or matches[0]["id"] != record.row_id:
            raise RuntimeError("similarity search did not return the row just inserted")
    finally:
        with store._connect() as conn:
            conn.execute("DELETE FROM failures WHERE id = %s", (record.row_id,))
            conn.commit()


def main() -> None:
    settings = Settings.from_env()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is not set. Add the RDS URL to .env, then run this again.")
    apply_and_verify(PgVectorStore(settings))
    print("schema applied; similarity search returned the inserted row")


if __name__ == "__main__":
    main()
