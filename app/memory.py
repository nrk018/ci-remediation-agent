"""Failure memory. Postgres/pgvector in production, in-memory cosine search in tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.config import Settings
from app.embedding import cosine, embed_text


@dataclass
class FailureRecord:
    repo: str
    run_id: int
    signature: str
    category: str | None = None
    root_cause: str | None = None
    fix_diff: str | None = None
    fix_worked: bool | None = None
    external_id: str | None = None
    embedding: list[float] | None = None
    row_id: int | None = None


class MemoryStore(Protocol):
    def add(self, record: FailureRecord) -> FailureRecord: ...

    def search(self, signature: str, k: int = 3, threshold: float | None = None) -> list[dict]: ...


def _public_match(record: FailureRecord, similarity: float) -> dict:
    return {
        "id": record.row_id,
        "external_id": record.external_id,
        "repo": record.repo,
        "run_id": record.run_id,
        "signature": record.signature,
        "category": record.category,
        "root_cause": record.root_cause,
        "fix_diff": record.fix_diff,
        "fix_worked": record.fix_worked,
        "similarity": round(similarity, 6),
    }


class InMemoryStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.rows: list[FailureRecord] = []

    def add(self, record: FailureRecord) -> FailureRecord:
        embedding = record.embedding or embed_text(record.signature, self.settings)
        stored = FailureRecord(
            repo=record.repo,
            run_id=record.run_id,
            signature=record.signature,
            category=record.category,
            root_cause=record.root_cause,
            fix_diff=record.fix_diff,
            fix_worked=record.fix_worked,
            external_id=record.external_id,
            embedding=embedding,
            row_id=len(self.rows) + 1,
        )
        self.rows.append(stored)
        return stored

    def search(self, signature: str, k: int = 3, threshold: float | None = None) -> list[dict]:
        floor = self.settings.similarity_floor if threshold is None else threshold
        query = embed_text(signature, self.settings)
        scored: list[tuple[float, FailureRecord]] = []
        for record in self.rows:
            if not record.fix_diff or record.fix_worked is False or record.embedding is None:
                continue
            similarity = cosine(query, record.embedding)
            if similarity >= floor:
                scored.append((similarity, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [_public_match(record, similarity) for similarity, record in scored[:k]]


def probe_database(settings: Settings) -> str:
    """Return ok, down, or unconfigured. Connection errors stay out of the response."""
    if not settings.database_url:
        return "unconfigured"
    try:
        store = PgVectorStore(settings)
        with store._connect(register=False) as conn:
            conn.execute("SELECT 1")
        return "ok"
    except Exception:
        return "down"


def with_ssl(database_url: str) -> str:
    """Require TLS for any host that is not this compose network or the local machine."""
    parsed = urlsplit(database_url)
    host = (parsed.hostname or "").lower()
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if host in {"", "localhost", "127.0.0.1", "db"} or "sslmode" in query:
        return database_url
    query["sslmode"] = "require"
    return urlunsplit(parsed._replace(query=urlencode(query)))


class PgVectorStore:
    def __init__(self, settings: Settings):
        if not settings.database_url:
            raise ValueError("DATABASE_URL is required for PgVectorStore")
        self.settings = settings

    def _connect(self, *, register: bool = True):
        import psycopg
        from pgvector.psycopg import register_vector

        conn = psycopg.connect(with_ssl(self.settings.database_url), connect_timeout=5)
        if register:
            register_vector(conn)
        return conn

    def ensure_schema(self) -> None:
        from pathlib import Path

        script = (Path(__file__).resolve().parent.parent / "sql" / "001_init.sql").read_text()
        with self._connect(register=False) as conn:
            for statement in script.split(";"):
                statement = statement.strip()
                if statement:
                    conn.execute(statement)
            conn.commit()

    def add(self, record: FailureRecord) -> FailureRecord:
        embedding = record.embedding or embed_text(record.signature, self.settings)
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO failures (repo, run_id, signature, embedding, category, root_cause, fix_diff, fix_worked)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    record.repo,
                    record.run_id,
                    record.signature,
                    embedding,
                    record.category,
                    record.root_cause,
                    record.fix_diff,
                    record.fix_worked,
                ),
            ).fetchone()
            conn.commit()
        record.row_id = int(row[0])
        record.embedding = embedding
        return record

    def search(self, signature: str, k: int = 3, threshold: float | None = None) -> list[dict]:
        floor = self.settings.similarity_floor if threshold is None else threshold
        query = embed_text(signature, self.settings)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, repo, run_id, signature, category, root_cause, fix_diff, fix_worked,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM failures
                WHERE fix_diff IS NOT NULL
                  AND fix_worked IS DISTINCT FROM FALSE
                  AND 1 - (embedding <=> %s::vector) >= %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query, query, floor, query, k),
            ).fetchall()
        matches = []
        for row in rows:
            matches.append(
                {
                    "id": row[0],
                    "external_id": None,
                    "repo": row[1],
                    "run_id": row[2],
                    "signature": row[3],
                    "category": row[4],
                    "root_cause": row[5],
                    "fix_diff": row[6],
                    "fix_worked": row[7],
                    "similarity": round(float(row[8]), 6),
                }
            )
        return matches
