"""
Signing in with the machine's device key.

The desktop app presents a secret only a local process can read, so the person
who installed it is not asked for a password every launch. What matters is that
it is a *sign-in*, not a bypass: a wrong key, a missing key, or an ambiguous
"which owner?" must all still get 401.
"""
import uuid

import pytest
from sqlalchemy import select

from app.database.connection import AsyncSessionLocal
from app.middleware.auth_gate import COOKIE_NAME, DEVICE_COOKIE_NAME
from app.models.database import Membership, Organization, User
from app.secrets import device_secret
from app.security import hash_password


async def _make_owner(email: str, org_id=None):
    org_id = org_id or uuid.uuid4()
    async with AsyncSessionLocal() as session:
        if not (await session.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none():
            session.add(Organization(id=org_id, name=f"W-{org_id.hex[:6]}", slug=f"w-{org_id.hex[:6]}",
                                     mcp_token=uuid.uuid4().hex, join_code=uuid.uuid4().hex[:8]))
        user = User(id=uuid.uuid4(), organization_id=org_id, email=email, name=email,
                    role="owner", is_active=True, settings={},
                    password_hash=hash_password("SomePassword123"))
        session.add(user)
        await session.flush()
        session.add(Membership(user_id=user.id, organization_id=org_id, role="owner"))
        await session.commit()
        return user.id


@pytest.mark.asyncio
async def test_no_cookies_at_all_is_still_refused(client):
    assert (await client.get("/api/notebook/notes")).status_code == 401


@pytest.mark.asyncio
async def test_device_key_signs_in_the_sole_owner(client):
    await _make_owner("solo@device.test")
    r = await client.get("/api/notebook/notes", headers={"Cookie": f"{DEVICE_COOKIE_NAME}={device_secret()}"})
    assert r.status_code == 200, r.text
    # It issues a real session rather than waving the request through.
    assert COOKIE_NAME in r.cookies


@pytest.mark.asyncio
async def test_a_wrong_device_key_is_refused(client):
    await _make_owner("solo2@device.test")
    r = await client.get("/api/notebook/notes", headers={"Cookie": f"{DEVICE_COOKIE_NAME}=not-the-real-key"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_device_key_refuses_when_several_owners_exist(client):
    """On a shared workspace 'the local user' is ambiguous - do not guess."""
    org = uuid.uuid4()
    await _make_owner("one@device.test", org)
    await _make_owner("two@device.test", org)
    r = await client.get("/api/notebook/notes", headers={"Cookie": f"{DEVICE_COOKIE_NAME}={device_secret()}"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_device_key_does_not_resurrect_a_deactivated_owner(client):
    user_id = await _make_owner("gone@device.test")
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        user.is_active = False
        await session.commit()
    r = await client.get("/api/notebook/notes", headers={"Cookie": f"{DEVICE_COOKIE_NAME}={device_secret()}"})
    assert r.status_code == 401


def test_device_key_exists_before_anything_asks_for_it(tmp_path, monkeypatch):
    """
    Start-up must write the file, not wait for first use.

    The desktop shell reads device.key *before* loading the UI, so a lazily
    created key is one that never exists when it is needed - auto sign-in
    silently does nothing.
    """
    import app.secrets as secrets_module

    monkeypatch.setenv("MEET_COMPANION_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(secrets_module, "_device_secret", None)

    key_file = tmp_path / "device.key"
    assert not key_file.exists()

    value = secrets_module.device_secret()
    assert key_file.exists(), "device_secret() must persist the key"
    assert key_file.read_text(encoding="utf-8").strip() == value
    # Stable across calls, or the desktop cookie would stop matching.
    monkeypatch.setattr(secrets_module, "_device_secret", None)
    assert secrets_module.device_secret() == value


def test_startup_creates_the_device_key(tmp_path, monkeypatch):
    """The lifespan calls it, so a fresh install has the file on disk."""
    import inspect

    import app.main as main_module

    source = inspect.getsource(main_module.lifespan)
    assert "device_secret()" in source, "startup must create the device key"


@pytest.mark.asyncio
async def test_auth_check_reports_signed_in_with_the_device_key(client):
    """
    /api/auth/* skips the gate, so this endpoint needs the device key of its
    own accord - it is what the UI boots on to decide whether to show the
    sign-in screen. Without it the app is authenticated for every API call yet
    still asks you to log in.
    """
    await _make_owner("boot@device.test")
    r = await client.get("/api/auth/check", headers={"Cookie": f"{DEVICE_COOKIE_NAME}={device_secret()}"})
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is True
    assert body["member"]["email"] == "boot@device.test"
    assert COOKIE_NAME in r.cookies, "it should hand back a real session too"


@pytest.mark.asyncio
async def test_auth_check_still_reports_signed_out_without_a_key(client):
    await _make_owner("nokey@device.test")
    assert (await client.get("/api/auth/check")).json()["authenticated"] is False
    bad = await client.get("/api/auth/check", headers={"Cookie": f"{DEVICE_COOKIE_NAME}=nope"})
    assert bad.json()["authenticated"] is False


@pytest.mark.asyncio
async def test_device_key_recovers_from_a_session_for_a_user_this_database_lacks(client):
    """
    Seen after switching databases from Settings: the browser kept a
    well-signed session cookie for a user the new database does not have.
    /auth/check decoded it, skipped the device key, failed the lookup and
    answered signed-out - and the desktop app cannot clear that cookie.
    """
    import time

    from app.middleware.auth_gate import SESSION_TTL_SECONDS, sign_session

    owner = await _make_owner("survivor@device.test")
    ghost = sign_session(str(uuid.uuid4()), int(time.time()) + SESSION_TTL_SECONDS)
    r = await client.get(
        "/api/auth/check",
        headers={"Cookie": f"{COOKIE_NAME}={ghost}; {DEVICE_COOKIE_NAME}={device_secret()}"},
    )
    assert r.status_code == 200
    assert r.json()["authenticated"] is True
    assert r.json()["member"]["email"] == "survivor@device.test"
    assert COOKIE_NAME in r.headers.get("set-cookie", "")  # replaced with a live session

    # Without the device key a ghost session is still simply signed out.
    r = await client.get("/api/auth/check", headers={"Cookie": f"{COOKIE_NAME}={ghost}"})
    assert r.json() == {"authenticated": False}
    assert owner is not None
