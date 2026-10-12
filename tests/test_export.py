"""
Export: Markdown and JSON for notes, meetings, and the whole workspace.

The cases that matter are the ones a user would notice losing: content that
survives the round trip, folder structure preserved in the archive, and - most
importantly - an export never reaching across workspaces.
"""
import io
import json
import uuid
import zipfile

import pytest

from app.services.processing import processing_pipeline


async def _note(client, title, content="", **extra):
    r = await client.post("/api/notebook/notes", json={"title": title, "content": content, **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def _meeting(client, title, transcript):
    r = await client.post("/api/meetings/upload", json={"title": title, "transcript": transcript})
    assert r.status_code == 202, r.text
    body = r.json()
    await processing_pipeline.wait_for(uuid.UUID(body["id"]))
    return body


def _filename(response):
    return response.headers.get("content-disposition", "")


# --------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_requires_a_session(client):
    assert (await client.get(f"/api/export/note/{uuid.uuid4()}")).status_code == 401
    assert (await client.get(f"/api/export/meeting/{uuid.uuid4()}")).status_code == 401
    assert (await client.get("/api/export/workspace")).status_code == 401


@pytest.mark.asyncio
async def test_export_cannot_reach_another_workspace(authed_client):
    """A note/meeting id from another workspace must 404, not export."""
    secret = await _note(authed_client, "Org A secret", "codename BLUEFALCON")
    meeting = await _meeting(authed_client, "Org A meeting", "Ana: BLUEFALCON is the codename.")

    # A second, independent workspace.
    import time

    from sqlalchemy import select

    from app.config import settings
    from app.database.connection import AsyncSessionLocal
    from app.middleware.auth_gate import COOKIE_NAME, SESSION_TTL_SECONDS, sign_session
    from app.models.database import Membership, Organization, User
    from app.security import hash_password

    org_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(Organization(id=org_id, name="Other", slug=f"other-{org_id.hex[:6]}",
                                 mcp_token=uuid.uuid4().hex, join_code=uuid.uuid4().hex[:8]))
        user = User(id=uuid.uuid4(), organization_id=org_id, name="Other",
                    email=f"other-{org_id.hex[:6]}@example.com",
                    password_hash=hash_password("x" * 12), role="owner", is_active=True)
        session.add(user)
        session.add(Membership(user_id=user.id, organization_id=org_id, role="owner"))
        await session.commit()
        token = sign_session(str(user.id), int(time.time()) + SESSION_TTL_SECONDS)

    authed_client.cookies.set(COOKIE_NAME, token)
    try:
        for path in (f"/api/export/note/{secret['id']}", f"/api/export/meeting/{meeting['id']}"):
            for fmt in ("md", "json"):
                r = await authed_client.get(path, params={"format": fmt})
                assert r.status_code == 404, f"{path} {fmt} -> {r.status_code}"
                assert "BLUEFALCON" not in r.text
        # And a whole-workspace export sees none of it.
        r = await authed_client.get("/api/export/workspace", params={"format": "json"})
        assert r.status_code == 200 and "BLUEFALCON" not in r.text
        assert r.json()["notes"] == [] and r.json()["meetings"] == []
    finally:
        authed_client.cookies.delete(COOKIE_NAME)


# --------------------------------------------------------------------------
# Notes
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_note_markdown_carries_front_matter_and_content(authed_client):
    folder = (await authed_client.post("/api/notebook/folders", json={"name": "Research"})).json()
    note = await _note(authed_client, "Pricing study", "# Findings\n\nSeats cost 42.",
                       folder_id=folder["id"], tags=["pricing", "q4"])
    r = await authed_client.get(f"/api/export/note/{note['id']}", params={"format": "md"})
    assert r.status_code == 200
    assert "text/markdown" in r.headers["content-type"]
    assert "pricing-study.md" in _filename(r)
    body = r.text
    assert body.startswith("---")
    assert 'title: "Pricing study"' in body
    assert 'folder: "Research"' in body
    assert '"pricing"' in body and '"q4"' in body
    assert "Seats cost 42." in body


@pytest.mark.asyncio
async def test_note_json_is_lossless(authed_client):
    note = await _note(authed_client, "Raw note", "line one\nline two", tags=["a"])
    r = await authed_client.get(f"/api/export/note/{note['id']}", params={"format": "json"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    payload = r.json()
    assert payload["id"] == note["id"]
    assert payload["content"] == "line one\nline two"
    assert payload["tags"] == ["a"]


@pytest.mark.asyncio
async def test_markdown_export_strips_internal_action_markers(authed_client):
    """Checkbox markers are machinery; the readable file should not show them."""
    note = await _note(authed_client, "Chores", "- [ ] buy milk")
    stored = (await authed_client.get(f"/api/notebook/notes/{note['id']}")).json()["content"]
    assert "<!-- action:" in stored, "precondition: the app adds markers"

    md = (await authed_client.get(f"/api/export/note/{note['id']}", params={"format": "md"})).text
    assert "<!-- action:" not in md and "- [ ] buy milk" in md
    # JSON keeps the raw text so a round trip stays lossless.
    js = (await authed_client.get(f"/api/export/note/{note['id']}", params={"format": "json"})).json()
    assert "<!-- action:" in js["content"]


@pytest.mark.asyncio
async def test_unknown_note_and_bad_format_are_refused(authed_client):
    note = await _note(authed_client, "Any", "x")
    assert (await authed_client.get(f"/api/export/note/{uuid.uuid4()}")).status_code == 404
    r = await authed_client.get(f"/api/export/note/{note['id']}", params={"format": "pdf"})
    assert r.status_code == 400 and "md" in r.text


# --------------------------------------------------------------------------
# Meetings
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meeting_markdown_includes_summary_items_and_transcript(authed_client):
    meeting = await _meeting(
        authed_client,
        "Quarterly review",
        "Ana: We decided to ship on Friday.\nBen: I will send the invoice.",
    )
    r = await authed_client.get(f"/api/export/meeting/{meeting['id']}", params={"format": "md"})
    assert r.status_code == 200
    assert "quarterly-review.md" in _filename(r)
    body = r.text
    assert "# Quarterly review" in body
    assert "## Transcript" in body
    assert "**Ana:** We decided to ship on Friday." in body
    assert 'title: "Quarterly review"' in body


@pytest.mark.asyncio
async def test_meeting_json_contains_the_structured_record(authed_client):
    meeting = await _meeting(authed_client, "Kickoff", "Ana: Budget is 45000.\nBen: Noted.")
    payload = (
        await authed_client.get(f"/api/export/meeting/{meeting['id']}", params={"format": "json"})
    ).json()
    assert payload["id"] == meeting["id"]
    assert payload["title"] == "Kickoff"
    assert any(s["text"] for s in payload["transcript"])
    assert isinstance(payload["memories"], list) and isinstance(payload["action_items"], list)


# --------------------------------------------------------------------------
# Whole workspace
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workspace_json_contains_everything(authed_client):
    await _note(authed_client, "Note one", "alpha")
    await _meeting(authed_client, "Meeting one", "Ana: beta.")
    r = await authed_client.get("/api/export/workspace", params={"format": "json"})
    assert r.status_code == 200
    assert "meet-companion-export-" in _filename(r) and ".json" in _filename(r)
    payload = r.json()
    assert payload["exported_at"]
    assert any(n["title"] == "Note one" for n in payload["notes"])
    assert any(m["title"] == "Meeting one" for m in payload["meetings"])


@pytest.mark.asyncio
async def test_workspace_markdown_is_a_zip_that_keeps_folder_structure(authed_client):
    parent = (await authed_client.post("/api/notebook/folders", json={"name": "Clients"})).json()
    child = (
        await authed_client.post(
            "/api/notebook/folders", json={"name": "Acme", "parent_id": parent["id"]}
        )
    ).json()
    await _note(authed_client, "Renewal", "terms", folder_id=child["id"])
    await _note(authed_client, "Loose note", "no folder")
    await _meeting(authed_client, "Sync call", "Ana: hello.")

    r = await authed_client.get("/api/export/workspace", params={"format": "md"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert ".zip" in _filename(r)

    with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
        names = archive.namelist()
        assert "notes/Clients/Acme/renewal.md" in names, names
        assert "notes/loose-note.md" in names, names
        assert any(n.startswith("meetings/") and n.endswith("sync-call.md") for n in names), names
        assert "terms" in archive.read("notes/Clients/Acme/renewal.md").decode("utf-8")


@pytest.mark.asyncio
async def test_notes_sharing_a_title_do_not_overwrite_each_other(authed_client):
    await _note(authed_client, "Duplicate", "first")
    await _note(authed_client, "Duplicate", "second")
    r = await authed_client.get("/api/export/workspace", params={"format": "md"})
    with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
        dupes = [n for n in archive.namelist() if "duplicate" in n]
        assert len(dupes) == 2, dupes
        bodies = {archive.read(n).decode("utf-8") for n in dupes}
    assert any("first" in b for b in bodies) and any("second" in b for b in bodies)


@pytest.mark.asyncio
async def test_empty_workspace_still_exports(authed_client):
    r = await authed_client.get("/api/export/workspace", params={"format": "md"})
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
        assert archive.namelist(), "zip must not be empty"
    j = await authed_client.get("/api/export/workspace", params={"format": "json"})
    assert j.status_code == 200 and j.json()["notes"] == []


@pytest.mark.asyncio
async def test_unicode_and_awkward_titles_produce_safe_filenames(authed_client):
    note = await _note(authed_client, "Zoë 🚀 <script>/../etc", "body")
    r = await authed_client.get(f"/api/export/note/{note['id']}", params={"format": "md"})
    name = _filename(r)
    assert r.status_code == 200
    assert "/" not in name.split("filename=")[1] and ".." not in name
    assert "body" in r.text


@pytest.mark.asyncio
async def test_note_that_opens_with_a_heading_is_not_given_a_second_title(authed_client):
    with_heading = await _note(authed_client, "Renewal terms", "# Terms\n\nRenewal is 21 days.")
    md = (await authed_client.get(f"/api/export/note/{with_heading['id']}", params={"format": "md"})).text
    assert md.count("\n# ") == 1, md
    assert "# Terms" in md

    plain = await _note(authed_client, "Plain note", "Just prose, no heading.")
    md2 = (await authed_client.get(f"/api/export/note/{plain['id']}", params={"format": "md"})).text
    assert "# Plain note" in md2  # a title is added when the body has none


@pytest.mark.asyncio
async def test_action_items_are_not_listed_twice_in_a_meeting(authed_client):
    meeting = await _meeting(
        authed_client, "Invoice sync", "Ana: Ben will send the invoice by Friday.\nBen: Will do."
    )
    md = (await authed_client.get(f"/api/export/meeting/{meeting['id']}", params={"format": "md"})).text
    assert "## Action items" in md
    assert "Action items raised" not in md, "action_item memories duplicate the list below"
    # The structured record still keeps everything.
    payload = (
        await authed_client.get(f"/api/export/meeting/{meeting['id']}", params={"format": "json"})
    ).json()
    assert isinstance(payload["memories"], list)


@pytest.mark.asyncio
async def test_unicode_stays_readable_rather_than_escaped(authed_client):
    """A title with accents/CJK/emoji must not become backslash-u escapes."""
    BS = chr(92)
    note = await _note(authed_client, "Café 東京 · résumé 🚀", "Body with naïve accents.")
    md = (await authed_client.get(f"/api/export/note/{note['id']}", params={"format": "md"})).text
    assert "Café 東京 · résumé 🚀" in md and (BS + "u") not in md

    raw = (await authed_client.get(f"/api/export/note/{note['id']}", params={"format": "json"})).content
    assert "東京".encode("utf-8") in raw, "JSON should be UTF-8, not escaped"

    ws = (await authed_client.get("/api/export/workspace", params={"format": "json"})).content
    assert "東京".encode("utf-8") in ws
