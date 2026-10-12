"""
Action Item Endpoints.

Action items are extracted from every meeting, so they are most useful read
across meetings rather than one call at a time - that is what the dashboard's
outstanding-work view is built on.
"""
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from app import permissions as perms
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.connection import get_db
from app.database.repositories import ActionItemRepository, MeetingRepository
from app.models.schemas import ActionItemUpdate, ActionItemResponse
from app.api.deps import get_current_org_id

router = APIRouter(prefix="/api/action-items", tags=["action-items"])


@router.get("")
async def list_action_items(
    status_filter: Optional[str] = Query(None, alias="status"),
    owner: Optional[str] = None,
    meeting_id: Optional[uuid.UUID] = None,
    limit: int = Query(50, ge=1, le=200),
    org_id: uuid.UUID = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Action items across the workspace, soonest due first."""
    items = await ActionItemRepository(db).list_action_items(
        org_id, meeting_id=meeting_id, owner=owner, status=status_filter, limit=limit
    )

    # Titles are resolved in one pass so the list can link back to the meeting
    # each item came from without an N+1 query.
    meeting_titles = {}
    meeting_ids = {item.meeting_id for item in items if item.meeting_id}
    if meeting_ids:
        meeting_repo = MeetingRepository(db)
        for meeting_id_value in meeting_ids:
            meeting = await meeting_repo.get_by_id(org_id, meeting_id_value)
            if meeting:
                meeting_titles[meeting_id_value] = meeting.title

    note_titles = {}
    note_ids = {item.note_id for item in items if item.note_id}
    if note_ids:
        from sqlalchemy import select

        from app.models.database import Note

        rows = await db.execute(select(Note.id, Note.title).where(Note.id.in_(note_ids)))
        note_titles = {row.id: row.title for row in rows}

    return {
        "action_items": [
            {
                "id": str(item.id),
                "task": item.task,
                "owner": item.owner,
                "status": item.status,
                "priority": item.priority,
                "due_date": item.due_date.isoformat() if item.due_date else None,
                "meeting_id": str(item.meeting_id) if item.meeting_id else None,
                "meeting_title": meeting_titles.get(item.meeting_id),
                "note_id": str(item.note_id) if item.note_id else None,
                "note_title": note_titles.get(item.note_id),
            }
            for item in items
        ],
        "total": len(items),
    }


@router.patch("/{action_id}", response_model=ActionItemResponse, dependencies=[Depends(perms.require("edit_content"))])
async def update_action_item(
    action_id: uuid.UUID,
    update_in: ActionItemUpdate,
    org_id: uuid.UUID = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Update an action item's status, owner, due date, priority, or notes."""
    action_repo = ActionItemRepository(db)
    action = await action_repo.update(org_id, action_id, update_in)
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action item not found")
    if "status" in update_in.model_dump(exclude_unset=True):
        from app.services.meeting_notes import apply_action_item_to_notes

        await apply_action_item_to_notes(db, action)
    await db.commit()
    await db.refresh(action)
    return action
