"""
A workspace's AI provider: each member's own install (the default), or one
the owner sets for everyone.

The install-level config in config.json is per machine. This is the other
axis: a choice stored *with the workspace*, so five people on one shared
database can be made to use the same model - and the proof that matters is
which provider a request in that workspace actually calls.
"""
import json

import pytest

from app.providers.llm import LLMConfigError
from app.services.llm import build_llm_config, workspace_llm
from tests.test_security import _client, _fresh_rate_limits, _signup  # noqa: F401


def test_build_workspace_config_uses_the_workspace_values_not_the_install(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "llama3.1")
    cfg = build_llm_config({"mode": "workspace", "provider": "groq", "model": "llama-3.3-70b", "api_key": "gsk-team"})
    assert (cfg.provider, cfg.model, cfg.api_key) == ("groq", "llama-3.3-70b", "gsk-team")
    assert cfg.base_url is None  # the provider fills in its own default - not this install's LLM_BASE_URL
    with pytest.raises(LLMConfigError, match="owner has not set it up"):
        build_llm_config({"mode": "workspace"})
    with pytest.raises(LLMConfigError, match="Unknown LLM provider"):
        build_llm_config({"mode": "workspace", "provider": "skynet"})


def test_workspace_llm_only_applies_in_workspace_mode():
    class Org:
        settings = None
    assert workspace_llm(Org()) is None
    Org.settings = {"llm": {"mode": "member", "provider": "groq", "api_key": "k"}}
    assert workspace_llm(Org()) is None
    Org.settings = {"llm": {"mode": "workspace", "provider": "groq", "api_key": "k"}}
    assert workspace_llm(Org())["provider"] == "groq"


@pytest.mark.asyncio
async def test_owner_sets_a_unified_provider_and_every_member_uses_it(httpx_mock, monkeypatch):
    # This install has its own provider: Ollama, as a member's laptop would.
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "llama3.1")
    monkeypatch.setenv("LLM_BASE_URL", "http://ollama.local:11434")

    async with _client() as owner, _client() as member:
        await _signup(owner, "ai-owner@example.com", workspace="Unified Co")
        code = (await owner.get("/api/members/workspace")).json()["join_code"]
        await _signup(member, "ai-member@example.com", join_code=code, approve_by=owner)
        await owner.post("/api/notebook/notes", json={"title": "Roadmap", "content": "Ship the widget in Q4."})

        # Default: members use their own.
        assert (await owner.get("/api/members/workspace")).json()["ai"]["mode"] == "member"
        assert (await member.get("/api/auth/check")).json()["member"]["workspace_ai"] == {"mode": "member"}

        # Only an owner may change it.
        r = await member.put("/api/members/workspace/ai", json={"mode": "workspace", "provider": "groq", "api_key": "x"})
        assert r.status_code == 403
        assert (await owner.put("/api/members/workspace/ai", json={"mode": "nope"})).status_code == 400
        assert (await owner.put("/api/members/workspace/ai", json={"mode": "workspace"})).status_code == 400
        assert (await owner.put("/api/members/workspace/ai", json={"mode": "workspace", "provider": "skynet"})).status_code == 400
        # Local means each person's own machine: not something a workspace can share.
        r = await owner.put("/api/members/workspace/ai", json={"mode": "workspace", "provider": "ollama", "model": "llama3.1"})
        assert r.status_code == 400 and "own machine" in r.json()["detail"]

        r = await owner.put("/api/members/workspace/ai", json={
            "mode": "workspace", "provider": "groq", "model": "llama-3.3-70b", "api_key": "gsk-team-secret",
        })
        assert r.status_code == 200, r.text
        # The key is never echoed; a masked preview is.
        assert r.json()["mode"] == "workspace" and r.json()["provider"] == "groq"
        assert "gsk-team-secret" not in r.text and r.json()["api_key"]
        ws = (await member.get("/api/members/workspace")).json()
        assert "gsk-team-secret" not in json.dumps(ws)
        assert ws["ai"]["provider"] == "groq"
        assert (await member.get("/api/auth/check")).json()["member"]["workspace_ai"] == {
            "mode": "workspace", "provider": "groq", "model": "llama-3.3-70b",
        }

        # The member's Ask AI now goes to Groq with the workspace key - not to
        # the Ollama this install is configured with.
        httpx_mock.add_response(
            url="https://api.groq.com/openai/v1/chat/completions",
            json={"choices": [{"message": {"content": "The widget ships in Q4."}}]},
        )
        r = await member.post("/api/notebook/ask", json={"question": "When does the widget ship?"})
        assert r.status_code == 200, r.text
        sent = httpx_mock.get_requests()
        assert len(sent) == 1 and sent[0].headers["Authorization"] == "Bearer gsk-team-secret"
        assert json.loads(sent[0].content)["model"] == "llama-3.3-70b"

        # A blank key on a later save keeps the stored one.
        r = await owner.put("/api/members/workspace/ai", json={"mode": "workspace", "provider": "groq", "model": "llama-3.1-8b"})
        assert r.status_code == 200 and r.json()["model"] == "llama-3.1-8b" and r.json()["api_key"]
        httpx_mock.add_response(
            url="https://api.groq.com/openai/v1/chat/completions",
            json={"choices": [{"message": {"content": "Q4."}}]},
        )
        await member.post("/api/notebook/ask", json={"question": "When?"})
        assert httpx_mock.get_requests()[-1].headers["Authorization"] == "Bearer gsk-team-secret"

        # Back to "member": the install's own provider applies again, and the
        # details are kept so switching back later needs no retyping.
        r = await owner.put("/api/members/workspace/ai", json={"mode": "member"})
        assert r.status_code == 200 and r.json()["mode"] == "member" and r.json()["provider"] == "groq"
        assert (await member.get("/api/auth/check")).json()["member"]["workspace_ai"] == {"mode": "member"}
        httpx_mock.add_response(
            url="http://ollama.local:11434/api/chat",
            json={"message": {"content": "Q4 (says Ollama)."}},
        )
        r = await member.post("/api/notebook/ask", json={"question": "When?"})
        assert r.status_code == 200, r.text
        assert "ollama.local" in str(httpx_mock.get_requests()[-1].url)


@pytest.mark.asyncio
async def test_workspace_ai_test_endpoint_tries_the_settings_without_saving(httpx_mock):
    async with _client() as owner:
        await _signup(owner, "ai-test@example.com", workspace="Try Co")
        httpx_mock.add_response(
            url="https://api.groq.com/openai/v1/models",
            json={"data": [{"id": "llama-3.3-70b"}]},
        )
        r = await owner.post("/api/members/workspace/ai/test", json={
            "mode": "workspace", "provider": "groq", "model": "llama-3.3-70b", "api_key": "gsk-try",
        })
        assert r.status_code == 200 and r.json()["ok"] is True, r.text
        assert httpx_mock.get_requests()[0].headers["Authorization"] == "Bearer gsk-try"
        # Nothing was saved.
        assert (await owner.get("/api/members/workspace")).json()["ai"]["mode"] == "member"
        r = await owner.post("/api/members/workspace/ai/test", json={"mode": "workspace", "provider": "groq"})
        assert r.status_code == 200 and r.json()["ok"] is False  # groq needs a key; none stored yet
