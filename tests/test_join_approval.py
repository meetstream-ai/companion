"""
Joining a workspace is a request an owner approves.

A join code is meant to be passed around, so on its own it must not open the
door. These cover the whole life of a request: what a pending person can and
cannot do, what the owner sees, and what approving or declining changes.
"""
import pytest

from tests.test_security import _approve, _client, _fresh_rate_limits, _pending_id, _signup  # noqa: F401


async def _owner_with_code(client, email, workspace):
    await _signup(client, email, workspace=workspace)
    return (await client.get("/api/members/workspace")).json()["join_code"]


@pytest.mark.asyncio
async def test_signing_up_with_a_code_waits_for_the_owner():
    async with _client() as owner, _client() as newcomer, _client() as member:
        code = await _owner_with_code(owner, "ap-owner@example.com", "Gated")
        await owner.post("/api/notebook/notes", json={"title": "ORANGE-secret"})
        await _signup(member, "ap-member@example.com", join_code=code, approve_by=owner)

        r = await newcomer.post("/api/members", json={
            "name": "New", "email": "ap-new@example.com", "password": "correct-horse-battery", "join_code": code,
        })
        assert r.status_code == 200 and r.json()["status"] == "pending", r.text
        login = await newcomer.post("/api/auth/login", json={"email": "ap-new@example.com", "password": "correct-horse-battery"})
        assert login.status_code == 200

        # Signed in, but told to wait - and every workspace door is shut.
        check = (await newcomer.get("/api/auth/check")).json()
        assert check["authenticated"] is True
        assert check["member"]["pending_approval"] == {"workspace": "Gated"}
        for path in ("/api/notebook/notes", "/api/members", "/api/members/workspace", "/api/meetings"):
            r = await newcomer.get(path)
            assert r.status_code == 403, f"{path} -> {r.status_code}"
            assert "ORANGE" not in r.text
        assert (await newcomer.post("/api/notebook/notes", json={"title": "sneak"})).status_code == 403

        # The owner sees the request; a member does not; neither lists them as in.
        listing = (await owner.get("/api/members")).json()
        assert [m["email"] for m in listing["pending"]] == ["ap-new@example.com"]
        assert listing["pending"][0]["status"] == "pending" and listing["pending"][0]["requested_at"]
        assert "ap-new@example.com" not in {m["email"] for m in listing["members"]}
        member_view = (await member.get("/api/members")).json()
        assert member_view["pending"] == []
        assert "ap-new@example.com" not in {m["email"] for m in member_view["members"]}

        # Approve: in, as a member, with the workspace open.
        await _approve(owner, listing["pending"][0]["id"])
        check = (await newcomer.get("/api/auth/check")).json()
        assert check["member"]["pending_approval"] is None and check["member"]["role"] == "member"
        titles = [n["title"] for n in (await newcomer.get("/api/notebook/notes")).json()["notes"]]
        assert "ORANGE-secret" in titles
        listing = (await owner.get("/api/members")).json()
        assert listing["pending"] == []
        assert "ap-new@example.com" in {m["email"] for m in listing["members"]}


@pytest.mark.asyncio
async def test_declining_a_signup_request_frees_the_email():
    async with _client() as owner, _client() as newcomer:
        code = await _owner_with_code(owner, "dc-owner@example.com", "Picky")
        await _signup(newcomer, "dc-new@example.com", join_code=code)
        pending = await _pending_id(owner, "dc-new@example.com")

        r = await owner.delete(f"/api/members/{pending}")
        assert r.status_code == 200 and r.json()["account_deleted"] is True
        assert (await newcomer.get("/api/auth/check")).json() == {"authenticated": False}
        assert (await owner.get("/api/members")).json()["pending"] == []
        # They can try again - with the right code this time.
        r = await newcomer.post("/api/members", json={
            "name": "New", "email": "dc-new@example.com", "password": "correct-horse-battery", "join_code": code,
        })
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_declining_an_in_app_request_keeps_the_rest_of_the_account():
    async with _client() as owner_a, _client() as owner_b, _client() as person:
        await _owner_with_code(owner_a, "kp-a@example.com", "Alpha")
        code_b = await _owner_with_code(owner_b, "kp-b@example.com", "Beta")
        await _signup(person, "kp-p@example.com", workspace="Mine")
        assert (await person.post("/api/members/workspaces/join", json={"join_code": code_b})).status_code == 200

        pending = await _pending_id(owner_b, "kp-p@example.com")
        r = await owner_b.delete(f"/api/members/{pending}")
        assert r.status_code == 200 and r.json()["account_deleted"] is False
        assert [w["name"] for w in (await person.get("/api/members/workspaces")).json()["workspaces"]] == ["Mine"]
        assert (await person.get("/api/notebook/notes")).status_code == 200


