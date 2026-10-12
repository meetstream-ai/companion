"""
Real database-backed tenant isolation test.

test_security.py::test_tenant_isolation_boundary only simulates isolation with an
in-memory list comprehension - it doesn't exercise the actual SQLAlchemy queries in
repositories.py against Postgres. This test creates two real organizations with
overlapping, semantically similar data and verifies the org-scoped repository and
vector-search queries never leak across the boundary, end-to-end against a live DB.

Requires a reachable Postgres instance (DATABASE_URL). Skips automatically if the
database can't be reached, so this doesn't break the rest of the suite in environments
without Postgres running.
"""
import uuid
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config import settings
from app.database.repositories import OrganizationRepository, MeetingRepository, MemoryRepository, VectorRepository
from app.models.database import MemoryType
from app.services.embedding import embedding_service


@pytest_asyncio.fixture
async def db_session():
    """
    Real AsyncSession against the configured Postgres database. Never committed -
    rolled back at teardown so no test data persists. Skips the test if the database
    is unreachable rather than failing the whole suite.
    """
    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with engine.connect():
            pass
    except Exception as e:
        await engine.dispose()
        pytest.skip(f"Postgres not reachable at {settings.DATABASE_URL.split('@')[-1]}: {e}")

    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_tenant_isolation_real_db(db_session: AsyncSession):
    org_repo = OrganizationRepository(db_session)
    meeting_repo = MeetingRepository(db_session)
    memory_repo = MemoryRepository(db_session)
    vector_repo = VectorRepository(db_session)

    suffix = uuid.uuid4().hex[:8]
    org_a = await org_repo.create(name="Org A", slug=f"org-a-{suffix}")
    org_b = await org_repo.create(name="Org B", slug=f"org-b-{suffix}")

    meeting_a = await meeting_repo.create(
        org_id=org_a.id,
        meeting_url="https://meet.example.com/org-a",
        title="Org A Security Review",
        customer_name="Acme",
    )
    meeting_b = await meeting_repo.create(
        org_id=org_b.id,
        meeting_url="https://meet.example.com/org-b",
        title="Org B Security Review",
        customer_name="BetaCorp",
    )

    secret_content = "Acme requires SSO integration before launch."
    memory_a = await memory_repo.create(
        org_id=org_a.id,
        meeting_id=meeting_a.id,
        memory_type=MemoryType.REQUIREMENT,
        content=secret_content,
        speaker="John",
    )
    await memory_repo.create(
        org_id=org_b.id,
        meeting_id=meeting_b.id,
        memory_type=MemoryType.REQUIREMENT,
        content="BetaCorp requires HIPAA compliance before launch.",
        speaker="Priya",
    )

    embedding = embedding_service.embed_text(secret_content)
    await vector_repo.add_meeting_embedding(
        org_id=org_a.id,
        content=secret_content,
        embedding=embedding,
        source_type="memory",
        meeting_id=meeting_a.id,
        memory_id=memory_a.id,
    )
    await db_session.flush()

    # --- Cross-org reads must all come back empty ---
    assert await meeting_repo.get_by_id(org_b.id, meeting_a.id) is None

    org_b_memories = await memory_repo.list_memories(org_id=org_b.id, meeting_id=meeting_a.id)
    assert org_b_memories == []

    org_b_vector_hits = await vector_repo.search_meeting_memories(
        org_id=org_b.id,
        query_embedding=embedding,
        min_similarity=0.0,
        limit=10,
    )
    assert all(r.content != secret_content for r, _sim in org_b_vector_hits)

    org_b_keyword_hits = await vector_repo.search_meeting_memories_keyword(
        org_id=org_b.id,
        query="SSO",
        limit=10,
    )
    assert all(r.content != secret_content for r, _rank in org_b_keyword_hits)

    # --- Org A must still see its own data (guards against a query bug that hides everything) ---
    assert await meeting_repo.get_by_id(org_a.id, meeting_a.id) is not None

    org_a_vector_hits = await vector_repo.search_meeting_memories(
        org_id=org_a.id,
        query_embedding=embedding,
        min_similarity=0.0,
        limit=10,
    )
    assert any(r.content == secret_content for r, _sim in org_a_vector_hits)
