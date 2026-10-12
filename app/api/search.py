"""
Meeting Memory Search Endpoint.
Exposes the same hybrid RAG search the in-meeting agent uses via MCP,
as a plain REST endpoint for the dashboard.
"""
import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.connection import get_db
from app.models.schemas import SearchMeetingMemoryQuery, SearchMeetingMemoryResponse
from app.rag.meeting_memory import meeting_memory_rag
from app.api.deps import get_current_org_id

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("/memory", response_model=SearchMeetingMemoryResponse)
async def search_meeting_memory(
    query_in: SearchMeetingMemoryQuery,
    org_id: uuid.UUID = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Hybrid (vector + keyword) search across indexed meeting transcripts and memories."""
    results = await meeting_memory_rag.search(
        db=db,
        org_id=org_id,
        query=query_in.query,
        customer_name=query_in.customer_name,
        project_name=query_in.project_name,
        speaker=query_in.speaker,
        meeting_id=query_in.meeting_id,
        memory_type=query_in.memory_type,
        date_from=query_in.date_from,
        date_to=query_in.date_to,
        min_similarity=query_in.min_similarity,
        limit=query_in.limit,
    )
    return SearchMeetingMemoryResponse(query=query_in.query, total_results=len(results), results=results)
