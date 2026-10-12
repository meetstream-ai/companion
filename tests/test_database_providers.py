"""
Tests for the database abstraction.

The point of these is that the application behaves the same whichever database
backs it, so they exercise the portable (SQLite) path that has no pgvector and
no Postgres full-text search to lean on.
"""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.connection import dialect_of, normalize_database_url
from app.models.database import Base, Memory, MemoryType, Meeting, MeetingMemoryEmbedding, Organization
from app.providers.database import get_search_backend
from app.providers.database.base import tokenize
from app.providers.database.portable import PortableSearchBackend

ORG_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        s.add(Organization(id=ORG_ID, name="Test", slug="test", settings={}))
        await s.commit()
        yield s
    await engine.dispose()


async def _add_embedding(session, content, vector, **metadata):
    record = MeetingMemoryEmbedding(
        organization_id=ORG_ID,
        source_type="memory",
        content=content,
        embedding=vector,
        metadata_=metadata,
    )
    session.add(record)
    await session.commit()
    return record


# --------------------------------------------------------------------------
# URL handling
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "given,expected",
    [
        ("sqlite:///app.db", "sqlite+aiosqlite:///app.db"),
        ("sqlite+aiosqlite:///app.db", "sqlite+aiosqlite:///app.db"),
        ("postgresql://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        ("postgres://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        ("postgresql+asyncpg://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
    ],
)
def test_sync_urls_are_upgraded_to_async_drivers(given, expected):
    assert normalize_database_url(given) == expected


@pytest.mark.parametrize(
    "url,dialect",
    [
        ("sqlite+aiosqlite:///a.db", "sqlite"),
        ("postgresql+asyncpg://u@h/d", "postgresql"),
    ],
)
def test_dialect_detection(url, dialect):
    assert dialect_of(url) == dialect


# --------------------------------------------------------------------------
# Portable column types
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_uuid_json_and_vector_columns_round_trip_on_sqlite(session):
    """These columns were Postgres-only types before the abstraction existed."""
    meeting = Meeting(organization_id=ORG_ID, title="Kickoff", custom_attributes={"a": 1})
    session.add(meeting)
    await session.commit()

    memory = Memory(
        organization_id=ORG_ID,
        meeting_id=meeting.id,
        type=MemoryType.DECISION,
        content="We ship on Friday",
        source_segment_ids=[uuid.uuid4(), uuid.uuid4()],
        metadata_={"nested": {"ok": True}},
    )
    session.add(memory)
    await session.commit()

    assert isinstance(memory.id, uuid.UUID)
    assert isinstance(meeting.id, uuid.UUID)
    assert memory.type is MemoryType.DECISION
    assert len(memory.source_segment_ids) == 2
    assert all(isinstance(v, uuid.UUID) for v in memory.source_segment_ids)
    assert memory.metadata_["nested"]["ok"] is True


@pytest.mark.asyncio
async def test_embedding_column_round_trips_floats(session):
    record = await _add_embedding(session, "hello", [0.25, -0.5, 0.75])
    assert record.embedding == pytest.approx([0.25, -0.5, 0.75])


# --------------------------------------------------------------------------
# Backend selection
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sqlite_session_selects_the_portable_backend(session):
    assert isinstance(get_search_backend(session), PortableSearchBackend)


# --------------------------------------------------------------------------
# Vector search without pgvector
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vector_search_ranks_by_cosine_similarity(session):
    await _add_embedding(session, "aligned", [1.0, 0.0, 0.0])
    await _add_embedding(session, "orthogonal", [0.0, 1.0, 0.0])
    await _add_embedding(session, "opposite", [-1.0, 0.0, 0.0])

    hits = await get_search_backend(session).vector_search(
        MeetingMemoryEmbedding,
        [MeetingMemoryEmbedding.organization_id == ORG_ID],
        [1.0, 0.0, 0.0],
        limit=3,
    )

    assert [record.content for record, _ in hits] == ["aligned", "orthogonal", "opposite"]
    assert hits[0][1] == pytest.approx(1.0, abs=1e-5)