@pytest.mark.asyncio
async def test_only_an_owner_can_approve_and_only_a_pending_request():
    async with _client() as owner, _client() as member, _client() as newcomer:
        code = await _owner_with_code(owner, "oo-owner@example.com", "Strict")
        await _signup(member, "oo-member@example.com", join_code=code, approve_by=owner)
        await _signup(newcomer, "oo-new@example.com", join_code=code)
        pending = await _pending_id(owner, "oo-new@example.com")

        assert (await member.post(f"/api/members/{pending}/approve")).status_code == 403
        assert (await newcomer.post(f"/api/members/{pending}/approve")).status_code == 403
        assert (await newcomer.get("/api/auth/check")).json()["member"]["pending_approval"]["workspace"] == "Strict"

        # Role changes and password resets do not reach someone not yet in.
        assert (await owner.post(f"/api/members/{pending}/role", json={"role": "owner"})).status_code == 404
        assert (await owner.post(f"/api/members/{pending}/reset-password", json={"new_password": "x" * 12})).status_code == 404

        await _approve(owner, pending)
        assert (await owner.post(f"/api/members/{pending}/approve")).status_code == 404  # nothing left to approve


@pytest.mark.asyncio
async def test_pending_people_do_not_count_and_are_not_a_way_in_elsewhere():
    """A request is not membership: guards ignore it, and it grants nothing anywhere."""
    async with _client() as owner, _client() as asker:
        code = await _owner_with_code(owner, "ct-owner@example.com", "Solo")
        await _signup(asker, "ct-asker@example.com", join_code=code)
        me = (await owner.get("/api/auth/check")).json()["member"]
        # Still the only member: cannot remove or demote self.
        assert (await owner.delete(f"/api/members/{me['id']}")).status_code == 400
        assert (await owner.post(f"/api/members/{me['id']}/role", json={"role": "member"})).status_code == 400
        # And the workspace can still be deleted - a request never blocks that.
        await owner.post("/api/members/workspaces", json={"name": "Elsewhere", "activate": False})
        r = await owner.delete("/api/members/workspace")
        assert r.status_code == 200, r.text
        # The account created only to ask went with it.
        assert (await asker.get("/api/auth/check")).json() == {"authenticated": False}


@pytest.mark.asyncio
async def test_someone_waiting_can_still_start_their_own_workspace():
    """Pending is a state to get out of, not a trap: creating your own works."""
    async with _client() as owner, _client() as asker:
        code = await _owner_with_code(owner, "wo-owner@example.com", "Elsewhere")
        await _signup(asker, "wo-asker@example.com", join_code=code)
        assert (await asker.get("/api/notebook/notes")).status_code == 403
        r = await asker.post("/api/members/workspaces", json={"name": "My own"})
        assert r.status_code == 200, r.text
        check = (await asker.get("/api/auth/check")).json()["member"]
        assert check["pending_approval"] is None and check["role"] == "owner"
        assert (await asker.get("/api/notebook/notes")).status_code == 200
        ws = (await asker.get("/api/members/workspaces")).json()["workspaces"]
        assert {(w["name"], w["status"]) for w in ws} == {("My own", "active"), ("Elsewhere", "pending")}
