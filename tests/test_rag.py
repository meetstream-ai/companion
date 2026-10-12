"""
Unit tests for Meeting Memory RAG components (chunking, embeddings, retrieval math).
"""
import pytest
from app.rag.chunking import TranscriptChunker
from app.services.embedding import EmbeddingService
from app.rag.retrieval import cosine_similarity, reciprocal_rank_fusion


def test_transcript_chunking():
    chunker = TranscriptChunker(chunk_size=100, chunk_overlap=20)
    segments = [
        {"speaker": "John", "text": "We need SSO integration before launch.", "start_time": 0.0, "end_time": 5.0},
        {"speaker": "Sarah", "text": "I will send the SOC 2 compliance documentation by tomorrow.", "start_time": 5.5, "end_time": 10.0},
        {"speaker": "John", "text": "Great, let us target September 15 for the release date.", "start_time": 10.5, "end_time": 15.0},
    ]

    chunks = chunker.chunk_transcript_segments(segments)
    assert len(chunks) >= 1
    assert any("SSO" in c.text for c in chunks)
    assert any("SOC 2" in c.text for c in chunks)
    assert any("September 15" in c.text for c in chunks)


def test_embedding_service():
    service = EmbeddingService(dimension=384)
    texts = ["SSO requirements for Acme Corp", "Launch date is September 15"]
    embeddings = service.embed_batch(texts)

    assert len(embeddings) == 2
    assert len(embeddings[0]) == 384
    assert len(embeddings[1]) == 384


def test_cosine_similarity():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]

    assert pytest.approx(cosine_similarity(v1, v2), 0.001) == 1.0
    assert pytest.approx(cosine_similarity(v1, v3), 0.001) == 0.0


def test_reciprocal_rank_fusion():
    list1 = [{"id": "doc1", "title": "Doc 1"}, {"id": "doc2", "title": "Doc 2"}]
    list2 = [{"id": "doc2", "title": "Doc 2"}, {"id": "doc3", "title": "Doc 3"}]

    fused = reciprocal_rank_fusion([list1, list2], key_field="id", k=60)
    assert len(fused) == 3
    # doc2 appeared in both lists, so should be top ranked
    assert fused[0]["id"] == "doc2"
