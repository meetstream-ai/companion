"""
Real database-backed test for the MCP write tools (add_meeting_memory,
add_meeting_note, create_action_item, update_action_item).

Exercises app.mcp.tools.execute_tool() directly against live Postgres/pgvector:
creates a memory and confirms it's retrievable via search_meeting_memory, creates
an action item and updates its status, and confirms org-scoped write isolation
(an org cannot update another org's action item).

Requires a reachable Postgres instance. Skips automatically if unreachable.
"""
import uuid
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config import settings
from app.database.repositories import OrganizationRepository, MeetingRepository
from app.models.database import Meeting, Organization
from app.mcp.tools import execute_tool


@pytest_asyncio.fixture
async def db_session():
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
async def test_write_tools_end_to_end(db_session: AsyncSession):
    suffix = uuid.uuid4().hex[:8]
    org_repo = OrganizationRepository(db_session)
    meeting_repo = MeetingRepository(db_session)

    org = await org_repo.create(name="Write Tools Test Org", slug=f"write-tools-{suffix}")
    other_org = await org_repo.create(name="Other Org", slug=f"other-org-{suffix}")

    meeting = await meeting_repo.create(
        org_id=org.id,
        meeting_url="https://meet.example.com/write-tools-test",
        title="Write Tools Integration Test Meeting",
        customer_name="Acme",
    )
    await db_session.flush()
    # execute_tool() opens its own DB session/transaction internally and commits,
    # so the org/meeting rows created here must be visible to that other
    # connection - flush isn't enough, they need to actually be committed.
    await db_session.commit()

    try:
        # --- add_meeting_memory ---
        mem_result = await execute_tool(org.id, "add_meeting_memory", {
            "meeting_id": str(meeting.id),
            "type": "requirement",
            "content": "Acme requires SSO integration before launch.",
            "speaker": "John",
            "importance": 8,
        })
        assert mem_result.get("status") == "created"
        memory_id = mem_result["id"]

        # Confirm it's actually retrievable via the read tool (embeds + indexes correctly)
        search_result = await execute_tool(org.id, "search_meeting_memory", {"query": "SSO requirement"})
        assert search_result["results_count"] > 0
        assert any("SSO" in r["content"] for r in search_result["results"])

        # A memory can't be attached to a meeting belonging to another org
        cross_org_attempt = await execute_tool(other_org.id, "add_meeting_memory", {
            "meeting_id": str(meeting.id),
            "type": "fact",
            "content": "This should not be allowed.",
        })
        assert "error" in cross_org_attempt

        # --- add_meeting_note ---
        note_result = await execute_tool(org.id, "add_meeting_note", {
            "meeting_id": str(meeting.id),
            "content": "General context note about the call.",
        })
        assert note_result.get("status") == "created"
        assert note_result["type"] == "fact"

        # --- create_action_item ---
        action_result = await execute_tool(org.id, "create_action_item", {
            "meeting_id": str(meeting.id),
            "task": "Send SOC 2 documentation",
            "owner": "Sarah",
            "due_date": "2026-09-01",
            "priority": "high",
        })
        assert action_result["owner"] == "Sarah"
        assert action_result["status"] == "open"
        action_item_id = action_result["id"]

        # Appears via the read tool
        list_result = await execute_tool(org.id, "get_action_items", {"owner": "Sarah", "status": "open"})
        assert any(a["id"] == action_item_id for a in list_result["action_items"])

        # --- update_action_item ---
        update_result = await execute_tool(org.id, "update_action_item", {
            "action_item_id": action_item_id,
            "status": "completed",
            "notes": "Sent by Sarah on time.",
        })
        assert update_result["status"] == "completed"
        assert update_result["notes"] == "Sent by Sarah on time."

        # An org cannot update another org's action item
        cross_org_update = await execute_tool(other_org.id, "update_action_item", {
            "action_item_id": action_item_id,
            "status": "cancelled",
        })
        assert "error" in cross_org_update

    finally:
        # Cleanup: cascade-delete the meeting (removes memories/action items/vectors), then the orgs.
        await db_session.execute(Meeting.__table__.delete().where(Meeting.id == meeting.id))
        await db_session.execute(Organization.__table__.delete().where(Organization.id.in_([org.id, other_org.id])))
        await db_session.commit()
