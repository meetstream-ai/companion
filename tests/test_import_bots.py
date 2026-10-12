"""
Importing past bots from MeetStream, and deleting agents there.

MeetStream is mocked at the HTTP layer (httpx_mock) rather than at our
client, because the bugs here were about *which URL* we called: the bare
GET /bots/{id} is not in MeetStream's API and answered 500 for some bots,
and the listing is paginated, so without following nextCursor the import
list quietly stopped at whatever the first page covered.
"""
import json
from urllib.parse import parse_qs, urlparse

import pytest

MS = "https://api.meetstream.ai/api/v1"


async def _with_key(authed_client, monkeypatch):
    """Give the member a MeetStream key without a real verification call."""
    from app.services import meetstream as meetstream_module

    async def list_mia_agents(self, api_key=None):
        return {"agent_configs": []}

    # Patch the class, not the shared instance: undoing an instance patch
    # leaves a bound method in the instance's __dict__ that shadows any
    # class-level patch a later test makes.
    monkeypatch.setattr(meetstream_module.MeetStreamClient, "list_mia_agents", list_mia_agents)
    r = await authed_client.put("/api/agent/api-key", json={"meetstream_api_key": "ms_test_key"})
    assert r.status_code == 200, r.text


def _bot(i, **extra):
    return {"bot_id": f"bot-{i}", "meeting_url": f"https://meet.google.com/abc-{i}", "platform": "GMeet",
            "status": "completed", "bot_username": f"Bot {i}", "start_time": f"2026-0{1 + i % 8}-1{i % 9}T10:00:00Z", **extra}


@pytest.mark.asyncio
async def test_importable_follows_every_page_and_passes_date_filters(authed_client, monkeypatch, httpx_mock):
    await _with_key(authed_client, monkeypatch)
    # Three pages. The cursor comes back as a query parameter on the next call.
    httpx_mock.add_response(url=f"{MS}/bots?from=2026-01-01&to=2026-06-30", json={"bots": [_bot(1), _bot(2)], "hasNextPage": True, "nextCursor": "c2"})
    httpx_mock.add_response(url=f"{MS}/bots?from=2026-01-01&to=2026-06-30&cursor=c2", json={"bots": [_bot(3)], "hasNextPage": True, "nextCursor": "c3"})
    httpx_mock.add_response(url=f"{MS}/bots?from=2026-01-01&to=2026-06-30&cursor=c3", json={"bots": [_bot(4)], "hasNextPage": False, "nextCursor": None})

    r = await authed_client.get("/api/meetings/importable", params={"from": "2026-01-01", "to": "2026-06-30"})
    assert r.status_code == 200, r.text
    assert [b["bot_id"] for b in r.json()["importable"]] == ["bot-1", "bot-2", "bot-3", "bot-4"]
    assert len(httpx_mock.get_requests()) == 3

    # A malformed date is refused before MeetStream is asked.
    r = await authed_client.get("/api/meetings/importable", params={"from": "yesterday"})
    assert r.status_code == 400 and "YYYY-MM-DD" in r.json()["detail"]


@pytest.mark.asyncio
async def test_importable_stops_if_the_server_ignores_the_cursor(authed_client, monkeypatch, httpx_mock):
    """A cursor the server does not honour must not loop forever."""
    await _with_key(authed_client, monkeypatch)
    same = {"bots": [_bot(1)], "hasNextPage": True, "nextCursor": "again"}
    httpx_mock.add_response(url=f"{MS}/bots", json=same)
    httpx_mock.add_response(url=f"{MS}/bots?cursor=again", json=same)
    r = await authed_client.get("/api/meetings/importable")
    assert r.status_code == 200
    assert [b["bot_id"] for b in r.json()["importable"]] == ["bot-1"]
    assert len(httpx_mock.get_requests()) == 2


