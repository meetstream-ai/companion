"""
Notebook data access.

Kept separate from repositories.py so the notebook's own concerns - tree
manipulation, filtering, sorting - do not accumulate inside the already large
meeting repository.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import Text, and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Meeting, Note, NotebookFolder

SORT_FIELDS = {
    "updated": Note.updated_at,
    "created": Note.created_at,
    "title": Note.title,
}


class NotebookFolderRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_all(self, org_id: uuid.UUID) -> List[NotebookFolder]:
        stmt = (
            select(NotebookFolder)
            .where(NotebookFolder.organization_id == org_id)
            .order_by(func.lower(NotebookFolder.name))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, org_id: uuid.UUID, folder_id: uuid.UUID) -> Optional[NotebookFolder]:
        stmt = select(NotebookFolder).where(
            NotebookFolder.id == folder_id, NotebookFolder.organization_id == org_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(
        self, org_id: uuid.UUID, name: str, parent_id: Optional[uuid.UUID] = None
    ) -> NotebookFolder:
        folder = NotebookFolder(organization_id=org_id, name=name.strip() or "Untitled", parent_id=parent_id)
        self.session.add(folder)
        await self.session.commit()
        await self.session.refresh(folder)
        return folder

    async def rename(self, folder: NotebookFolder, name: str) -> NotebookFolder:
        folder.name = name.strip() or folder.name
        await self.session.commit()
        await self.session.refresh(folder)
        return folder

    async def move(self, folder: NotebookFolder, parent_id: Optional[uuid.UUID]) -> NotebookFolder:
        folder.parent_id = parent_id
        await self.session.commit()
        await self.session.refresh(folder)
        return folder

    async def would_create_cycle(
        self, org_id: uuid.UUID, folder_id: uuid.UUID, new_parent_id: Optional[uuid.UUID]
    ) -> bool:
        """
        Whether re-parenting would detach a subtree from the root.

        Moving a folder inside its own descendant orphans the whole branch, and
        nothing in the UI would be able to reach it again.
        """
        if new_parent_id is None:
            return False
        if new_parent_id == folder_id:
            return True

        folders = {f.id: f.parent_id for f in await self.list_all(org_id)}
        cursor: Optional[uuid.UUID] = new_parent_id
        seen: set = set()
        while cursor is not None and cursor not in seen:
            if cursor == folder_id:
                return True
            seen.add(cursor)
            cursor = folders.get(cursor)
        return False

    async def delete(self, folder: NotebookFolder, *, cascade: bool = False) -> None:
        """
        Remove a folder.

        By default its notes and subfolders are lifted to the parent rather
        than destroyed - deleting a folder should not silently take a year of
        notes with it. Passing cascade deletes the whole subtree.
        """
        org_id = folder.organization_id
        if cascade:
            ids = await self._subtree_ids(org_id, folder.id)
            await self.session.execute(delete(Note).where(Note.folder_id.in_(ids)))
            await self.session.execute(delete(NotebookFolder).where(NotebookFolder.id.in_(ids)))
        else:
            await self.session.execute(
                NotebookFolder.__table__.update()
                .where(NotebookFolder.parent_id == folder.id)
                .values(parent_id=folder.parent_id)
            )
            await self.session.execute(
                Note.__table__.update()
                .where(Note.folder_id == folder.id)
                .values(folder_id=folder.parent_id)
            )
            await self.session.execute(delete(NotebookFolder).where(NotebookFolder.id == folder.id))
        await self.session.commit()

    async def _subtree_ids(self, org_id: uuid.UUID, root_id: uuid.UUID) -> List[uuid.UUID]:
        by_parent: Dict[Optional[uuid.UUID], List[uuid.UUID]] = {}
        for folder in await self.list_all(org_id):
            by_parent.setdefault(folder.parent_id, []).append(folder.id)

        collected = [root_id]
        queue = [root_id]
        while queue:
            current = queue.pop()
            for child in by_parent.get(current, []):
                collected.append(child)
                queue.append(child)
        return collected


class NoteRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, org_id: uuid.UUID, note_id: uuid.UUID) -> Optional[Note]:
        stmt = select(Note).where(Note.id == note_id, Note.organization_id == org_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def build_filters(
        self,
        org_id: uuid.UUID,
        *,
        folder_id: Optional[uuid.UUID] = None,
        unfiled: bool = False,
        meeting_id: Optional[uuid.UUID] = None,
        note_type: Optional[str] = None,
        tag: Optional[str] = None,
        favorites_only: bool = False,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        note_ids: Optional[Sequence[uuid.UUID]] = None,
    ) -> List[Any]:
        conditions: List[Any] = [Note.organization_id == org_id]
        if note_ids:
            conditions.append(Note.id.in_(list(note_ids)))
        if unfiled:
            conditions.append(Note.folder_id.is_(None))
        elif folder_id is not None:
            conditions.append(Note.folder_id == folder_id)
        if meeting_id is not None:
            conditions.append(Note.meeting_id == meeting_id)
        if note_type:
            conditions.append(Note.note_type == note_type)
        if favorites_only:
            conditions.append(Note.is_favorite.is_(True))
        if since is not None:
            conditions.append(Note.updated_at >= since)
        if until is not None:
            conditions.append(Note.updated_at <= until)
        if tag:
            # Tags are a JSON array; a LIKE over its serialized form keeps this
            # working identically on SQLite and Postgres without a join table.
            conditions.append(func.lower(func.cast(Note.tags, Text)).like(f'%"{tag.lower()}"%'))
        return conditions

    async def list(
        self,
        conditions: Sequence[Any],
        *,
        query: Optional[str] = None,
        sort: str = "updated",
        descending: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Note], int]:
        all_conditions = list(conditions)
        if query and query.strip():
            like = f"%{query.strip().lower()}%"
            all_conditions.append(
                or_(func.lower(Note.title).like(like), func.lower(Note.content).like(like))
            )

        sort_column = SORT_FIELDS.get(sort, Note.updated_at)
        order = sort_column.desc() if descending else sort_column.asc()

        total = (
            await self.session.execute(
                select(func.count()).select_from(Note).where(and_(*all_conditions))
            )
        ).scalar_one()

        stmt = (
            select(Note)
            .where(and_(*all_conditions))
            .order_by(order)
            .limit(limit)
            .offset(offset)
        )
        notes = list((await self.session.execute(stmt)).scalars().all())
        return notes, int(total)

    async def create(self, org_id: uuid.UUID, **fields: Any) -> Note:
        note = Note(organization_id=org_id, **fields)
        self.session.add(note)
        await self.session.commit()
        await self.session.refresh(note)
        return note

    async def update(self, note: Note, **fields: Any) -> Note:
        for key, value in fields.items():
            if value is not None:
                setattr(note, key, value)
        await self.session.commit()
        await self.session.refresh(note)
        return note

    async def delete(self, note: Note) -> None:
        await self.session.delete(note)
        await self.session.commit()

    async def list_tags(self, org_id: uuid.UUID) -> List[str]:
        stmt = select(Note.tags).where(Note.organization_id == org_id)
        seen: List[str] = []
        for (tags,) in (await self.session.execute(stmt)).all():
            for tag in tags or []:
                if tag not in seen:
                    seen.append(tag)
        return sorted(seen, key=str.lower)

    async def counts(self, org_id: uuid.UUID) -> Dict[str, int]:
        base = Note.organization_id == org_id
        total = (
            await self.session.execute(select(func.count()).select_from(Note).where(base))
        ).scalar_one()
        favorites = (
            await self.session.execute(
                select(func.count()).select_from(Note).where(base, Note.is_favorite.is_(True))
            )
        ).scalar_one()
        unfiled = (
            await self.session.execute(
                select(func.count()).select_from(Note).where(base, Note.folder_id.is_(None))
            )
        ).scalar_one()
        return {"total": int(total), "favorites": int(favorites), "unfiled": int(unfiled)}


def build_folder_tree(folders: Sequence[NotebookFolder], note_counts: Dict[Optional[uuid.UUID], int]) -> List[Dict[str, Any]]:
    """Nest a flat folder list into the tree the sidebar renders."""
    by_parent: Dict[Optional[uuid.UUID], List[NotebookFolder]] = {}
    for folder in folders:
        by_parent.setdefault(folder.parent_id, []).append(folder)

    def build(parent_id: Optional[uuid.UUID], depth: int) -> List[Dict[str, Any]]:
        # Depth is bounded defensively: a cycle introduced outside the move
        # guard would otherwise recurse forever.
        if depth > 32:
            return []
        return [
            {
                "id": str(folder.id),
                "name": folder.name,
                "parent_id": str(folder.parent_id) if folder.parent_id else None,
                "note_count": note_counts.get(folder.id, 0),
                "children": build(folder.id, depth + 1),
            }
            for folder in by_parent.get(parent_id, [])
        ]

    return build(None, 0)
