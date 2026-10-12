"""
Security tests that go through HTTP, the way an attacker would.

Covers the trust boundaries described in SECURITY.md: workspace isolation,
owner-only configuration, the session cookie's signing key, rate limits,
generated MCP tokens and webhook signature enforcement.
"""
import time
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.database.connection import AsyncSessionLocal
from app.main import app
from app.middleware.auth_gate import COOKIE_NAME, SESSION_TTL_SECONDS, sign_session
from app.middleware.limits import rate_limiter
from app.models.database import Organization, User
from app.models.schemas import ActionItemUpdate


async def _signup(client, email, *, workspace=None, join_code=None, approve_by=None):
    """
    Create an account and sign it in. A join by code is only a *request*;
    pass the owner's client as approve_by to have them let the person in,
    which is what every "member of the workspace" scenario wants.
    """
    body = {"name": email.split("@")[0], "email": email, "password": "correct-horse-battery"}
    if workspace:
        body["workspace_name"] = workspace
    if join_code:
        body["join_code"] = join_code
    resp = await client.post("/api/members", json=body)
    assert resp.status_code == 200, resp.text
    if approve_by is not None:
        await _approve(approve_by, resp.json()["id"])
    login = await client.post("/api/auth/login", json={"email": email, "password": "correct-horse-battery"})
    assert login.status_code == 200, login.text
    return resp.json()


async def _approve(owner_client, member_id):
    r = await owner_client.post(f"/api/members/{member_id}/approve")
    assert r.status_code == 200, r.text
    return r.json()


async def _pending_id(owner_client, email):
    """The id of the person with this email waiting to join the owner's workspace."""
    listing = (await owner_client.get("/api/members")).json()
    return next(m["id"] for m in listing["pending"] if m["email"] == email)


def _client(cookies=None):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", cookies=cookies or {})


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    rate_limiter.reset()
    yield
    rate_limiter.reset()


# ---------------------------------------------------------------------------
# Workspace isolation over HTTP
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_other_workspace_cannot_read_or_change_my_data():
    async with _client() as a, _client() as b:
        await _signup(a, f"a-{uuid.uuid4().hex[:6]}@example.com", workspace="Alpha")
        await _signup(b, f"b-{uuid.uuid4().hex[:6]}@example.com", workspace="Beta")

        note = (await a.post("/api/notebook/notes", json={"title": "Alpha secret", "content": "- [ ] ship it"})).json()
        folder = (await a.post("/api/notebook/folders", json={"name": "Alpha folder"})).json()
        upload = await a.post(
            "/api/meetings/upload",
            json={"title": "Alpha call", "transcript": "Sam: I will send the SOC2 report tomorrow."},
        )
        assert upload.status_code == 202
        meeting = upload.json()
        assert meeting["processing_status"] == "queued_for_processing"
        from app.services.processing import processing_pipeline

        await processing_pipeline.wait_for(uuid.UUID(meeting["id"]))
        assert (await a.get(f"/api/meetings/{meeting['id']}")).json()["processing_status"] == "completed"
        items = (await a.get("/api/action-items")).json()
        item_id = items["action_items"][0]["id"]

        assert (await b.get(f"/api/notebook/notes/{note['id']}")).status_code == 404
        assert (await b.patch(f"/api/notebook/notes/{note['id']}", json={"title": "pwned"})).status_code == 404
        assert (await b.delete(f"/api/notebook/notes/{note['id']}")).status_code == 404
        assert (await b.patch(f"/api/notebook/folders/{folder['id']}", json={"name": "pwned"})).status_code == 404
        assert (await b.get(f"/api/meetings/{meeting['id']}")).status_code == 404
        assert (await b.get(f"/api/meetings/{meeting['id']}/transcript")).status_code == 404
        assert (await b.delete(f"/api/meetings/{meeting['id']}")).status_code == 404
        assert (await b.patch(f"/api/action-items/{item_id}", json={"status": "completed"})).status_code == 404

        listing = (await b.get("/api/notebook/notes")).json()
        titles = [n["title"] for n in (listing["notes"] if isinstance(listing, dict) else listing)]
        assert "Alpha secret" not in titles
        assert (await b.post("/api/search/memory", json={"query": "SOC2"})).json()["total_results"] == 0

        # Still intact for its owner.
        assert (await a.get(f"/api/notebook/notes/{note['id']}")).json()["title"] == "Alpha secret"


