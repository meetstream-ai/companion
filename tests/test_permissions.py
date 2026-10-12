"""
Per-workspace member permissions: what an owner lets members do.

Owners can always do everything. Members get the workspace's settings,
which default to add + edit but not delete / agents / export / invite.
"""
import uuid

import pytest

from app import permissions as perms
from tests.test_security import _approve, _client, _fresh_rate_limits, _pending_id, _signup  # noqa: F401


def _email(tag):
    return f"{tag}-{uuid.uuid4().hex[:6]}@example.com"


from contextlib import asynccontextmanager


@asynccontextmanager
async def _workspace_with_member():
    async with _client() as owner, _client() as member:
        await _signup(owner, _email("owner"), workspace="Perm Co")
        code = (await owner.get("/api/members/workspace")).json()["join_code"]
        await _signup(member, _email("member"), join_code=code, approve_by=owner)
        yield owner, member


def test_defaults_are_add_and_edit_only():
    assert perms.member_permissions(None) == {
        "create_content": True,
        "edit_content": True,
        "delete_content": False,
        "manage_agents": False,
        "export_workspace": False,
        "invite_members": False,
    }


@pytest.mark.asyncio
async def test_member_can_add_and_edit_but_not_delete_by_default():
    async with _workspace_with_member() as (owner, member):
        note = await member.post("/api/notebook/notes", json={"title": "mine", "content": "hello"})
        assert note.status_code == 201, note.text
        note_id = note.json()["id"]
        assert (await member.patch(f"/api/notebook/notes/{note_id}", json={"content": "edited"})).status_code == 200

        forbidden = await member.delete(f"/api/notebook/notes/{note_id}")
        assert forbidden.status_code == 403
        assert "Members of this workspace cannot delete content" in forbidden.json()["detail"]
        assert "Members page" in forbidden.json()["detail"]

        # Still there, and the owner can delete it.
        assert (await member.get(f"/api/notebook/notes/{note_id}")).status_code == 200
        assert (await owner.delete(f"/api/notebook/notes/{note_id}")).status_code == 200


@pytest.mark.asyncio
async def test_member_is_blocked_from_every_restricted_area_by_default():
    async with _workspace_with_member() as (owner, member):
        meeting = (await owner.post("/api/meetings", params={"deploy_bot": "false"}, json={
            "meeting_url": "https://meet.google.com/abc-defg-hij", "title": "t", "platform": "google_meet",
        })).json()
        assert (await member.delete(f"/api/meetings/{meeting['id']}")).status_code == 403
        assert (await member.get("/api/export/workspace")).status_code == 403
        assert (await member.get(f"/api/export/meeting/{meeting['id']}")).status_code == 403
        assert (await member.post("/api/agent/activate", json={"agent_config_id": "x"})).status_code == 403
        assert (await member.post("/api/agent", json={"agent_name": "x", "system_prompt": "x"})).status_code == 403

        ws = (await member.get("/api/members/workspace")).json()
        assert ws["join_code"] is None
        added = await member.post("/api/members", json={"name": "x", "email": _email("x"), "password": "correct-horse-battery"})
        assert added.status_code == 403
        assert ws["member_permissions"]["delete_content"] is False
        assert (await owner.get("/api/members/workspace")).json()["join_code"]


@pytest.mark.asyncio
async def test_owner_can_grant_and_revoke_and_it_takes_effect_immediately():
    async with _workspace_with_member() as (owner, member):
        note_id = (await member.post("/api/notebook/notes", json={"title": "n", "content": "c"})).json()["id"]

        granted = await owner.put("/api/members/workspace/permissions", json={"member_permissions": {"delete_content": True, "invite_members": True}})
        assert granted.status_code == 200, granted.text
        assert granted.json()["member_permissions"]["delete_content"] is True
        assert granted.json()["member_permissions"]["export_workspace"] is False  # untouched keys keep their value

        assert (await member.get("/api/members/workspace")).json()["join_code"]
        assert (await member.delete(f"/api/notebook/notes/{note_id}")).status_code == 200

        # The signed-in member's own view reflects it too.
        me = (await member.get("/api/auth/check")).json()["member"]
        assert me["permissions"]["delete_content"] is True and me["permissions"]["manage_agents"] is False

        revoked = await owner.put("/api/members/workspace/permissions", json={"member_permissions": {"create_content": False}})
        assert revoked.status_code == 200
        assert (await member.post("/api/notebook/notes", json={"title": "x", "content": "y"})).status_code == 403
        # Editing is a separate permission and is still allowed.
        assert (await member.get("/api/notebook/notes")).status_code == 200


@pytest.mark.asyncio
async def test_only_owners_change_permissions_and_owners_are_never_restricted():
    async with _workspace_with_member() as (owner, member):
        assert (await member.put("/api/members/workspace/permissions", json={"member_permissions": {"delete_content": True}})).status_code == 403
        assert (await owner.put("/api/members/workspace/permissions", json={"member_permissions": {"fly": True}})).status_code == 400

        # Turning everything off for members changes nothing for the owner.
        await owner.put("/api/members/workspace/permissions", json={"member_permissions": {k: False for k in perms.PERMISSION_KEYS}})
        me = (await owner.get("/api/auth/check")).json()["member"]
        assert all(me["permissions"].values())
        note = await owner.post("/api/notebook/notes", json={"title": "o", "content": "o"})
        assert note.status_code == 201
        assert (await owner.delete(f"/api/notebook/notes/{note.json()['id']}")).status_code == 200


@pytest.mark.asyncio
async def test_permissions_are_per_workspace():
    """A member of two workspaces is governed by whichever one is active."""
    owner_a, owner_b, person = _client(), _client(), _client()
    async with owner_a, owner_b, person:
        await _signup(owner_a, _email("a"), workspace="A")
        await _signup(owner_b, _email("b"), workspace="B")
        code_a = (await owner_a.get("/api/members/workspace")).json()["join_code"]
        code_b = (await owner_b.get("/api/members/workspace")).json()["join_code"]
        p_email = _email("p")
        await _signup(person, p_email, join_code=code_a, approve_by=owner_a)
        joined = await person.post("/api/members/workspaces/join", json={"join_code": code_b})
        assert joined.status_code == 200 and joined.json()["pending"] is True, joined.text
        await _approve(owner_b, await _pending_id(owner_b, p_email))

        await owner_b.put("/api/members/workspace/permissions", json={"member_permissions": {"delete_content": True}})

        # Switch to B: may delete there.
        ws = (await person.get("/api/members/workspaces")).json()["workspaces"]
        b_id = next(w["id"] for w in ws if w["name"] == "B")
        assert (await person.post(f"/api/members/workspaces/{b_id}/activate")).status_code == 200
        nb = (await person.post("/api/notebook/notes", json={"title": "b", "content": "b"})).json()
        assert (await person.delete(f"/api/notebook/notes/{nb['id']}")).status_code == 200

        # Switch back to A: defaults apply, no deleting.
        ws = (await person.get("/api/members/workspaces")).json()["workspaces"]
        a_id = next(w["id"] for w in ws if w["name"] == "A")
        assert (await person.post(f"/api/members/workspaces/{a_id}/activate")).status_code == 200
        na = (await person.post("/api/notebook/notes", json={"title": "a", "content": "a"})).json()
        assert (await person.delete(f"/api/notebook/notes/{na['id']}")).status_code == 403
