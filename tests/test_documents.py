"""
Uploaded documents: indexed, retrievable by Ask AI, isolated per workspace,
removable.
"""
import io
import uuid
import zipfile

import pytest

from app.providers.llm import ChatMessage, LLMProvider, ProviderStatus


def _docx(text: str) -> bytes:
    """A minimal .docx: a zip with word/document.xml."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f"<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>")
    return buf.getvalue()


class _EchoProvider(LLMProvider):
    """Returns the prompt it was given, so the test can see what was retrieved."""
    name = "echo"
    label = "Echo"
    requires_api_key = False
    default_base_url = "http://echo"

    async def _complete(self, messages, *, json_mode=False, temperature=None, max_tokens=None):
        return messages[-1].content

    async def health_check(self):
        return ProviderStatus(ok=True, detail="ok")


@pytest.mark.asyncio
async def test_upload_index_ask_and_delete(authed_client, monkeypatch):
    from app.providers.llm import LLMConfig
    import app.api.notebook as notebook

    async def _echo(org_id, db):
        return _EchoProvider(LLMConfig(provider="echo", model="m"))

    monkeypatch.setattr(notebook, "provider_for_workspace", _echo)

    md = b"# Refund policy\n\nRefunds are issued within 14 days of purchase for annual plans.\n"
    up = await authed_client.post("/api/documents/upload", files={"file": ("policy.md", md, "text/markdown")})
    assert up.status_code == 202, up.text
    doc_id = up.json()["document_id"]
    assert up.json()["chunks_indexed"] >= 1

    up2 = await authed_client.post("/api/documents/upload", files={"file": ("handbook.docx", _docx("Office hours are 9 to 5."), "application/octet-stream")})
    assert up2.status_code == 202, up2.text

    listing = (await authed_client.get("/api/documents")).json()
    assert {d["filename"] for d in listing} == {"policy.md", "handbook.docx"}

    ask = await authed_client.post("/api/notebook/ask", json={"question": "How many days for a refund on annual plans?"})
    assert ask.status_code == 200, ask.text
    body = ask.json()
    assert "Document passages" in body["answer"] and "14 days" in body["answer"]
    assert [d["title"] for d in body["documents"]][0] == "policy.md"

    assert (await authed_client.delete(f"/api/documents/{doc_id}")).status_code == 204
    assert (await authed_client.delete(f"/api/documents/{doc_id}")).status_code == 404
    assert {d["filename"] for d in (await authed_client.get("/api/documents")).json()} == {"handbook.docx"}


@pytest.mark.asyncio
async def test_documents_are_workspace_scoped(authed_client):
    from tests.test_security import _client, _signup

    up = await authed_client.post("/api/documents/upload", files={"file": ("secret.txt", b"Alpha pricing is 42 per seat.", "text/plain")})
    doc_id = up.json()["document_id"]
    async with _client() as other:
        await _signup(other, f"d-{uuid.uuid4().hex[:6]}@example.com", workspace="Other")
        assert (await other.get("/api/documents")).json() == []
        assert (await other.delete(f"/api/documents/{doc_id}")).status_code == 404


@pytest.mark.asyncio
async def test_unsupported_and_oversized_uploads_are_refused(authed_client, monkeypatch):
    import app.api.documents as documents

    assert (await authed_client.post("/api/documents/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")})).status_code == 400
    monkeypatch.setattr(documents, "MAX_UPLOAD_BYTES", 10)
    assert (await authed_client.post("/api/documents/upload", files={"file": ("big.txt", b"x" * 11, "text/plain")})).status_code == 413


@pytest.mark.asyncio
async def test_upload_keeps_only_the_base_name(authed_client):
    r = await authed_client.post(
        "/api/documents/upload",
        files={"file": ("../../evil.txt", b"hello world " * 20, "text/plain")},
    )
    assert r.status_code == 202, r.text
    assert r.json()["filename"] == "evil.txt"
