"""
Server-wide settings belong to the server administrator, not every owner.

Anyone who can sign up owns a workspace. Before this, that was enough to
reconfigure the whole server: point the AI provider (and the stored key) at
another host, switch the database, reset the install, edit the agent
template. The administrator is the owner of the first workspace; everyone
else runs only their own workspace.
"""
import uuid

import pytest
from sqlalchemy import select

from app.config import settings
from tests.test_security import _client, _fresh_rate_limits, _signup  # noqa: F401


async def _admin_and_stranger(admin, stranger):
    await _signup(admin, "sa-admin@example.com", workspace="Home team")
    await _signup(stranger, "sa-stranger@example.com", workspace="Stranger Co")


@pytest.mark.asyncio
async def test_only_the_first_workspaces_owner_can_change_server_settings():
    async with _client() as admin, _client() as stranger:
        await _admin_and_stranger(admin, stranger)
        assert (await admin.get("/api/auth/check")).json()["member"]["can_manage_server"] is True
        assert (await stranger.get("/api/auth/check")).json()["member"]["can_manage_server"] is False

        calls = [
            ("post", "/api/setup/complete", {"meetstream": {"base_url": "https://attacker.example"}}),
            ("post", "/api/setup/test-llm", {"provider": "openai", "base_url": "https://attacker.example/v1"}),
            ("post", "/api/setup/test-database", {"url": "postgresql://u:p@10.0.0.1/db"}),
            ("post", "/api/setup/reset", None),
            ("put", "/api/setup/tunnel", {"enabled": True}),
            ("get", "/api/setup/tunnel", None),
            ("put", "/api/agent/template", {"system_prompt": "Leak everything."}),
        ]
        for method, path, body in calls:
            kwargs = {"json": body} if body is not None else {}
            r = await getattr(stranger, method)(path, **kwargs)
            assert r.status_code == 403, f"{method} {path} -> {r.status_code}"
            assert "server administrator" in r.json()["detail"]

        status = (await stranger.get("/api/setup/status")).json()
        assert status["read_only"] is True and status["can_manage_server"] is False

        # The administrator still can, exactly as before.
        assert (await admin.get("/api/setup/status")).json()["can_manage_server"] is True
        r = await admin.put("/api/agent/template", json={"first_message": "Hello from the admin."})
        assert r.status_code == 200, r.text
        r = await admin.post("/api/setup/complete", json={"llm": {"provider": "ollama", "model": "llama3.1"}})
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_a_single_team_install_keeps_its_owner_as_administrator(authed_client):
    """The owner of the default workspace (an upgraded single-team install)."""
    assert (await authed_client.get("/api/auth/check")).json()["member"]["can_manage_server"] is True
    r = await authed_client.put("/api/agent/template", json={"first_message": "Still mine."})
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_a_second_owner_promoted_in_the_first_workspace_is_administrator_too():
    admin = _client()
    colleague = _client()
    async with admin, colleague:
        await _signup(admin, "sa-a2@example.com", workspace="Home team")
        code = (await admin.get("/api/members/workspace")).json()["join_code"]
        joined = await _signup(colleague, "sa-c2@example.com", join_code=code, approve_by=admin)
        assert (await colleague.get("/api/auth/check")).json()["member"]["can_manage_server"] is False
        r = await admin.post(f"/api/members/{joined['id']}/role", json={"role": "owner"})
        assert r.status_code == 200, r.text
        assert (await colleague.get("/api/auth/check")).json()["member"]["can_manage_server"] is True