@pytest.mark.asyncio
async def test_import_uses_the_detail_path_and_the_transcript_from_it(authed_client, monkeypatch, httpx_mock):
    await _with_key(authed_client, monkeypatch)
    httpx_mock.add_response(
        url=f"{MS}/bots/bot-9/detail",
        json={"bot_details": {"MeetingLink": "https://meet.google.com/xyz", "StartTime": "2026-03-01T10:00:00Z",
                              "EndTime": "2026-03-01T10:45:00Z", "transcript_id": "tr-9"}},
    )
    monkeypatch.setattr("app.services.processing.processing_pipeline.process_meeting_transcript", _noop, raising=False)
    r = await authed_client.post("/api/meetings/import", json={"bot_id": "bot-9", "platform": "GMeet", "meeting_url": "https://meet.google.com/xyz"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["meetstream_bot_id"] == "bot-9"
    assert body["processing_status"] == "queued_for_processing"
    assert body["started_at"].startswith("2026-03-01T10:00")
    called = [str(q.url) for q in httpx_mock.get_requests()]
    assert called == [f"{MS}/bots/bot-9/detail"]  # never the bare /bots/{id}


@pytest.mark.asyncio
async def test_import_survives_a_500_from_detail_by_asking_for_transcriptions(authed_client, monkeypatch, httpx_mock):
    """The bug report: MeetStream answered 500 for the bot's detail. The
    listing already had the URL and platform; the transcript id comes from
    the bot's transcription runs instead. The import goes through."""
    await _with_key(authed_client, monkeypatch)
    httpx_mock.add_response(url=f"{MS}/bots/bot-5/detail", status_code=500, text="Internal Server Error")
    httpx_mock.add_response(
        url=f"{MS}/bots/bot-5/transcriptions",
        json={"bot_id": "bot-5", "transcriptions": [
            {"transcript_id": "tr-old", "status": "failed"},
            {"transcript_id": "tr-5", "status": "completed"},
        ]},
    )
    monkeypatch.setattr("app.services.processing.processing_pipeline.process_meeting_transcript", _noop, raising=False)
    r = await authed_client.post("/api/meetings/import", json={"bot_id": "bot-5", "platform": "GMeet", "meeting_url": "https://meet.google.com/five"})
    assert r.status_code == 201, r.text
    assert r.json()["processing_status"] == "queued_for_processing"
    assert r.json()["meeting_url"] == "https://meet.google.com/five"
    detail = await authed_client.get(f"/api/meetings/{r.json()['id']}")
    assert detail.json()["meetstream_transcript_id"] == "tr-5"


@pytest.mark.asyncio
async def test_import_with_nothing_to_go_on_is_filed_as_failed_with_a_reason(authed_client, monkeypatch, httpx_mock):
    await _with_key(authed_client, monkeypatch)
    httpx_mock.add_response(url=f"{MS}/bots/bot-7/detail", status_code=500, text="boom")
    httpx_mock.add_response(url=f"{MS}/bots/bot-7/transcriptions", json={"bot_id": "bot-7", "transcriptions": []})
    r = await authed_client.post("/api/meetings/import", json={"bot_id": "bot-7", "platform": "GMeet", "meeting_url": "https://meet.google.com/seven"})
    assert r.status_code == 201, r.text
    assert r.json()["processing_status"] == "failed"
    assert "Reprocess" in r.json()["processing_error"]
    # Importing it again is a conflict, not a duplicate row.
    r = await authed_client.post("/api/meetings/import", json={"bot_id": "bot-7", "platform": "GMeet"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_delete_agent_removes_it_on_meetstream_and_from_the_member(authed_client, monkeypatch, httpx_mock):
    await _with_key(authed_client, monkeypatch)
    from app.database.connection import AsyncSessionLocal
    from app.database.repositories import UserRepository

    async with AsyncSessionLocal() as db:
        await UserRepository(db).update_settings(authed_client.user_id, {"agent_config_ids": ["ag-1", "ag-2"], "active_agent_config_id": "ag-1"})
        await db.commit()

    httpx_mock.add_response(method="DELETE", url=f"{MS}/mia?agent_config_id=ag-1", json={"message": "Agent configuration deleted successfully."})
    r = await authed_client.delete("/api/agent", params={"agent_config_id": "ag-1"})
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": True, "agent_config_id": "ag-1", "was_active": True}
    sent = httpx_mock.get_requests()[-1]
    assert sent.method == "DELETE" and parse_qs(urlparse(str(sent.url)).query) == {"agent_config_id": ["ag-1"]}

    async with AsyncSessionLocal() as db:
        user = await UserRepository(db).get_by_id(authed_client.user_id)
    assert user.settings["agent_config_ids"] == ["ag-2"]
    assert user.settings.get("active_agent_config_id") is None

    # Already gone on MeetStream: still tidied on our side, not an error.
    httpx_mock.add_response(method="DELETE", url=f"{MS}/mia?agent_config_id=ag-2", status_code=404, json={"detail": "not found"})
    r = await authed_client.delete("/api/agent", params={"agent_config_id": "ag-2"})
    assert r.status_code == 200 and r.json()["was_active"] is False


@pytest.mark.asyncio
async def test_delete_agent_refuses_another_members_agent(authed_client, monkeypatch, httpx_mock):
    await _with_key(authed_client, monkeypatch)
    from app.database.connection import AsyncSessionLocal
    from app.database.repositories import UserRepository
    from app.models.database import Membership, User
    from app.security import hash_password

    async with AsyncSessionLocal() as db:
        me = await UserRepository(db).get_by_id(authed_client.user_id)
        other = User(organization_id=me.organization_id, email="other-agent@example.com", name="Other",
                     password_hash=hash_password("correct-horse-battery"), role="member", is_active=True,
                     settings={"agent_config_ids": ["theirs"]})
        db.add(other)
        await db.flush()
        db.add(Membership(user_id=other.id, organization_id=me.organization_id, role="member"))
        await db.commit()

    r = await authed_client.delete("/api/agent", params={"agent_config_id": "theirs"})
    assert r.status_code == 403
    assert httpx_mock.get_requests() == []  # MeetStream was never asked


async def _noop(*args, **kwargs):
    return None
