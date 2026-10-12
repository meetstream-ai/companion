"""
Saved database connections: one person, several databases, one picker.

Someone with a workspace on their own database and their team's on another
has an account in each. The desktop app remembers each database and who
this machine is on it, lists every workspace across them, and switches
without a password prompt. Everything here needs the device key: on a
shared server these endpoints do not exist.
"""
import uuid

import httpx
import pytest

from app.database.connection import current_url, switch_database
from app.main import app
from app.middleware.auth_gate import DEVICE_COOKIE_NAME
from app.secrets import device_secret
from tests.test_security import _client, _fresh_rate_limits, _signup  # noqa: F401


def _desktop_client():
    """A client that presents this machine's device key, like the Electron shell."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
        cookies={DEVICE_COOKIE_NAME: device_secret()},
    )


@pytest.mark.asyncio
async def test_without_the_device_key_the_endpoints_do_not_exist(authed_client):
    assert (await authed_client.get("/api/connections")).status_code == 404
    assert (await authed_client.post("/api/connections", json={"url": "sqlite:///x.db"})).status_code == 404


@pytest.mark.asyncio
async def test_two_databases_one_picker(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    home_url = current_url()
    team_url = f"sqlite+aiosqlite:///{(tmp_path / 'team.db').as_posix()}"

    # The team's database already exists with its owner and a join code.
    await switch_database(team_url)
    async with _client() as owner:  # the owner is on another machine: no device key here
        await _signup(owner, "owner@team.example", workspace="Team Co")
        team_code = (await owner.get("/api/members/workspace")).json()["join_code"]
    await switch_database(home_url)

    async with _desktop_client() as me:
        # 1. My own workspace on my own database; signing in remembers me here.
        await _signup(me, "me@home.example", workspace="Mine")
        listing = (await me.get("/api/connections")).json()["connections"]
        assert len(listing) == 1 and listing[0]["active"] and listing[0]["signed_in"]
        assert [w["name"] for w in listing[0]["workspaces"]] == ["Mine"]
        home_id = listing[0]["id"]

        # 2. Add the team's database as a connection - saved, not switched to.
        r = await me.post("/api/connections", json={"label": "Team", "url": team_url})
        assert r.status_code == 200, r.text
        team_id = r.json()["id"]
        assert r.json()["signed_in"] is False and r.json()["workspaces"] == []
        assert current_url() == home_url
        r = await me.post("/api/connections", json={"url": "postgresql://u:p@nohost.invalid/db"})
        assert r.status_code == 400  # must connect to be saved

        # 3. Switch to it: no account there yet, so sign-in is required.
        r = await me.post(f"/api/connections/{team_id}/activate", json={})
        assert r.status_code == 200 and r.json() == {"switched": True, "signed_in": False}
        assert current_url() == team_url
        assert (await me.get("/api/auth/check")).json() == {"authenticated": False}

        # Join the team there with the code; the sign-in is remembered for this connection.
        r = await me.post("/api/members", json={"name": "Me", "email": "me@home.example", "password": "correct-horse-battery", "join_code": team_code})
        assert r.status_code == 200, r.text
        # The team's owner, from their own machine, lets me in.
        async with _client() as owner:
            assert (await owner.post("/api/auth/login", json={"email": "owner@team.example", "password": "correct-horse-battery"})).status_code == 200
            assert (await owner.post(f"/api/members/{r.json()['id']}/approve")).status_code == 200
        assert (await me.post("/api/auth/login", json={"email": "me@home.example", "password": "correct-horse-battery"})).status_code == 200

        # 4. The picker now shows both databases and my workspaces on each.
        listing = {c["label"]: c for c in (await me.get("/api/connections")).json()["connections"]}
        assert listing["Team"]["active"] and listing["Team"]["signed_in"]
        assert [w["name"] for w in listing["Team"]["workspaces"]] == ["Team Co"]
        assert listing["Team"]["workspaces"][0]["role"] == "member"
        home_label = next(k for k in listing if k != "Team")
        assert listing[home_label]["active"] is False and listing[home_label]["signed_in"]
        assert [w["name"] for w in listing[home_label]["workspaces"]] == ["Mine"]

        # 5. Switch back home: signed in without a password, in my own workspace.
        mine_id = listing[home_label]["workspaces"][0]["id"]
        r = await me.post(f"/api/connections/{home_id}/activate", json={"organization_id": mine_id})
        assert r.json() == {"switched": True, "signed_in": True}
        check = (await me.get("/api/auth/check")).json()
        assert check["authenticated"] and check["member"]["email"] == "me@home.example" and check["member"]["role"] == "owner"
        assert (await me.get("/api/members/workspace")).json()["name"] == "Mine"

        # 6. And to the team again - also without a password.
        r = await me.post(f"/api/connections/{team_id}/activate", json={})
        assert r.json()["signed_in"] is True
        assert (await me.get("/api/auth/check")).json()["member"]["role"] == "member"
        assert (await me.get("/api/members/workspace")).json()["name"] == "Team Co"

        # The live connection cannot be removed; another can.
        assert (await me.delete(f"/api/connections/{team_id}")).status_code == 400
        await me.post(f"/api/connections/{home_id}/activate", json={})
        assert (await me.delete(f"/api/connections/{team_id}")).json() == {"removed": True}
        assert [c["label"] for c in (await me.get("/api/connections")).json()["connections"]] == [home_label]

    await switch_database(home_url)


@pytest.mark.asyncio
async def test_an_unreachable_saved_connection_does_not_break_the_picker(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from dataclasses import replace

    from app.runtime_config import ConnectionSettings, load_config, save_config

    async with _desktop_client() as me:
        await _signup(me, "solo@home.example", workspace="Solo")
        gone = tmp_path / "gone.db"
        config = load_config()
        save_config(replace(config, connections=[*config.connections, ConnectionSettings(
            id="dead", label="Old laptop", url=f"sqlite+aiosqlite:///{gone.as_posix()}", user_id=str(uuid.uuid4()),
        )]))
        listing = {c["label"]: c for c in (await me.get("/api/connections")).json()["connections"]}
        assert listing["Old laptop"]["workspaces"] == [] and listing["Old laptop"]["signed_in"] in (True, False)
        assert any(c["active"] for c in listing.values())


# ---------------------------------------------------------------------------
# Checking a join code against a database before switching to it


@pytest.mark.asyncio
async def test_check_join_answers_without_switching_or_saving(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    home_url = current_url()
    team_url = f"sqlite+aiosqlite:///{(tmp_path / 'team.db').as_posix()}"

    await switch_database(team_url)
    async with _client() as owner:
        await _signup(owner, "owner@team.example", workspace="Team Co")
        team_code = (await owner.get("/api/members/workspace")).json()["join_code"]
    await switch_database(home_url)

    async with _desktop_client() as me:
        await _signup(me, "me@home.example", workspace="Mine")
        saved_before = len((await me.get("/api/connections")).json()["connections"])

        # Right code on the right database: named, and nothing moved.
        r = await me.post("/api/connections/check-join", json={"url": team_url, "join_code": team_code})
        assert r.status_code == 200, r.text
        assert r.json() == {"workspace": "Team Co", "same_database": False}
        assert current_url() == home_url
        assert len((await me.get("/api/connections")).json()["connections"]) == saved_before

        # Right code, wrong database (it lives on the team's, not mine).
        r = await me.post("/api/connections/check-join", json={"join_code": team_code})
        assert r.status_code == 404 and "not on" not in r.text and "that database" in r.json()["detail"]
        # Wrong code on the right database.
        r = await me.post("/api/connections/check-join", json={"url": team_url, "join_code": "nope1234"})
        assert r.status_code == 404
        # My own workspace's code, no database given: means the one I am on.
        my_code = (await me.get("/api/members/workspace")).json()["join_code"]
        r = await me.post("/api/connections/check-join", json={"join_code": my_code})
        assert r.status_code == 200 and r.json() == {"workspace": "Mine", "same_database": True}

        # A database that cannot be reached is a 400 with a readable reason.
        r = await me.post("/api/connections/check-join", json={"url": "postgresql://u:p@nohost.invalid/db", "join_code": team_code})
        assert r.status_code == 400 and "Could not connect" in r.json()["detail"]
        assert (await me.post("/api/connections/check-join", json={"url": team_url, "join_code": "  "})).status_code == 400
        assert current_url() == home_url


@pytest.mark.asyncio
async def test_check_join_is_for_the_desktop_or_a_fresh_install(authed_client):
    # Accounts exist and there is no device key: the endpoint does not exist.
    assert (await authed_client.post("/api/connections/check-join", json={"join_code": "x"})).status_code == 404


@pytest.mark.asyncio
async def test_check_join_is_open_during_first_run_setup(client):
    """The wizard's Join path needs it before any account or device exists."""
    # A 400 (unreachable database) proves the gate let the request through; a
    # gated call would be a 404 like any other unknown endpoint.
    r = await client.post("/api/connections/check-join", json={"url": "postgresql://u:p@nohost.invalid/db", "join_code": "abc"})
    assert r.status_code == 400, r.text

@pytest.mark.asyncio
async def test_connections_need_the_device_key_not_a_session(client):
    """Signed out, no device key: 404. The key alone, no session: works."""
    async with _client() as owner:
        await _signup(owner, "gate-owner@example.com", workspace="Gate Co")
    assert (await client.get("/api/connections")).status_code == 404
    async with _desktop_client() as me:
        assert (await me.get("/api/connections")).status_code == 200
