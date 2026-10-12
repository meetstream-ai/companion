"""
The knowledge graph endpoint: every node type a processed meeting produces,
edges that only ever point at nodes in the same response, and nothing from
another workspace.
"""
import uuid

import pytest

from tests.test_security import _client, _fresh_rate_limits, _signup  # noqa: F401

TRANSCRIPT = """Priya: We agreed to ship the Atlas billing migration on October 3rd.
Marcus: I will write the rollback runbook by Friday.
Priya: Decision - we keep Stripe as the only payment provider this quarter."""


async def _processed_meeting(client, monkeypatch, title="Q3 sync"):
    from app.services.processing import processing_pipeline

    monkeypatch.setattr("app.services.memory.try_get_llm_provider", lambda workspace=None: None)
    r = await client.post("/api/meetings/upload", json={"title": title, "transcript": TRANSCRIPT, "project_name": "Atlas"})
    assert r.status_code == 202, r.text
    meeting_id = uuid.UUID(r.json()["id"])
    await processing_pipeline.wait_for(meeting_id)
    return str(meeting_id)


@pytest.mark.asyncio
async def test_graph_has_every_node_type_and_consistent_edges(authed_client, monkeypatch):
    meeting_id = await _processed_meeting(authed_client, monkeypatch)

    r = await authed_client.get("/api/graph")
    assert r.status_code == 200, r.text
    graph = r.json()
    nodes, edges = graph["nodes"], graph["edges"]

    by_type = {}
    for node in nodes:
        by_type.setdefault(node["type"], []).append(node)
    assert {"meeting", "person", "memory", "action_item", "project"} <= set(by_type), sorted(by_type)
    assert {n["label"] for n in by_type["person"]} >= {"Priya", "Marcus"}
    meeting_node = next(n for n in by_type["meeting"] if n["id"].endswith(meeting_id))
    assert meeting_node["label"] == "Q3 sync"
    assert meeting_node["date"] is None or meeting_node["date"].endswith(("Z", "+00:00"))

    ids = {n["id"] for n in nodes}
    assert ids, "no nodes"
    assert len(ids) == len(nodes), "duplicate node ids"
    for edge in edges:
        assert edge["source"] in ids and edge["target"] in ids, edge
    assert {e["type"] for e in edges} >= {"participated_in", "produced"}
    # Marcus committed to the runbook, so he owns that action item.
    marcus = next(n["id"] for n in by_type["person"] if n["label"] == "Marcus")
    assert any(e["source"] == marcus and e["type"] == "owns" for e in edges)


@pytest.mark.asyncio
async def test_graph_is_empty_for_a_fresh_workspace_and_scoped_to_it(authed_client, monkeypatch):
    await _processed_meeting(authed_client, monkeypatch, title="Mine")

    async with _client() as other:
        await _signup(other, f"g-{uuid.uuid4().hex[:6]}@example.com", workspace="Elsewhere")
        graph = (await other.get("/api/graph")).json()
        assert graph == {"nodes": [], "edges": []}

    async with _client() as anon:
        assert (await anon.get("/api/graph")).status_code == 401