@pytest.mark.asyncio
async def test_members_of_other_workspaces_are_invisible():
    async with _client() as a, _client() as b:
        await _signup(a, f"a-{uuid.uuid4().hex[:6]}@example.com", workspace="Alpha")
        b_user = await _signup(b, f"b-{uuid.uuid4().hex[:6]}@example.com", workspace="Beta")
        emails = [m["email"] for m in (await a.get("/api/members")).json()["members"]]
        assert b_user["email"] not in emails
        assert (await a.delete(f"/api/members/{b_user['id']}")).status_code == 404
        assert (await a.post(f"/api/members/{b_user['id']}/reset-password", json={"new_password": "hijacked-pw"})).status_code == 404


# ---------------------------------------------------------------------------
# Roles: owners vs members
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workspace_creator_is_owner_and_joiner_is_member():
    async with _client() as a, _client() as b:
        owner = await _signup(a, f"o-{uuid.uuid4().hex[:6]}@example.com", workspace="Gamma")
        assert owner["role"] == "owner"
        code = (await a.get("/api/members/workspace")).json()["join_code"]
        member = await _signup(b, f"m-{uuid.uuid4().hex[:6]}@example.com", join_code=code, approve_by=a)
        assert member["role"] == "member"
        assert (await b.get("/api/auth/check")).json()["member"]["role"] == "member"


