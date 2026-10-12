"""
Company Knowledge RAG Engine.
Enables indexing and semantic retrieval over company documents
(PDFs, Markdown guides, Word documents, text files, CSVs).
"""
import uuid
import os
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.embedding import embedding_service
from app.models.database import CompanyKnowledgeEmbedding
from app.providers.database import get_search_backend
from app.rag.retrieval import reciprocal_rank_fusion
from langchain_text_splitters import RecursiveCharacterTextSplitter


class CompanyKnowledgeRAG:
    def __init__(self):
        self.embedding_service = embedding_service
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=150,
            length_function=len,
        )

    def chunk_text(self, text: str, source_name: str) -> List[Dict[str, Any]]:
        """Split document text into clean semantic chunks."""
        clean = str(text or "").encode("utf-8", "ignore").decode("utf-8")
        chunks = self.splitter.split_text(clean)
        return [
            {
                "text": c.strip(),
                "source_name": source_name,
                "chunk_index": i,
            }
            for i, c in enumerate(chunks)
            if c.strip()
        ]

    async def index_document(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        document_id: uuid.UUID,
        source_name: str,
        source_type: str,
        text_content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Chunk and embed a company document into company_knowledge_embeddings.
        """
        chunks = self.chunk_text(text_content, source_name)
        if not chunks:
            return 0

        texts = [c["text"] for c in chunks]
        embeddings = await self.embedding_service.embed_batch_async(texts)

        for chunk, emb in zip(chunks, embeddings):
            record = CompanyKnowledgeEmbedding(
                organization_id=org_id,
                document_id=document_id,
                source_type=source_type,
                source_name=source_name,
                content=chunk["text"],
                embedding=emb,
                metadata_=metadata or {},
            )
            db.add(record)

        await db.flush()
        return len(chunks)

    async def search(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        query: str,
        *,
        limit: int = 6,
        min_similarity: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """
        Passages from uploaded documents relevant to the query, hybrid-ranked
        the same way meeting memory is (vector + keyword, fused by rank), on
        whichever database backend is live.
        """
        backend = get_search_backend(db)
        conditions = [CompanyKnowledgeEmbedding.organization_id == org_id]
        pool = max(limit * 3, 12)

        vector_hits: List = []
        try:
            embedded = await self.embedding_service.embed_text_async(query)
            vector_hits = await backend.vector_search(
                CompanyKnowledgeEmbedding, conditions, embedded, limit=pool, min_similarity=min_similarity
            )
        except Exception:
            vector_hits = []
        keyword_hits = await backend.keyword_search(CompanyKnowledgeEmbedding, conditions, query, limit=pool)

        def as_dicts(hits):
            return [
                {
                    "id": str(row.id),
                    "document_id": str(row.document_id) if row.document_id else None,
                    "source_name": row.source_name,
                    "content": row.content,
                }
                for row, _score in hits
            ]

        fused = reciprocal_rank_fusion([as_dicts(vector_hits), as_dicts(keyword_hits)])
        return [
            {k: v for k, v in item.items() if k != "id"}
            for item in fused[:limit]
        ]


company_knowledge_rag = CompanyKnowledgeRAG()
