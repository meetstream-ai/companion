"""
End-to-End Critical Path Test: Acme SSO Scenario.
Verifies the complete flow from raw transcript ingestion to structured memory extraction
and subsequent semantic question answering.
"""
import pytest
from app.services.memory import MemoryExtractionService
from app.rag.chunking import TranscriptChunker
from app.services.embedding import EmbeddingService
from app.rag.retrieval import cosine_similarity
from app.models.database import MemoryType


@pytest.mark.asyncio
async def test_acme_sso_e2e_scenario(monkeypatch):
    # Deterministic: the rule-based extractor, not whichever LLM is configured.
    monkeypatch.setattr("app.services.memory.try_get_llm_provider", lambda workspace=None: None)
    """
    Simulates Meeting #1:
    - John: "Acme requires SSO integration before launch."
    - Sarah: "I'll send the SOC 2 compliance documentation by tomorrow."
    - John: "Let's target September 15 for the public launch date."

    Verifies questions:
    1. "What did Acme require before launch?" -> SSO
    2. "Who was supposed to send the SOC 2 documentation?" -> Sarah
    3. "What launch date did the team agree on?" -> September 15
    """
    raw_transcript = """John: Acme requires SSO integration before launch.
Sarah: I will send the SOC 2 compliance documentation by tomorrow.
John: Let's target September 15 for the public launch date."""

    # 1. Memory Extraction
    extractor = MemoryExtractionService()
    extracted = await extractor.extract_memories(
        transcript_text=raw_transcript,
        meeting_title="Acme Architecture & Security Review",
        customer_name="Acme Corp",
        project_name="Enterprise Launch",
    )

    memories = extracted["memories"]
    action_items = extracted["action_items"]

    assert len(memories) >= 3
    assert len(action_items) >= 1

    # 2. Embedding Indexing
    embedder = EmbeddingService(dimension=384)
    indexed_items = []

    for m in memories:
        text_repr = f"[{m['type'].upper()}] (Speaker: {m['speaker']}): {m['content']}"
        vec = embedder.embed_text(text_repr)
        indexed_items.append({
            "type": m["type"],
            "speaker": m["speaker"],
            "content": m["content"],
            "vector": vec,
        })

    # Add transcript chunks as well
    chunker = TranscriptChunker()
    segments = [
        {"speaker": "John", "text": "Acme requires SSO integration before launch."},
        {"speaker": "Sarah", "text": "I will send the SOC 2 compliance documentation by tomorrow."},
        {"speaker": "John", "text": "Let's target September 15 for the public launch date."},
    ]
    chunks = chunker.chunk_transcript_segments(segments)
    for c in chunks:
        vec = embedder.embed_text(c.text)
        indexed_items.append({
            "type": "transcript_chunk",
            "speaker": c.speaker,
            "content": c.text,
            "vector": vec,
        })

    # Helper search function
    def search(query: str):
        q_vec = embedder.embed_text(query)
        scored = []
        for item in indexed_items:
            sim = cosine_similarity(q_vec, item["vector"])
            scored.append((item, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    # 3. Query 1: "What did Acme require before launch?"
    q1_results = search("What did Acme require before launch?")
    assert len(q1_results) > 0
    top_hit_1 = q1_results[0][0]
    assert "SSO" in top_hit_1["content"]

    # 4. Query 2: "Who was supposed to send the SOC 2 documentation?"
    q2_results = search("Who was supposed to send the SOC 2 documentation?")
    assert len(q2_results) > 0
    top_hit_2 = q2_results[0][0]
    assert "SOC 2" in top_hit_2["content"]
    assert top_hit_2["speaker"] == "Sarah" or "Sarah" in top_hit_2["content"]

    # 5. Query 3: "What launch date did the team agree on?"
    q3_results = search("What launch date did the team agree on?")
    assert len(q3_results) > 0
    top_hit_3 = q3_results[0][0]
    assert "September 15" in top_hit_3["content"]