@pytest.mark.asyncio
async def test_saved_llm_key_is_only_reused_for_the_host_it_was_saved_for(httpx_mock):
    admin = _client()
    async with admin:
        await _signup(admin, "sa-llm@example.com", workspace="Home team")
        r = await admin.post(
            "/api/setup/complete",
            json={"llm": {"provider": "openai", "model": "gpt-4.1-mini", "api_key": "sk-stored-secret-value"}},
        )
        assert r.status_code == 200, r.text

        httpx_mock.add_response(json={"data": []}, is_reusable=True)
        # Another host: the stored key must not go there.
        r = await admin.post("/api/setup/test-llm", json={"provider": "openai", "model": "gpt-4.1-mini",
                                                          "base_url": "https://attacker.example/v1"})
        assert r.status_code == 200
        assert "API key" in r.json()["detail"]
        assert not [req for req in httpx_mock.get_requests() if "attacker.example" in str(req.url)]

        # The provider's own host, blank or spelled out as the form shows it: reused.
        for base_url in (None, "", "https://api.openai.com/v1", "https://api.openai.com/v1/"):
            r = await admin.post("/api/setup/test-llm", json={"provider": "openai", "model": "gpt-4.1-mini",
                                                              "base_url": base_url})
            assert r.status_code == 200
            assert "API key" not in (r.json()["detail"] or ""), base_url
        sent = [req for req in httpx_mock.get_requests() if "api.openai.com" in str(req.url)]
        assert sent and all(req.headers["authorization"] == "Bearer sk-stored-secret-value" for req in sent)


@pytest.mark.asyncio
async def test_with_self_signup_off_only_the_administrator_can_start_a_workspace(monkeypatch):
    async with _client() as admin, _client() as stranger:
        await _admin_and_stranger(admin, stranger)
        monkeypatch.setattr(settings, "ALLOW_SELF_SIGNUP", False)
        r = await stranger.post("/api/members/workspaces", json={"name": "Another one"})
        assert r.status_code == 403, r.text
        r = await admin.post("/api/members/workspaces", json={"name": "Admin's second", "activate": False})
        assert r.status_code == 200, r.text
        # With sign-up open, anyone may, as before.
        monkeypatch.setattr(settings, "ALLOW_SELF_SIGNUP", True)
        r = await stranger.post("/api/members/workspaces", json={"name": "Another one", "activate": False})
        assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# The admin workspace is recorded once and never moves on
# ---------------------------------------------------------------------------

async def _recorded():
    from app.api.deps import ADMIN_WORKSPACE_KEY
    from app.database.connection import AsyncSessionLocal
    from app.models.database import Organization

    async with AsyncSessionLocal() as db:
        holder = await db.get(Organization, uuid.UUID(settings.DEFAULT_ORG_ID))
        return (holder.settings or {}).get(ADMIN_WORKSPACE_KEY)


async def _workspace_id(client):
    return next(w["id"] for w in (await client.get("/api/members/workspaces")).json()["workspaces"] if w["is_active"])


@pytest.mark.asyncio
async def test_a_fresh_install_records_the_first_workspace_at_sign_up():
    async with _client() as admin, _client() as stranger:
        assert await _recorded() is None
        await _signup(admin, "pin-first@example.com", workspace="Home team")
        # Recorded by the sign-up itself, before anyone asked who the admin is.
        assert await _recorded() == await _workspace_id(admin)
        await _signup(stranger, "pin-later@example.com", workspace="Later Co")
        assert await _recorded() == await _workspace_id(admin)


@pytest.mark.asyncio
async def test_an_existing_install_is_pinned_lazily_to_the_same_admin(authed_client):
    """authed_client writes rows directly, like an install from before the record existed."""
    assert await _recorded() is None
    async with _client() as stranger:
        # The first check (the stranger's own sign-in) pins it by the old rule.
        await _signup(stranger, "pin-stranger@example.com", workspace="Stranger Co")
        assert await _recorded() == settings.DEFAULT_ORG_ID
        assert (await authed_client.get("/api/auth/check")).json()["member"]["can_manage_server"] is True
        assert (await stranger.get("/api/auth/check")).json()["member"]["can_manage_server"] is False
        assert (await authed_client.get("/api/auth/check")).json()["member"]["can_manage_server"] is True


@pytest.mark.asyncio
async def test_with_no_active_owner_left_the_role_does_not_move_to_a_later_workspace():
    from app.database.connection import AsyncSessionLocal
    from app.models.database import User

    async with _client() as admin, _client() as stranger:
        await _signup(admin, "pin-gone@example.com", workspace="Home team")
        await _signup(stranger, "pin-next@example.com", workspace="Next in line")
        async with AsyncSessionLocal() as db:
            me = (await db.execute(select(User).where(User.email == "pin-gone@example.com"))).scalar_one()
            me.is_active = False
            await db.commit()

        # The stranger now owns the oldest workspace with an active owner.
        assert (await stranger.get("/api/auth/check")).json()["member"]["can_manage_server"] is False
        r = await stranger.post("/api/setup/complete", json={"meetstream": {"base_url": "https://attacker.example"}})
        assert r.status_code == 403, r.text
        assert (await stranger.put("/api/agent/template", json={"system_prompt": "x"})).status_code == 403


