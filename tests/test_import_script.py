"""
Tests for the workspace import script.

The real use is PostgreSQL to SQLite, but the copy path is identical for any
pair of databases: read through the models, write through the models. Running
it SQLite to SQLite exercises that path - including the columns that change
representation between dialects - without needing a Postgres server.
"""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.database import (
    ActionItem,
    Base,
    Meeting,
    MeetingMemoryEmbedding,
    Memory,
    MemoryType,
    Note,
    NotebookFolder,
    Organization,
    Participant,
    User,
)
from scripts.import_from_postgres import run

ORG_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_ORG_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
EMAIL = "owner@example.com"


@pytest_asyncio.fixture
async def source_url(tmp_path):
    """A stand-in for the production database, with one workspace populated."""
    path = tmp_path / "source.db"
    url = f"sqlite+aiosqlite:///{path.as_posix()}"

    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        session.add(Organization(id=ORG_ID, name="Mine", slug="mine", settings={"a": 1}))
        session.add(Organization(id=OTHER_ORG_ID, name="Theirs", slug="theirs", settings={}))
        await session.commit()

        user = User(organization_id=ORG_ID, email=EMAIL, name="Owner", settings={"k": "v"})
        stranger = User(organization_id=OTHER_ORG_ID, email="other@example.com", name="Other", settings={})
        session.add_all([user, stranger])
        await session.commit()

        meeting = Meeting(
            organization_id=ORG_ID,
            title="Pricing review",
            platform="google_meet",
            status="completed",
            custom_attributes={"nested": {"ok": True}},
        )
        other_meeting = Meeting(organization_id=OTHER_ORG_ID, title="Not mine")
        session.add_all([meeting, other_meeting])
        await session.commit()

        session.add_all([
            Participant(meeting_id=meeting.id, name="Ada"),
            Memory(
                organization_id=ORG_ID,
                meeting_id=meeting.id,
                type=MemoryType.DECISION,
                content="Forty dollars per seat",
                source_segment_ids=[uuid.uuid4()],
                metadata_={"speaker": "Ada"},
            ),
            ActionItem(
                organization_id=ORG_ID,
                meeting_id=meeting.id,
                task="Send the SOC2 report",
                owner="Ada",
            ),
            MeetingMemoryEmbedding(
                organization_id=ORG_ID,
                meeting_id=meeting.id,
                source_type="memory",
                content="Forty dollars per seat",
                embedding=[0.25, -0.5, 0.75],
                metadata_={"speaker": "Ada"},
            ),
        ])
        await session.commit()

        folder = NotebookFolder(organization_id=ORG_ID, name="Work")
        session.add(folder)
        await session.commit()
        session.add(Note(organization_id=ORG_ID, folder_id=folder.id, title="Kickoff", content="notes"))
        await session.commit()

    await engine.dispose()
    return url


@pytest_asyncio.fixture
async def target_url(tmp_path):
    return f"sqlite+aiosqlite:///{(tmp_path / 'target.db').as_posix()}"


async def _rows(url, model):
    engine = create_async_engine(url)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        rows = list((await session.execute(select(model))).scalars().all())
    await engine.dispose()
    return rows


@pytest.mark.asyncio
async def test_import_copies_the_whole_workspace(source_url, target_url):
    await run(source_url, target_url, EMAIL, dry_run=False)

    assert [o.name for o in await _rows(target_url, Organization)] == ["Mine"]
    assert [m.title for m in await _rows(target_url, Meeting)] == ["Pricing review"]
    assert [p.name for p in await _rows(target_url, Participant)] == ["Ada"]
    assert [a.task for a in await _rows(target_url, ActionItem)] == ["Send the SOC2 report"]
    assert [n.title for n in await _rows(target_url, Note)] == ["Kickoff"]


@pytest.mark.asyncio
async def test_import_is_scoped_to_the_requested_account(source_url, target_url):
    """A shared database must not leak another workspace's meetings."""
    await run(source_url, target_url, EMAIL, dry_run=False)

    titles = [m.title for m in await _rows(target_url, Meeting)]
    assert "Not mine" not in titles
    assert [u.email for u in await _rows(target_url, User)] == [EMAIL]


@pytest.mark.asyncio
async def test_embeddings_and_json_survive_the_copy(source_url, target_url):
    """These are the columns whose representation differs between dialects."""
    await run(source_url, target_url, EMAIL, dry_run=False)

    embedding = (await _rows(target_url, MeetingMemoryEmbedding))[0]
    assert embedding.embedding == pytest.approx([0.25, -0.5, 0.75])
    assert embedding.metadata_["speaker"] == "Ada"

    memory = (await _rows(target_url, Memory))[0]
    assert memory.type is MemoryType.DECISION
    assert len(memory.source_segment_ids) == 1
    assert isinstance(memory.source_segment_ids[0], uuid.UUID)

    meeting = (await _rows(target_url, Meeting))[0]
    assert meeting.custom_attributes["nested"]["ok"] is True


@pytest.mark.asyncio
async def test_folder_links_are_preserved(source_url, target_url):
    await run(source_url, target_url, EMAIL, dry_run=False)

    folder = (await _rows(target_url, NotebookFolder))[0]
    note = (await _rows(target_url, Note))[0]
    assert note.folder_id == folder.id


@pytest.mark.asyncio
async def test_rerunning_does_not_duplicate(source_url, target_url):
    await run(source_url, target_url, EMAIL, dry_run=False)
    await run(source_url, target_url, EMAIL, dry_run=False)

    assert len(await _rows(target_url, Meeting)) == 1
    assert len(await _rows(target_url, Note)) == 1
    assert len(await _rows(target_url, MeetingMemoryEmbedding)) == 1


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(source_url, target_url):
    await run(source_url, target_url, EMAIL, dry_run=True)
    assert await _rows(target_url, Meeting) == []


@pytest.mark.asyncio
async def test_unknown_account_lists_the_accounts_that_exist(source_url, target_url):
    """A mistyped address is the common case, so show the near misses."""
    with pytest.raises(SystemExit) as exc:
        await run(source_url, target_url, "nobody@example.com", dry_run=False)

    message = str(exc.value)
    assert "No account found" in message
    assert EMAIL in message
