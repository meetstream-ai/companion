"""
Pydantic schemas for request validation, serialization, and response bodies.
"""
import uuid
from datetime import datetime, date, timezone
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, HttpUrl, field_serializer
from app.models.database import MemoryType


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """
    Every timestamp is stored as UTC, but SQLite hands it back naive, and a
    naive ISO string ("2026-09-15T04:07:15") is read by browsers as *local*
    time - so the UI showed every time off by the viewer's UTC offset.
    Stamp the zone on the way out; Postgres already does.
    """
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def utc_iso(value: Optional[datetime]) -> Optional[str]:
    """ISO 8601 with an explicit offset, for handlers that build dicts by hand."""
    value = as_utc(value)
    return value.isoformat() if value else None


# ---- Common Base ----
class SchemaBase(BaseModel):
    model_config = {"from_attributes": True}

    @field_serializer("*", mode="wrap")
    def _utc_timestamps(self, value, handler, info):
        return handler(as_utc(value))


# ---- Organization Schemas ----
class OrganizationCreate(BaseModel):
    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=100)
    settings: Optional[Dict[str, Any]] = None


class OrganizationResponse(SchemaBase):
    id: uuid.UUID
    name: str
    slug: str
    settings: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


# ---- Participant Schemas ----
class ParticipantBase(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    identifier: Optional[str] = None
    platform_id: Optional[str] = None
    role: Optional[str] = None


class ParticipantResponse(SchemaBase, ParticipantBase):
    id: uuid.UUID
    meeting_id: uuid.UUID
    created_at: datetime


# ---- Transcript Segment Schemas ----
class TranscriptSegmentBase(BaseModel):
    speaker: Optional[str] = None
    speaker_identifier: Optional[str] = None
    text: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    confidence: Optional[float] = None
    segment_index: Optional[int] = None


class TranscriptSegmentCreate(TranscriptSegmentBase):
    word_data: Optional[Any] = None


class TranscriptSegmentResponse(SchemaBase, TranscriptSegmentBase):
    id: uuid.UUID
    meeting_id: uuid.UUID
    word_data: Optional[Any] = None
    created_at: datetime


# ---- Memory Schemas ----
class MemoryBase(BaseModel):
    type: MemoryType
    content: str
    importance: int = Field(default=5, ge=1, le=10)
    speaker: Optional[str] = None
    customer_name: Optional[str] = None
    project_name: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, alias="metadata_")


class MemoryCreate(MemoryBase):
    meeting_id: uuid.UUID
    source_segment_ids: Optional[List[uuid.UUID]] = None


class MemoryResponse(SchemaBase):
    id: uuid.UUID
    organization_id: uuid.UUID
    meeting_id: uuid.UUID
    type: MemoryType
    content: str
    importance: int
    speaker: Optional[str] = None
    customer_name: Optional[str] = None
    project_name: Optional[str] = None
    source_segment_ids: Optional[List[uuid.UUID]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ---- Action Item Schemas ----
class ActionItemBase(BaseModel):
    task: str
    owner: Optional[str] = None
    due_date: Optional[date] = None
    status: str = Field(default="open")
    priority: str = Field(default="medium")
    notes: Optional[str] = None


class ActionItemCreate(ActionItemBase):
    meeting_id: uuid.UUID
    memory_id: Optional[uuid.UUID] = None


ActionItemStatus = Literal["open", "in_progress", "completed", "cancelled"]
ActionItemPriority = Literal["low", "medium", "high", "critical"]


class ActionItemUpdate(BaseModel):
    task: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    owner: Optional[str] = Field(default=None, max_length=255)
    due_date: Optional[date] = None
    status: Optional[ActionItemStatus] = None
    priority: Optional[ActionItemPriority] = None
    notes: Optional[str] = Field(default=None, max_length=10_000)
    completed_at: Optional[datetime] = None


class ActionItemResponse(SchemaBase, ActionItemBase):
    id: uuid.UUID
    organization_id: uuid.UUID
    meeting_id: Optional[uuid.UUID] = None
    note_id: Optional[uuid.UUID] = None
    memory_id: Optional[uuid.UUID] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# ---- Meeting Schemas ----
class MeetingCreate(BaseModel):
    meeting_url: str = Field(..., min_length=1, max_length=2000, description="Link to the Google Meet, Zoom, or Teams call")
    title: Optional[str] = None
    customer_name: Optional[str] = None
    project_name: Optional[str] = None
    platform: Optional[str] = None
    agent_config_id: Optional[str] = None
    custom_attributes: Optional[Dict[str, Any]] = None


class MeetingUpdate(BaseModel):
    title: Optional[str] = None
    customer_name: Optional[str] = None
    project_name: Optional[str] = None
    status: Optional[str] = None
    summary: Optional[str] = None
    processing_status: Optional[str] = None
    processing_error: Optional[str] = None


class MeetingResponse(SchemaBase):
    id: uuid.UUID
    organization_id: uuid.UUID
    created_by_user_id: Optional[uuid.UUID] = None
    created_by_name: Optional[str] = None
    meetstream_bot_id: Optional[str] = None
    title: Optional[str] = None
    meeting_url: Optional[str] = None
    platform: Optional[str] = None
    customer_name: Optional[str] = None
    project_name: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    status: str
    summary: Optional[str] = None
    meetstream_transcript_id: Optional[str] = None
    processing_status: str
    processing_error: Optional[str] = None
    custom_attributes: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


class MeetingDetailResponse(MeetingResponse):
    participants: List[ParticipantResponse] = []
    memories: List[MemoryResponse] = []
    action_items: List[ActionItemResponse] = []
    transcript_segments_count: int = 0


# ---- Search & RAG Schemas ----
class SearchMeetingMemoryQuery(BaseModel):
    query: str
    customer_name: Optional[str] = None
    project_name: Optional[str] = None
    speaker: Optional[str] = None
    meeting_id: Optional[uuid.UUID] = None
    memory_type: Optional[MemoryType] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    min_similarity: float = 0.0
    limit: int = Field(default=10, ge=1, le=50)


class SearchResultItem(BaseModel):
    id: uuid.UUID
    content: str
    similarity: float
    source_type: str  # memory, transcript_chunk, summary
    meeting_id: Optional[uuid.UUID] = None
    memory_id: Optional[uuid.UUID] = None
    meeting_title: Optional[str] = None
    meeting_date: Optional[str] = None
    customer_name: Optional[str] = None
    project_name: Optional[str] = None
    speaker: Optional[str] = None
    memory_type: Optional[str] = None
    metadata: Dict[str, Any] = {}


class SearchMeetingMemoryResponse(BaseModel):
    query: str
    total_results: int
    results: List[SearchResultItem]


# ---- MeetStream Webhook Payload Schema ----
class MeetStreamWebhookPayload(BaseModel):
    bot_id: Optional[str] = None
    event: Optional[str] = None
    bot_event: Optional[str] = None
    bot_status: Optional[str] = None
    status_code: Optional[int] = None
    message: Optional[str] = None
    transcript_id: Optional[str] = None
    custom_attributes: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    model_config = {"extra": "allow"}
