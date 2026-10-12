"""
Standalone Demonstration Script for Meet Companion Pipeline.
Simulates Meeting 1 with Acme Corp, extracts memories, indexes embeddings,
and runs semantic search queries to answer questions from the meeting history.
"""
import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.memory import memory_extractor
from app.rag.chunking import transcript_chunker
from app.services.embedding import embedding_service
from app.rag.retrieval import cosine_similarity


async def run_pipeline_demo():
    print("=" * 70)
    print("MEETSTREAM COMPANION - MEMORY & RAG PIPELINE DEMO")
    print("=" * 70)

    # 1. Simulate Meeting Transcript
    transcript = """John: Acme requires SSO integration before launch.
Sarah: I will send the SOC 2 compliance documentation by tomorrow.
John: Let's target September 15 for the public launch date.
David: We should also verify that data retention policies meet the enterprise SLA."""

    print("\n[1] SIMULATED MEETING TRANSCRIPT:")
    print("-" * 50)
    print(transcript)
    print("-" * 50)

    # 2. Extract Memories
    print("\n[2] EXTRACTING STRUCTURED MEMORIES & ACTION ITEMS...")
    extracted = await memory_extractor.extract_memories(
        transcript_text=transcript,
        meeting_title="Acme Corp Product & Security Architecture Review",
        customer_name="Acme Corp",
        project_name="Enterprise Launch",
    )

    print("\n--- Summary ---")
    print(extracted.get("summary"))

    print("\n--- Extracted Memories ---")
    memories = extracted.get("memories", [])
    for i, m in enumerate(memories, 1):
        print(f"  {i}. [{m['type'].upper()}] (Speaker: {m.get('speaker', 'Unknown')} | Importance: {m.get('importance', 5)}/10)")
        print(f"     \"{m['content']}\"")

    print("\n--- Action Items ---")
    actions = extracted.get("action_items", [])
    for i, a in enumerate(actions, 1):
        print(f"  {i}. Owner: {a.get('owner', 'Unassigned')} | Priority: {a.get('priority', 'medium')}")
        print(f"     Task: \"{a.get('task')}\"")

    # 3. Vector Indexing
    print("\n[3] GENERATING EMBEDDINGS & INDEXING INTO MEETING MEMORY RAG...")
    indexed_store = []

    # Embed memories
    for m in memories:
        text_repr = f"[{m['type'].upper()}] (Speaker: {m.get('speaker', 'Unknown')}): {m['content']}"
        vec = embedding_service.embed_text(text_repr)
        indexed_store.append({
            "source": "memory",
            "type": m["type"],
            "speaker": m.get("speaker"),
            "content": m["content"],
            "vector": vec,
        })

    # Embed transcript chunks
    segments = [
        {"speaker": "John", "text": "Acme requires SSO integration before launch."},
        {"speaker": "Sarah", "text": "I will send the SOC 2 compliance documentation by tomorrow."},
        {"speaker": "John", "text": "Let's target September 15 for the public launch date."},
        {"speaker": "David", "text": "We should also verify that data retention policies meet the enterprise SLA."},
    ]
    chunks = transcript_chunker.chunk_transcript_segments(segments)
    for c in chunks:
        vec = embedding_service.embed_text(c.text)
        indexed_store.append({
            "source": "transcript_chunk",
            "type": "chunk",
            "speaker": c.speaker,
            "content": c.text,
            "vector": vec,
        })

    print(f"Indexed {len(indexed_store)} total memory items into vector space.")

    # 4. Semantic Search Queries
    test_queries = [
        "What did Acme require before launch?",
        "Who was supposed to send the SOC 2 documentation?",
        "What launch date did the team agree on?",
        "What was mentioned about data retention policies?",
    ]

    print("\n[4] EXECUTING PERSISTENT MEMORY QUERIES (VIA COMPANION):")
    print("=" * 70)

    for q in test_queries:
        print(f"\n[QUERY] \"{q}\"")
        q_vec = embedding_service.embed_text(q)
        scored = []
        for item in indexed_store:
            sim = cosine_similarity(q_vec, item["vector"])
            scored.append((item, sim))
        scored.sort(key=lambda x: x[1], reverse=True)

        top_match, top_sim = scored[0]
        print(f"   -> Top Match (Relevance: {top_sim:.4f}) [{top_match['source']}]:")
        print(f"      \"{top_match['content']}\" (Speaker: {top_match['speaker'] or 'Team'})")

    print("\n" + "=" * 70)
    print("DEMO COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_pipeline_demo())
