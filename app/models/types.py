"""
Portable column types.

The ORM models were originally written against PostgreSQL-only column types
(UUID, JSONB, ARRAY, pgvector's Vector), which made Postgres a hard
requirement. These decorators keep the native Postgres representation when
running on Postgres, and fall back to portable equivalents everywhere else, so
the same models can back a zero-setup local SQLite file.
"""
from __future__ import annotations

import uuid
from typing import Any, List, Optional

from sqlalchemy import CHAR, JSON, Float, TypeDecorator
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

POSTGRESQL = "postgresql"

#: JSON document column. Uses JSONB on Postgres for indexing and containment
#: operators, plain JSON elsewhere. Read keys with `col["k"].as_string()`,
#: which works on both, rather than JSONB-only `.astext`.
JSONDocument = JSON().with_variant(JSONB, POSTGRESQL)


class GUID(TypeDecorator):
    """UUID primary/foreign key. Native uuid on Postgres, CHAR(36) elsewhere."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == POSTGRESQL:
            return dialect.type_descriptor(PGUUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect) -> Any:
        if value is None:
            return None
        parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        if dialect.name == POSTGRESQL:
            return parsed
        return str(parsed)

    def process_result_value(self, value: Any, dialect) -> Optional[uuid.UUID]:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class GUIDArray(TypeDecorator):
    """List of UUIDs. Native uuid[] on Postgres, a JSON array elsewhere."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == POSTGRESQL:
            return dialect.type_descriptor(ARRAY(PGUUID(as_uuid=True)))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect) -> Any:
        if value is None:
            return None
        parsed = [v if isinstance(v, uuid.UUID) else uuid.UUID(str(v)) for v in value]
        if dialect.name == POSTGRESQL:
            return parsed
        return [str(v) for v in parsed]

    def process_result_value(self, value: Any, dialect) -> Optional[List[uuid.UUID]]:
        if value is None:
            return None
        return [v if isinstance(v, uuid.UUID) else uuid.UUID(str(v)) for v in value]


class Embedding(TypeDecorator):
    """
    A dense float vector.

    On Postgres this is a real pgvector column, so similarity search runs in
    the database against an ivfflat index. Elsewhere the vector is stored as a
    JSON array and similarity is computed in Python - see
    app/providers/database/portable.py. That is slower asymptotically but
    entirely adequate for a single user's local corpus, and it is what removes
    the hard pgvector dependency.
    """

    impl = JSON
    cache_ok = True

    class Comparator(TypeDecorator.Comparator):
        def cosine_distance(self, other):
            """
            pgvector's `<=>` operator.

            Only valid on Postgres; the portable backend computes similarity in
            Python instead and never builds this expression.
            """
            return self.op("<=>", return_type=Float)(other)

    comparator_factory = Comparator

    def __init__(self, dimensions: int, *args, **kwargs):
        self.dimensions = dimensions
        super().__init__(*args, **kwargs)

    def load_dialect_impl(self, dialect):
        if dialect.name == POSTGRESQL:
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dimensions))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect) -> Any:
        if value is None:
            return None
        if dialect.name == POSTGRESQL:
            return value
        return [float(v) for v in value]

    def process_result_value(self, value: Any, dialect) -> Optional[List[float]]:
        if value is None:
            return None
        if hasattr(value, "tolist"):
            return value.tolist()
        return [float(v) for v in value]
