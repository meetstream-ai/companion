"""
Portable search backend (SQLite and any database without vector support).

Similarity is computed in Python with numpy over candidate rows, and keyword
relevance is scored with plain LIKE matching. Neither needs an extension, a
server, or any setup at all - which is what makes "just run it" possible.

This scans candidate rows rather than using an index, so it is O(n) in corpus
size. For a single user's meeting history that is comfortably fast; shared or
very large deployments should point DATABASE_URL at Postgres instead.
"""
from __future__ import annotations

from typing import Any, List, Sequence

import numpy as np
from sqlalchemy import Integer, and_, case, func, select

from app.providers.database.base import ScoredRow, SearchBackend, tokenize

#: Upper bound on rows pulled into memory for one similarity search, so a
#: runaway corpus degrades throughput rather than exhausting RAM.
MAX_CANDIDATE_ROWS = 20_000


class PortableSearchBackend(SearchBackend):
    name = "portable"

    async def vector_search(
        self,
        model: type,
        conditions: Sequence[Any],
        query_embedding: List[float],
        *,
        limit: int,
        min_similarity: float = 0.0,
    ) -> List[ScoredRow]:
        stmt = select(model).where(and_(*conditions)).limit(MAX_CANDIDATE_ROWS)
        records = list((await self.session.execute(stmt)).scalars().all())
        if not records:
            return []

        query_vector = np.asarray(query_embedding, dtype=np.float32)
        dimensions = query_vector.shape[0]

        # A stored vector of a different width means it was written by a
        # different embedding model; comparing it would produce meaningless
        # scores, so it is skipped rather than silently mis-ranked.
        usable = [r for r in records if r.embedding is not None and len(r.embedding) == dimensions]
        if not usable:
            return []

        matrix = np.asarray([r.embedding for r in usable], dtype=np.float32)
        scores = matrix @ query_vector
        norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query_vector)
        similarities = np.divide(
            scores, norms, out=np.zeros_like(scores), where=norms > 0
        )

        # Clamped to match the Postgres backend, which derives similarity from
        # pgvector's distance as max(0, 1 - distance). Without this, opposed
        # vectors would score negative here and positive-zero there, so the
        # same min_similarity threshold would mean different things.
        ranked = sorted(zip(usable, similarities), key=lambda pair: pair[1], reverse=True)
        return [
            (record, max(0.0, float(score)))
            for record, score in ranked[:limit]
            if max(0.0, float(score)) >= min_similarity
        ]

    async def keyword_search(
        self,
        model: type,
        conditions: Sequence[Any],
        query: str,
        *,
        limit: int,
    ) -> List[ScoredRow]:
        terms = tokenize(query)
        if not terms:
            return []

        content = func.lower(model.content)
        # Relevance is the count of distinct query terms present, which
        # approximates ts_rank well enough to make hybrid fusion behave.
        matches = [
            case((content.like(f"%{_escape_like(term)}%", escape="\\"), 1), else_=0)
            for term in terms
        ]
        score = sum(matches[1:], matches[0]).cast(Integer).label("score")

        stmt = (
            select(model, score)
            .where(and_(*conditions, score > 0))
            .order_by(score.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(record, float(value)) for record, value in rows]


def _escape_like(term: str) -> str:
    """Neutralise LIKE wildcards so a query containing % or _ matches literally."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
