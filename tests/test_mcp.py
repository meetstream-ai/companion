"""
Unit and integration tests for MCP Protocol server and tool authorization.
"""
import pytest
import uuid
from app.config import settings
from app.mcp.tools import MCP_TOOL_DEFINITIONS


@pytest.mark.asyncio
async def test_mcp_unauthorized(client):
    # No Authorization header
    resp = await client.post("/mcp", json={"method": "initialize"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mcp_forbidden_token(client):
    # Invalid Bearer token
    headers = {"Authorization": "Bearer wrong_token_xyz"}
    resp = await client.post("/mcp", json={"method": "initialize"}, headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_mcp_initialize(client):
    headers = {"Authorization": f"Bearer {settings.MCP_AUTH_TOKEN}"}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    }
    resp = await client.post("/mcp", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 1
    assert "capabilities" in data["result"]
    assert "tools" in data["result"]["capabilities"]


@pytest.mark.asyncio
async def test_mcp_tools_list(client):
    headers = {"Authorization": f"Bearer {settings.MCP_AUTH_TOKEN}"}
    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    }
    resp = await client.post("/mcp", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    tools = data["result"]["tools"]
    tool_names = [t["name"] for t in tools]

    assert "search_meeting_memory" in tool_names
    assert "get_meeting" in tool_names
    assert "get_previous_meetings" in tool_names
    assert "get_action_items" in tool_names


@pytest.mark.asyncio
async def test_mcp_rest_tools_list(client):
    headers = {"Authorization": f"Bearer {settings.MCP_AUTH_TOKEN}"}
    resp = await client.get("/mcp/tools", headers=headers)
    assert resp.status_code == 200
    tools = resp.json()["tools"]
    assert len(tools) == len(MCP_TOOL_DEFINITIONS)
    tool_names = [t["name"] for t in tools]
    # Read tools
    assert "search_meeting_memory" in tool_names
    assert "get_meeting" in tool_names
    assert "get_previous_meetings" in tool_names
    assert "get_action_items" in tool_names
    # Write tools
    assert "add_meeting_memory" in tool_names
    assert "add_meeting_note" in tool_names
    assert "create_action_item" in tool_names
    assert "update_action_item" in tool_names


@pytest.mark.asyncio
async def test_owner_can_make_the_agent_read_only(authed_client, client):
    """Switching write tools off hides them from tools/list and refuses calls."""
    from tests.test_security import _client, _signup

    async with _client() as owner:
        await _signup(owner, f"w-{uuid.uuid4().hex[:6]}@example.com", workspace="Omega")
        assert (await owner.get("/api/agent/write-tools")).json()["enabled"] is True

        from app.database.connection import AsyncSessionLocal
        from app.models.database import Organization, User
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            token = (
                await session.execute(
                    select(Organization.mcp_token).join(User, User.organization_id == Organization.id).where(User.email.like("w-%"))
                )
            ).scalars().first()
        headers = {"Authorization": f"Bearer {token}"}

        listed = (await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=headers)).json()
        assert "create_action_item" in {t["name"] for t in listed["result"]["tools"]}

        assert (await owner.put("/api/agent/write-tools", json={"enabled": False})).status_code == 200

        listed = (await client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers)).json()
        names = {t["name"] for t in listed["result"]["tools"]}
        assert "create_action_item" not in names and "search_meeting_memory" in names

        call = (
            await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "add_meeting_note", "arguments": {"title": "x", "content": "y"}}},
                headers=headers,
            )
        ).json()
        assert call["result"]["isError"] is True and "switched off" in call["result"]["content"][0]["text"]


@pytest.mark.asyncio
async def test_members_cannot_change_write_tools():
    from tests.test_security import _client, _signup

    async with _client() as owner, _client() as member:
        await _signup(owner, f"o-{uuid.uuid4().hex[:6]}@example.com", workspace="Psi")
        code = (await owner.get("/api/members/workspace")).json()["join_code"]
        await _signup(member, f"m-{uuid.uuid4().hex[:6]}@example.com", join_code=code)
        assert (await member.put("/api/agent/write-tools", json={"enabled": False})).status_code == 403


@pytest.mark.asyncio
async def test_tool_arguments_are_validated_against_the_schema(client):
    """
    QA: a string `limit` reached min() and answered 500; an empty `query`
    returned five arbitrary memories; an unknown tool answered 200. Every
    call is now checked against the tool's declared inputSchema first.
    """
    headers = {"Authorization": f"Bearer {settings.MCP_AUTH_TOKEN}"}

    # REST surface: unknown tool 404, bad arguments 422.
    r = await client.post("/mcp/tools/no_such_tool", json={}, headers=headers)
    assert r.status_code == 404
    r = await client.post("/mcp/tools/search_meeting_memory", json={"query": 123, "limit": "lots"}, headers=headers)
    assert r.status_code == 422
    assert "'query' must be string" in r.json()["detail"] and "'limit' must be integer" in r.json()["detail"]
    r = await client.post("/mcp/tools/search_meeting_memory", json={"query": "   "}, headers=headers)
    assert r.status_code == 422 and "'query' is required" in r.json()["detail"]
    r = await client.post("/mcp/tools/search_meeting_memory", json={"query": "x", "limit": True}, headers=headers)
    assert r.status_code == 422  # booleans are not integers
    r = await client.post("/mcp/tools/search_meeting_memory", json={"query": "anything", "limit": 3}, headers=headers)
    assert r.status_code == 200 and "results" in r.json()

    # JSON-RPC surface: isError with the same sentence, never a Python message.
    def call(name, args):
        return client.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args},
        })
    r = await call("search_meeting_memory", {"query": 123, "limit": "lots"})
    body = r.json()["result"]
    assert r.status_code == 200 and body["isError"] is True
    assert "Invalid arguments" in body["content"][0]["text"] and "not supported between" not in body["content"][0]["text"]
    r = await call("no_such_tool", {})
    assert r.json()["result"]["isError"] is True and "Unknown tool" in r.json()["result"]["content"][0]["text"]