@pytest.mark.asyncio
async def test_member_cannot_change_server_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("MEET_COMPANION_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    from app import runtime_config

    runtime_config.load_config(refresh=True)
    runtime_config.update_config(onboarding_completed=True)

    async with _client() as a, _client() as b:
        await _signup(a, f"o-{uuid.uuid4().hex[:6]}@example.com", workspace="Delta")
        code = (await a.get("/api/members/workspace")).json()["join_code"]
        await _signup(b, f"m-{uuid.uuid4().hex[:6]}@example.com", join_code=code, approve_by=a)

        for path, body in (
            ("/api/setup/complete", {"llm": {"provider": "ollama", "model": "llama3.1"}}),
            ("/api/setup/reset", None),
            ("/api/setup/test-database", {"url": "sqlite+aiosqlite:///data/x.db"}),
            ("/api/setup/test-llm", {"provider": "ollama", "model": "llama3.1"}),
        ):
            resp = await b.post(path, json=body)
            assert resp.status_code == 403, (path, resp.text)
        assert (await b.put("/api/agent/template", json={"first_message": "hi"})).status_code == 403

        status = (await b.get("/api/setup/status")).json()
        assert status["read_only"] is True
        assert "api_key" not in status["llm"]
        assert "url" not in status["database"]

        # The owner still can, and gets the full view.
        assert (await a.post("/api/setup/test-llm", json={"provider": "ollama", "model": "llama3.1"})).status_code == 200
        assert "read_only" not in (await a.get("/api/setup/status")).json()

    runtime_config.load_config(refresh=True)


@pytest.mark.asyncio
async def test_setup_is_not_open_just_because_config_is_missing(tmp_path, monkeypatch):
    """
    "Not configured" used to mean "first run, no auth needed" - even with
    accounts in the database. Delete config.json (or move the data dir) and
    anyone on the network could repoint the AI provider at their own
    endpoint, or reset the install. First-run openness needs both: no saved
    configuration AND no account yet.
    """
    monkeypatch.setenv("MEET_COMPANION_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    from app import runtime_config

    runtime_config.load_config(refresh=True)
    assert runtime_config.is_configured() is False

    async with _client() as owner, _client() as anon:
        # A brand-new install: setup is open.
        assert (await anon.get("/api/setup/providers")).status_code == 200
        assert (await anon.get("/api/setup/status")).json()["needs_setup"] is True

        await _signup(owner, f"o-{uuid.uuid4().hex[:6]}@example.com", workspace="Epsilon")

        # Still unconfigured, but an account exists: locked down.
        assert (await anon.post("/api/setup/reset")).status_code == 401
        assert (await anon.post("/api/setup/complete", json={"llm": {"provider": "openai_compatible", "base_url": "https://evil.example.com/v1", "api_key": "x"}})).status_code == 401
        assert (await anon.get("/api/setup/providers")).status_code == 401
        status = (await anon.get("/api/setup/status")).json()
        assert status == {"onboarding_completed": False, "needs_setup": False, "has_members": True}
        assert runtime_config.load_config(refresh=True).llm.provider != "openai_compatible"

        # The owner configures it from Settings.
        assert (await owner.post("/api/setup/complete", json={"llm": {"provider": "ollama", "model": "llama3.1"}})).status_code == 200
    runtime_config.load_config(refresh=True)


@pytest.mark.asyncio
async def test_setup_requires_sign_in_once_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("MEET_COMPANION_CONFIG", str(tmp_path / "config.json"))
    from app import runtime_config

    runtime_config.load_config(refresh=True)
    runtime_config.update_config(onboarding_completed=True)
    async with _client() as anon:
        assert (await anon.post("/api/setup/reset")).status_code == 401
        assert (await anon.post("/api/setup/complete", json={})).status_code == 401
    runtime_config.load_config(refresh=True)


@pytest.mark.asyncio
async def test_member_can_only_remove_self_and_last_owner_is_protected():
    async with _client() as a, _client() as b:
        owner = await _signup(a, f"o-{uuid.uuid4().hex[:6]}@example.com", workspace="Epsilon")
        code = (await a.get("/api/members/workspace")).json()["join_code"]
        member = await _signup(b, f"m-{uuid.uuid4().hex[:6]}@example.com", join_code=code, approve_by=a)

        assert (await b.delete(f"/api/members/{owner['id']}")).status_code == 403
        assert (await b.post(f"/api/members/{owner['id']}/role", json={"role": "member"})).status_code == 403
        assert (await a.post(f"/api/members/{owner['id']}/role", json={"role": "member"})).status_code == 400

        promoted = await a.post(f"/api/members/{member['id']}/role", json={"role": "owner"})
        assert promoted.json()["role"] == "owner"
        assert (await a.post(f"/api/members/{owner['id']}/role", json={"role": "member"})).status_code == 200


# ---------------------------------------------------------------------------
# Sessions and secrets
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cookie_signed_with_a_different_key_is_rejected():
    async with _client() as a:
        me = await _signup(a, f"s-{uuid.uuid4().hex[:6]}@example.com", workspace="Zeta")
    import hashlib
    import hmac

    expires = int(time.time()) + SESSION_TTL_SECONDS
    payload = f"{expires}.{me['id']}"
    forged = payload + "." + hmac.new(b"meet_companion_secure_salt_2026", payload.encode(), hashlib.sha256).hexdigest()
    async with _client({COOKIE_NAME: forged}) as forger:
        assert (await forger.get("/api/notebook/notes")).status_code == 401
    genuine = sign_session(me["id"], expires)
    async with _client({COOKIE_NAME: genuine}) as real:
        assert (await real.get("/api/notebook/notes")).status_code == 200


def test_placeholder_secrets_are_never_accepted(monkeypatch, tmp_path):
    from app import secrets as app_secrets

    monkeypatch.setenv("MEET_COMPANION_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("SESSION_SECRET", "change-me-to-a-random-string")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "dev-mcp-token-meetstream-2026")
    for name in ("SESSION_SECRET", "API_KEY_SALT", "MCP_AUTH_TOKEN"):
        monkeypatch.setattr(settings, name, "change-me")  # a placeholder in .env too
    app_secrets.reset_for_tests()
    try:
        generated = app_secrets.session_secret()
        assert generated != "change-me-to-a-random-string"
        assert len(generated) >= 32
        assert (tmp_path / "session.key").read_text().strip() == generated
        assert app_secrets.configured_mcp_token() is None
    finally:
        app_secrets.reset_for_tests()


@pytest.mark.asyncio
async def test_new_workspaces_get_unique_random_mcp_tokens():
    async with _client() as a, _client() as b:
        await _signup(a, f"t-{uuid.uuid4().hex[:6]}@example.com", workspace="Theta")
        await _signup(b, f"t-{uuid.uuid4().hex[:6]}@example.com", workspace="Iota")
    async with AsyncSessionLocal() as session:
        tokens = [row[0] for row in (await session.execute(select(Organization.mcp_token))).all()]
    assert len(tokens) == len(set(tokens))
    assert all(t and len(t) >= 32 for t in tokens)
    assert "dev-mcp-token-meetstream-2026" not in tokens


# ---------------------------------------------------------------------------
# Rate limiting and webhooks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_is_rate_limited():
    async with _client() as c:
        codes = []
        for _ in range(12):
            resp = await c.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong"})
            codes.append(resp.status_code)
    assert codes[:10] == [401] * 10
    assert codes[10:] == [429, 429]


@pytest.mark.asyncio
async def test_unsigned_webhook_for_unknown_bot_is_ignored(monkeypatch):
    monkeypatch.delenv("MEETSTREAM_WEBHOOK_SECRET", raising=False)
    async with _client() as c:
        resp = await c.post("/api/webhooks/meetstream", json={"bot_id": "never-launched", "event": "bot.failed"})
    assert resp.status_code == 200
    assert resp.json()["reason"] == "unknown_bot"


@pytest.mark.asyncio
async def test_webhook_with_wrong_signature_is_rejected(monkeypatch):
    monkeypatch.setenv("MEETSTREAM_WEBHOOK_SECRET", "a-real-webhook-secret-value")
    async with _client() as c:
        resp = await c.post(
            "/api/webhooks/meetstream",
            content=b'{"bot_id": "x", "event": "bot.failed"}',
            headers={"Content-Type": "application/json", "X-Meetstream-Signature": "sha256=deadbeef"},
        )
    assert resp.status_code == 401


def test_action_item_update_schema_validation():
    update_valid = ActionItemUpdate(status="completed", notes="Sent by Sarah")
    assert update_valid.status == "completed"
    assert update_valid.notes == "Sent by Sarah"


# ---------------------------------------------------------------------------
# Cookie flags, proxy trust, .env secrets, API docs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cookie_is_usable_over_plain_http_and_strict_over_https():
    email = f"c-{uuid.uuid4().hex[:6]}@example.com"
    async with _client() as c:
        await _signup(c, email, workspace="Kappa")
    creds = {"email": email, "password": "correct-horse-battery"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://lan-box:8000") as http:
        header = (await http.post("/api/auth/login", json=creds)).headers["set-cookie"].lower()
        assert "secure" not in header and "samesite=lax" in header
        # The jar keeps a non-Secure cookie over http, so the session just works.
        assert (await http.get("/api/auth/check")).json()["authenticated"] is True
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://hosted.example") as https:
        header = (await https.post("/api/auth/login", json=creds)).headers["set-cookie"].lower()
        assert "secure" in header and "samesite=none" in header


@pytest.mark.asyncio
async def test_forwarded_for_is_ignored_unless_proxy_is_trusted(monkeypatch):
    async def attempts(n):
        codes = []
        async with _client() as c:
            for i in range(n):
                resp = await c.post(
                    "/api/auth/login",
                    json={"email": "nobody@example.com", "password": "wrong"},
                    headers={"X-Forwarded-For": f"10.0.0.{i}"},
                )
                codes.append(resp.status_code)
        return codes

    monkeypatch.setattr(settings, "TRUST_PROXY", False)
    assert (await attempts(12))[-1] == 429  # spoofed addresses do not reset the bucket
    rate_limiter.reset()
    monkeypatch.setattr(settings, "TRUST_PROXY", True)
    assert 429 not in await attempts(12)  # behind a real proxy each address is its own client


def test_dotenv_session_secret_is_honoured(monkeypatch, tmp_path):
    from app import secrets as app_secrets

    monkeypatch.setenv("MEET_COMPANION_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.delenv("API_KEY_SALT", raising=False)
    # What pydantic would have read from a .env file:
    monkeypatch.setattr(settings, "SESSION_SECRET", "from-the-dotenv-file-0123456789abcdef")
    app_secrets.reset_for_tests()
    try:
        assert app_secrets.session_secret() == "from-the-dotenv-file-0123456789abcdef"
        assert not (tmp_path / "session.key").exists()
    finally:
        app_secrets.reset_for_tests()


def test_api_docs_are_off_outside_development(monkeypatch):
    import importlib

    from app import main as main_module

    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "API_DOCS", None)
    reloaded = importlib.reload(main_module)
    try:
        assert reloaded.app.docs_url is None and reloaded.app.openapi_url is None
    finally:
        monkeypatch.setattr(settings, "APP_ENV", "development")
        importlib.reload(main_module)


@pytest.mark.asyncio
async def test_duplicate_email_is_refused_by_the_database_not_just_the_api():
    from sqlalchemy.exc import IntegrityError

    email = f"dup-{uuid.uuid4().hex[:6]}@example.com"
    async with _client() as a:
        await _signup(a, email, workspace="Lambda")
    async with AsyncSessionLocal() as session:
        org_id = (await session.execute(select(User.organization_id).where(User.email == email))).scalar_one()
        session.add(User(organization_id=org_id, email=email, name="Twin", is_active=True, settings={}))
        with pytest.raises(IntegrityError):
            await session.commit()


# ---------------------------------------------------------------------------
# QA round: password pre-hash, per-email rate limit, cross-org note references
# ---------------------------------------------------------------------------

def test_long_passwords_are_not_truncated_and_legacy_hashes_still_verify():
    import bcrypt as _bcrypt

    from app.security import hash_password, needs_rehash, verify_password

    long_pw = "p" * 200
    h = hash_password(long_pw)
    assert verify_password(long_pw, h)
    assert not verify_password("p" * 72 + "WRONG", h), "bcrypt's 72-byte limit must not leak through"
    assert not needs_rehash(h)
    # A hash written by the old code (plain bcrypt over the first 72 bytes).
    legacy = _bcrypt.hashpw(("q" * 200).encode()[:72], _bcrypt.gensalt(4)).decode()
    assert verify_password("q" * 200, legacy) and needs_rehash(legacy)


@pytest.mark.asyncio
async def test_legacy_hash_is_upgraded_on_login():
    import bcrypt as _bcrypt

    from app.security import PREHASH_PREFIX

    email = f"legacy-{uuid.uuid4().hex[:6]}@example.com"
    async with _client() as c:
        await _signup(c, email, workspace="Legacy")
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        user.password_hash = _bcrypt.hashpw(b"correct-horse-battery", _bcrypt.gensalt(4)).decode()
        await session.commit()
    async with _client() as c:
        assert (await c.post("/api/auth/login", json={"email": email, "password": "correct-horse-battery"})).status_code == 200
    async with AsyncSessionLocal() as session:
        stored = (await session.execute(select(User.password_hash).where(User.email == email))).scalar_one()
    assert stored.startswith(PREHASH_PREFIX)


@pytest.mark.asyncio
async def test_login_rate_limit_is_per_email_not_per_address():
    rate_limiter.reset()
    email = f"v-{uuid.uuid4().hex[:6]}@example.com"
    async with _client() as c:
        await _signup(c, email, workspace="Victim")
    async with _client() as attacker:
        for _ in range(12):
            await attacker.post("/api/auth/login", json={"email": "someone-else@example.com", "password": "wrong"})
    async with _client() as colleague:
        # Same address (test client), different email: must still get in.
        r = await colleague.post("/api/auth/login", json={"email": email, "password": "correct-horse-battery"})
    assert r.status_code == 200
    rate_limiter.reset()


@pytest.mark.asyncio
async def test_note_cannot_reference_another_workspaces_meeting():
    from app.services.processing import processing_pipeline

    async with _client() as a, _client() as b:
        await _signup(a, f"na-{uuid.uuid4().hex[:6]}@example.com", workspace="NoteA")
        await _signup(b, f"nb-{uuid.uuid4().hex[:6]}@example.com", workspace="NoteB")
        meeting = (await a.post("/api/meetings/upload", json={"title": "A only", "transcript": "Sam: hello."})).json()
        await processing_pipeline.wait_for(uuid.UUID(meeting["id"]))
        assert (await b.post("/api/notebook/notes", json={"title": "x", "meeting_id": meeting["id"]})).status_code == 404
        own = (await b.post("/api/notebook/notes", json={"title": "mine"})).json()
        patched = await b.patch(f"/api/notebook/notes/{own['id']}", json={"meeting_id": meeting["id"]})
        assert patched.json()["meeting_id"] is None  # meeting_id is not updatable
        assert (await a.post("/api/notebook/notes", json={"title": "ok", "meeting_id": meeting["id"]})).status_code == 201


@pytest.mark.asyncio
async def test_racing_signups_with_the_same_workspace_name_never_500():
    import asyncio

    rate_limiter.reset()
    name = f"Race {uuid.uuid4().hex[:4]}"

    async def one(i):
        async with _client() as c:
            return (await c.post("/api/members", json={"name": "R", "email": f"race{i}-{uuid.uuid4().hex[:4]}@example.com", "password": "correct-horse-battery", "workspace_name": name})).status_code

    codes = await asyncio.gather(*(one(i) for i in range(6)))
    assert 500 not in codes and codes.count(200) + codes.count(201) == 6, codes
    rate_limiter.reset()


# ---------------------------------------------------------------------------
# Self-signup policy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_self_signup_can_be_switched_off_but_the_first_account_always_works(monkeypatch):
    """
    A server on the public internet may not want strangers creating
    workspaces. With ALLOW_SELF_SIGNUP=false, anonymous sign-up is refused -
    except the very first account, or nobody could ever sign in - and an
    owner can still add teammates.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "ALLOW_SELF_SIGNUP", False)
    async with _client() as first, _client() as stranger:
        await _signup(first, f"first-{uuid.uuid4().hex[:6]}@example.com", workspace="Closed Co")
        code = (await first.get("/api/members/workspace")).json()["join_code"]

        r = await stranger.post("/api/members", json={"name": "s", "email": f"s-{uuid.uuid4().hex[:6]}@example.com", "password": "correct-horse-battery", "workspace_name": "Mine"})
        assert r.status_code == 403 and "switched off" in r.json()["detail"]
        r = await stranger.post("/api/members", json={"name": "s", "email": f"s-{uuid.uuid4().hex[:6]}@example.com", "password": "correct-horse-battery", "join_code": code})
        assert r.status_code == 403

        # An owner adding someone is not self-signup.
        r = await first.post("/api/members", json={"name": "t", "email": f"t-{uuid.uuid4().hex[:6]}@example.com", "password": "correct-horse-battery"})
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_account_creation_has_a_tighter_per_address_ceiling():
    """QA: sixty distinct-email sign-ups a minute from one address all passed. Fifteen is plenty for a team."""
    async with _client() as c:
        codes = []
        for i in range(20):
            r = await c.post("/api/members", json={"name": "r", "email": f"r{i}-{uuid.uuid4().hex[:6]}@example.com", "password": "correct-horse-battery", "workspace_name": f"rl{i}"})
            codes.append(r.status_code)
        assert codes[:15] == [200] * 15 and 429 in codes[15:], codes
