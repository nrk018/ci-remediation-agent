"""Local feature hashing and optional OpenAI embeddings."""

from __future__ import annotations

import hashlib
import math
import re

from app.config import Settings

_TOKEN = re.compile(r"[a-z0-9_./:=-]{2,}")
_STOPWORDS = {
    "error",
    "failed",
    "failure",
    "process",
    "completed",
    "exit",
    "code",
    "with",
    "the",
    "for",
    "and",
    "run",
    "from",
    "that",
    "this",
    "into",
    "file",
    "line",
    "step",
    "job",
    "command",
    "group",
}


def _accumulate(vector: list[float], feature: str, weight: float) -> None:
    digest = hashlib.sha256(feature.encode()).digest()
    index = int.from_bytes(digest[:4], "little") % len(vector)
    sign = 1.0 if digest[4] % 2 == 0 else -1.0
    vector[index] += sign * weight


def hash_embed(text: str, dim: int = 1536) -> list[float]:
    """Deterministic unit vector so similar signatures rank together without an API call."""
    vector = [0.0] * dim
    normalized = text.lower().strip()
    if not normalized:
        return vector
    for line in normalized.splitlines():
        line = line.strip()
        if line:
            _accumulate(vector, f"line:{line}", 3.0)
    for token in _TOKEN.findall(normalized):
        if token in _STOPWORDS:
            continue
        _accumulate(vector, f"tok:{token}", 1.0)
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    return float(sum(a * b for a, b in zip(left, right)))


def embed_text(text: str, settings: Settings, client: object | None = None) -> list[float]:
    if not settings.use_openai:
        return hash_embed(text, settings.embedding_dim)
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
    response = client.embeddings.create(model=settings.embedding_model, input=text)
    vector = list(response.data[0].embedding)
    if len(vector) != settings.embedding_dim:
        raise ValueError(
            f"embedding model {settings.embedding_model} returned {len(vector)} dims, "
            f"expected {settings.embedding_dim}"
        )
    return vector