@pytest.mark.asyncio
async def test_vector_search_applies_minimum_similarity(session):
    await _add_embedding(session, "aligned", [1.0, 0.0, 0.0])
    await _add_embedding(session, "orthogonal", [0.0, 1.0, 0.0])

    hits = await get_search_backend(session).vector_search(
        MeetingMemoryEmbedding,
        [MeetingMemoryEmbedding.organization_id == ORG_ID],
        [1.0, 0.0, 0.0],
        limit=10,
        min_similarity=0.5,
    )
    assert [record.content for record, _ in hits] == ["aligned"]


@pytest.mark.asyncio
async def test_vector_search_skips_vectors_of_a_different_width(session):
    """A stored vector from a different embedding model must not be mis-ranked."""
    await _add_embedding(session, "right width", [1.0, 0.0, 0.0])
    await _add_embedding(session, "wrong width", [1.0, 0.0])

    hits = await get_search_backend(session).vector_search(
        MeetingMemoryEmbedding,
        [MeetingMemoryEmbedding.organization_id == ORG_ID],
        [1.0, 0.0, 0.0],
        limit=10,
    )
    assert [record.content for record, _ in hits] == ["right width"]


@pytest.mark.asyncio
async def test_vector_search_is_scoped_by_conditions(session):
    await _add_embedding(session, "mine", [1.0, 0.0, 0.0], speaker="Ada")
    await _add_embedding(session, "theirs", [1.0, 0.0, 0.0], speaker="Grace")

    hits = await get_search_backend(session).vector_search(
        MeetingMemoryEmbedding,
        [
            MeetingMemoryEmbedding.organization_id == ORG_ID,
            MeetingMemoryEmbedding.metadata_["speaker"].as_string().ilike("ada"),
        ],
        [1.0, 0.0, 0.0],
        limit=10,
    )
    assert [record.content for record, _ in hits] == ["mine"]


@pytest.mark.asyncio
async def test_vector_search_on_empty_corpus_returns_nothing(session):
    hits = await get_search_backend(session).vector_search(
        MeetingMemoryEmbedding,
        [MeetingMemoryEmbedding.organization_id == ORG_ID],
        [1.0, 0.0, 0.0],
        limit=5,
    )
    assert hits == []


# --------------------------------------------------------------------------
# Keyword search without Postgres full-text
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_keyword_search_ranks_by_number_of_matching_terms(session):
    await _add_embedding(session, "migrate the database next quarter", [1.0, 0.0, 0.0])
    await _add_embedding(session, "the database is fine", [0.0, 1.0, 0.0])
    await _add_embedding(session, "unrelated discussion", [0.0, 0.0, 1.0])

    hits = await get_search_backend(session).keyword_search(
        MeetingMemoryEmbedding,
        [MeetingMemoryEmbedding.organization_id == ORG_ID],
        "database migrate",
        limit=10,
    )

    assert [record.content for record, _ in hits] == [
        "migrate the database next quarter",
        "the database is fine",
    ]
    assert hits[0][1] == 2.0


@pytest.mark.asyncio
async def test_keyword_search_is_case_insensitive(session):
    await _add_embedding(session, "The SOC2 Report", [1.0, 0.0, 0.0])

    hits = await get_search_backend(session).keyword_search(
        MeetingMemoryEmbedding,
        [MeetingMemoryEmbedding.organization_id == ORG_ID],
        "soc2",
        limit=5,
    )
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_keyword_search_treats_wildcards_literally(session):
    """A bare % must not turn into a match-everything query."""
    await _add_embedding(session, "ordinary content", [1.0, 0.0, 0.0])

    hits = await get_search_backend(session).keyword_search(
        MeetingMemoryEmbedding,
        [MeetingMemoryEmbedding.organization_id == ORG_ID],
        "100%",
        limit=5,
    )
    assert hits == []


@pytest.mark.asyncio
async def test_keyword_search_with_no_usable_terms_returns_nothing(session):
    await _add_embedding(session, "content", [1.0, 0.0, 0.0])

    hits = await get_search_backend(session).keyword_search(
        MeetingMemoryEmbedding,
        [MeetingMemoryEmbedding.organization_id == ORG_ID],
        "a I",
        limit=5,
    )
    assert hits == []