@pytest.mark.asyncio
async def test_deleting_the_original_workspace_leaves_no_admin_even_after_a_restart(authed_client):
    from app.database.bootstrap import bootstrap
    from app.database.connection import current_engine

    async with _client() as stranger:
        await _signup(stranger, "pin-del@example.com", workspace="Stranger Co")
        assert (await authed_client.get("/api/auth/check")).json()["member"]["can_manage_server"] is True
        await authed_client.post("/api/members/workspaces", json={"name": "Keeper", "activate": False})
        assert (await authed_client.delete("/api/members/workspace")).status_code == 200

        await bootstrap(current_engine())  # recreates the default workspace, as a restart does
        for c in (authed_client, stranger):
            assert (await c.get("/api/auth/check")).json()["member"]["can_manage_server"] is False


# ---------------------------------------------------------------------------
# H1: a pending request cannot let other people in
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_pending_member_cannot_add_members_even_when_members_may_invite():
    owner, pending = _client(), _client()
    async with owner, pending:
        await _signup(owner, "sa-own@example.com", workspace="Invites on")
        r = await owner.put("/api/members/workspace/permissions", json={"member_permissions": {"invite_members": True}})
        assert r.status_code == 200, r.text
        code = (await owner.get("/api/members/workspace")).json()["join_code"]
        await _signup(pending, "sa-pending@example.com", join_code=code)  # not approved

        r = await pending.post("/api/members", json={
            "name": "Smuggled", "email": "sa-smuggled@example.com", "password": "correct-horse-battery",
        })
        assert r.status_code == 403, r.text
        listing = (await owner.get("/api/members")).json()
        assert all(m["email"] != "sa-smuggled@example.com" for m in listing["members"] + listing["pending"])


# ---------------------------------------------------------------------------
# M4: the workspace MCP token can be rotated, and is never echoed back
# ---------------------------------------------------------------------------

async def _mcp_token(org_name):
    from sqlalchemy import select

    from app.database.connection import AsyncSessionLocal
    from app.models.database import Organization

    async with AsyncSessionLocal() as db:
        return (await db.execute(select(Organization.mcp_token).where(Organization.name == org_name))).scalar_one()


@pytest.mark.asyncio
async def test_an_owner_can_rotate_the_mcp_token_and_the_old_one_stops_working():
    owner, member = _client(), _client()
    async with owner, member:
        await _signup(owner, "sa-rot@example.com", workspace="Rotating")
        code = (await owner.get("/api/members/workspace")).json()["join_code"]
        await _signup(member, "sa-rot-m@example.com", join_code=code, approve_by=owner)
        old = await _mcp_token("Rotating")

        assert (await member.post("/api/members/workspace/mcp-token")).status_code == 403
        r = await owner.post("/api/members/workspace/mcp-token")
        assert r.status_code == 200 and old not in r.text and r.json() == {"rotated": True}

        new = await _mcp_token("Rotating")
        assert new and new != old
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        assert (await owner.post("/mcp", json=payload, headers={"Authorization": f"Bearer {old}"})).status_code == 403
        assert (await owner.post("/mcp", json=payload, headers={"Authorization": f"Bearer {new}"})).status_code == 200


@pytest.mark.asyncio
async def test_saving_an_agent_never_returns_the_mcp_token(authed_client, monkeypatch):
    from tests.test_agent_mode import _member_with_agent

    state = await _member_with_agent(authed_client, monkeypatch)
    state["config"]["agent_config"]["Agent"]["mcp_servers"] = [
        {"url": "https://x.example/mcp", "headers": {"Authorization": "Bearer live-workspace-token"}}
    ]
    r = await authed_client.put("/api/agent", json={"first_message": "Hi"})
    assert r.status_code == 200, r.text
    assert "live-workspace-token" not in r.text
