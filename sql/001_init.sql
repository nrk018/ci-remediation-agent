CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS failures (
    id SERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    run_id BIGINT NOT NULL,
    signature TEXT NOT NULL,
    embedding VECTOR(1536),
    category TEXT,
    root_cause TEXT,
    fix_diff TEXT,
    fix_worked BOOLEAN,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS failures_embedding_hnsw
    ON failures USING hnsw (embedding vector_cosine_ops);