@pytest.mark.parametrize(
    "query,expected",
    [
        ("Database MIGRATE database", ["database", "migrate"]),
        ("a to be finished", ["finished"]),  # stopwords dropped
        ("", []),
    ],
)
def test_tokenize_deduplicates_and_lowercases(query, expected):
    assert tokenize(query) == expected


# ---------------------------------------------------------------------------
# Provider catalog -> URL
# ---------------------------------------------------------------------------

import pytest as _pytest

from app.providers.database.catalog import build_database_url, describe_databases, provider_for_url


def test_catalog_lists_available_and_coming_soon():
    names = {entry["name"]: entry for entry in describe_databases()}
    assert names["sqlite"]["available"] and names["sqlite"]["recommended"]
    assert names["mysql"]["available"] is False


def test_sqlite_defaults_to_data_directory():
    assert build_database_url("sqlite", {}) == "sqlite+aiosqlite:///data/meet-companion.db"
    assert build_database_url("sqlite", {"path": "/srv/mc.db"}) == "sqlite+aiosqlite:////srv/mc.db"


def test_postgres_fields_become_asyncpg_url_with_escaping():
    url = build_database_url("postgresql", {
        "host": "db.local", "port": "5433", "database": "meet", "user": "me@corp", "password": "p@ss/w", "sslmode": "require",
    })
    assert url == "postgresql+asyncpg://me%40corp:p%40ss%2Fw@db.local:5433/meet?ssl=require"


def test_postgres_requires_host_and_user():
    with _pytest.raises(ValueError, match="Host"):
        build_database_url("postgresql", {"database": "x", "user": "u"})


def test_hosted_string_is_normalized_to_async_driver():
    url = build_database_url("neon", {"url": "postgresql://u:p@ep-1.neon.tech/db?sslmode=require"})
    assert url == "postgresql+asyncpg://u:p@ep-1.neon.tech/db?ssl=require"
    assert provider_for_url(url) == "neon"


def test_unavailable_provider_is_refused():
    with _pytest.raises(ValueError, match="not supported"):
        build_database_url("mysql", {"url": "mysql://x"})


# ---------------------------------------------------------------------------
# Whichever database the suite is running on, the live backend must match
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_backend_matches_live_dialect():
    """On Postgres (CI) this proves pgvector search runs; on SQLite the portable one."""
    from app.database.connection import AsyncSessionLocal, current_dialect
    from app.providers.database import get_search_backend
    from app.providers.database.postgres import PostgresSearchBackend
    from app.models.database import Note

    async with AsyncSessionLocal() as session:
        backend = get_search_backend(session)
        if current_dialect() == "postgresql":
            assert isinstance(backend, PostgresSearchBackend)
        else:
            assert isinstance(backend, PortableSearchBackend)
        # Empty result, but the query must be valid SQL for this dialect.
        assert await backend.vector_search(Note, [Note.embedding.isnot(None)], [0.0] * 384, limit=3) == []
        assert await backend.keyword_search(Note, [], "nothing here", limit=3) == []


def test_neon_dashboard_string_is_accepted_as_pasted():
    """
    Live QA against Neon: its dashboard string carries `channel_binding=require`,
    which SQLAlchemy passed to asyncpg.connect() as a keyword -> "unexpected
    keyword argument 'channel_binding'". Every libpq-only parameter is dropped
    and every sslmode value (not just require) becomes asyncpg's ssl.
    """
    url = build_database_url("neon", {"url": "postgresql://u:p@ep-x-pooler.neon.tech/neondb?sslmode=require&channel_binding=require"})
    assert url == "postgresql+asyncpg://u:p@ep-x-pooler.neon.tech/neondb?ssl=require"
    url = build_database_url("postgres-url", {"url": "postgresql://u:p@h/db?sslmode=verify-full&gssencmode=disable&application_name=mc"})
    assert url == "postgresql+asyncpg://u:p@h/db?ssl=verify-full&application_name=mc"
    assert build_database_url("postgres-url", {"url": "postgresql://u:p@h/db"}) == "postgresql+asyncpg://u:p@h/db"
    # The environment path goes through the same normalisation.
    from app.database.connection import normalize_database_url
    assert normalize_database_url("postgres://u:p@h/db?channel_binding=require&sslmode=require") == "postgresql+asyncpg://u:p@h/db?ssl=require"
