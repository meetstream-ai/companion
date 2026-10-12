"""
Export notes and meetings as Markdown or JSON.

The point of this endpoint is that the data is the user's: everything they can
see in the app, they can take out of it in a format that outlives the app.
Markdown is for reading and for dropping into Obsidian/Notion; JSON is the
lossless one, keeping ids and metadata so an export can be re-imported or
processed by something else.

Everything is scoped to the caller's workspace - an export must never become a
way around tenant isolation.
"""
from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from app import permissions as perms
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_org_id
from app.database.connection import get_db
from app.models.database import Meeting, Note, NotebookFolder
from app.models.schemas import utc_iso

router = APIRouter(prefix="/api/export", tags=["export"])

#: Markers the notebook appends to checkbox lines to tie them to action items.
#: They are machinery, not content, so the readable export drops them. JSON
#: keeps the raw text so a round-trip stays lossless.
_ACTION_MARKER = re.compile(r"[ \t]*<!--\s*action:[0-9a-fA-F-]+\s*-->")

FORMATS = ("md", "json")


def _clean(text: Optional[str]) -> str:
    return _ACTION_MARKER.sub("", text or "")


def _slug(value: Optional[str], fallback: str = "untitled") -> str:
    """A filename-safe, ASCII-only stem."""
    base = re.sub(r"[^\w\s-]", "", (value or "").strip(), flags=re.ASCII).strip()
    base = re.sub(r"[\s_]+", "-", base).strip("-").lower()
    return (base or fallback)[:60]


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return utc_iso(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _attachment(body: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": 'attachment; filename="' + filename + '"'},
    )


def _front_matter(fields: Dict[str, Any]) -> str:
    """Minimal YAML front matter - the convention Obsidian and friends read."""
    # ensure_ascii=False keeps accents, CJK and emoji readable in the file
    # instead of turning a title into ·-style escapes.
    quote = lambda v: json.dumps(str(v), ensure_ascii=False)
    lines = ["---"]
    for key, value in fields.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            lines.append(key + ": [" + ", ".join(quote(v) for v in value) + "]")
        elif isinstance(value, bool):
            lines.append(key + ": " + ("true" if value else "false"))
        else:
            lines.append(key + ": " + quote(value))
    lines.append("---")
    return "\n".join(lines)


def _check_format(fmt: str) -> str:
    if fmt not in FORMATS:
        raise HTTPException(status_code=400, detail="Format must be 'md' or 'json'.")
    return fmt


def _unique(name: str, used: set) -> str:
    """Two notes can share a title; their files must not overwrite each other."""
    candidate, n = name, 2
    while candidate in used:
        candidate = name + "-" + str(n)
        n += 1
    used.add(candidate)
    return candidate


# ---------------------------------------------------------------- notes
def _folder_path(folder_id: Optional[uuid.UUID], folders: Dict[uuid.UUID, NotebookFolder]) -> str:
    """'Parent/Child' for a folder id, so exported files keep their shape."""
    parts: List[str] = []
    seen: set = set()
    current = folders.get(folder_id) if folder_id else None
    while current is not None and current.id not in seen:
        seen.add(current.id)
        parts.append(current.name)
        current = folders.get(current.parent_id) if current.parent_id else None
    return "/".join(reversed(parts))


def note_markdown(note: Note, folder_path: str = "") -> str:
    head = _front_matter(
        {
            "title": note.title,
            "type": note.note_type,
            "tags": note.tags or [],
            "folder": folder_path,
            "favourite": note.is_favorite,
            "created": _iso(note.created_at),
            "updated": _iso(note.updated_at),
            "meeting_id": str(note.meeting_id) if note.meeting_id else None,
        }
    )
    body = _clean(note.content).strip()
    # The title is already in the front matter; adding an H1 on top of content
    # that opens with its own heading would give the file two titles.
    if body.startswith("# "):
        return head + "\n\n" + body + "\n"
    return head + "\n\n# " + (note.title or "Untitled") + "\n\n" + body + "\n"


def note_json(note: Note, folder_path: str = "") -> Dict[str, Any]:
    return {
        "id": str(note.id),
        "title": note.title,
        "content": note.content,
        "note_type": note.note_type,
        "tags": note.tags or [],
        "folder": folder_path or None,
        "is_favorite": note.is_favorite,
        "meeting_id": str(note.meeting_id) if note.meeting_id else None,
        "created_at": _iso(note.created_at),
        "updated_at": _iso(note.updated_at),
    }


# ---------------------------------------------------------------- meetings
_MEMORY_HEADINGS = {
    "decision": "Decisions",
    "commitment": "Commitments",
    "requirement": "Requirements",
    "concern": "Concerns",
    "preference": "Preferences",
    "fact": "Facts",
    "project_update": "Project updates",
    "relationship_context": "Relationship context",
    "unresolved_question": "Unresolved questions",
}


#: Memories of this type restate what the action-item records below already
#: list, so the document carries each task once rather than twice.
_MEMORY_TYPES_COVERED_ELSEWHERE = {"action_item"}


def _memory_type(memory: Any) -> str:
    raw = getattr(memory, "type", None)
    return getattr(raw, "value", raw) or "fact"


def meeting_markdown(meeting: Meeting) -> str:
    when = meeting.started_at or meeting.created_at
    participants = [
        p.name or p.identifier for p in (meeting.participants or []) if (p.name or p.identifier)
    ]
    title = meeting.title or "Untitled meeting"
    head = _front_matter(
        {
            "title": title,
            "date": _iso(when),
            "platform": meeting.platform,
            "customer": meeting.customer_name,
            "project": meeting.project_name,
            "participants": participants,
            "status": meeting.status,
        }
    )
    out: List[str] = [head, "", "# " + title, ""]
    if when:
        out += ["*" + when.strftime("%A, %d %B %Y") + "*", ""]
    if participants:
        out += ["**Participants:** " + ", ".join(participants), ""]

    if meeting.summary:
        out += ["## Summary", "", meeting.summary.strip(), ""]

    grouped: Dict[str, List[Any]] = {}
    for memory in meeting.memories or []:
        kind = _memory_type(memory)
        if kind in _MEMORY_TYPES_COVERED_ELSEWHERE:
            continue
        grouped.setdefault(kind, []).append(memory)
    for kind, heading in _MEMORY_HEADINGS.items():
        items = grouped.get(kind)
        if not items:
            continue
        out += ["## " + heading, ""]
        for memory in sorted(items, key=lambda m: -(m.importance or 0)):
            speaker = " - *" + memory.speaker + "*" if memory.speaker else ""
            out.append("- " + memory.content.strip() + speaker)
        out.append("")

    if meeting.action_items:
        out += ["## Action items", ""]
        for item in meeting.action_items:
            box = "x" if item.status == "completed" else " "
            bits = [str(b) for b in (item.owner, _iso(item.due_date), item.priority) if b]
            suffix = " (" + ", ".join(bits) + ")" if bits else ""
            out.append("- [" + box + "] " + item.task.strip() + suffix)
        out.append("")

    segments = sorted(meeting.transcript_segments or [], key=lambda s: (s.segment_index or 0))
    if segments:
        out += ["## Transcript", ""]
        for segment in segments:
            out.append("**" + (segment.speaker or "Speaker") + ":** " + segment.text.strip())
            out.append("")

    return "\n".join(out).rstrip() + "\n"


def meeting_json(meeting: Meeting) -> Dict[str, Any]:
    return {
        "id": str(meeting.id),
        "title": meeting.title,
        "meeting_url": meeting.meeting_url,
        "platform": meeting.platform,
        "customer_name": meeting.customer_name,
        "project_name": meeting.project_name,
        "status": meeting.status,
        "processing_status": meeting.processing_status,
        "started_at": _iso(meeting.started_at),
        "ended_at": _iso(meeting.ended_at),
        "created_at": _iso(meeting.created_at),
        "summary": meeting.summary,
        "participants": [
            {"name": p.name, "email": p.email, "role": p.role}
            for p in (meeting.participants or [])
        ],
        "memories": [
            {
                "id": str(m.id),
                "type": _memory_type(m),
                "content": m.content,
                "speaker": m.speaker,
                "importance": m.importance,
            }
            for m in (meeting.memories or [])
        ],
        "action_items": [
            {
                "id": str(a.id),
                "task": a.task,
                "owner": a.owner,
                "due_date": _iso(a.due_date),
                "status": a.status,
                "priority": a.priority,
                "notes": a.notes,
            }
            for a in (meeting.action_items or [])
        ],
        "transcript": [
            {
                "speaker": s.speaker,
                "text": s.text,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "index": s.segment_index,
            }
            for s in sorted(meeting.transcript_segments or [], key=lambda s: (s.segment_index or 0))
        ],
    }


async def _load_folders(db: AsyncSession, org_id: uuid.UUID) -> Dict[uuid.UUID, NotebookFolder]:
    rows = await db.execute(
        select(NotebookFolder).where(NotebookFolder.organization_id == org_id)
    )
    return {folder.id: folder for folder in rows.scalars()}


def _meeting_options():
    return (
        selectinload(Meeting.participants),
        selectinload(Meeting.memories),
        selectinload(Meeting.action_items),
        selectinload(Meeting.transcript_segments),
    )


# ---------------------------------------------------------------- endpoints
@router.get("/note/{note_id}", dependencies=[Depends(perms.require("export_workspace"))])
async def export_note(
    note_id: uuid.UUID,
    format: str = Query("md"),
    org_id: uuid.UUID = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    _check_format(format)
    note = (
        await db.execute(
            select(Note).where(Note.id == note_id, Note.organization_id == org_id)
        )
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found.")

    path = _folder_path(note.folder_id, await _load_folders(db, org_id))
    stem = _slug(note.title, "note")

    if format == "json":
        body = json.dumps(note_json(note, path), indent=2, ensure_ascii=False).encode("utf-8")
        return _attachment(body, stem + ".json", "application/json")
    return _attachment(
        note_markdown(note, path).encode("utf-8"), stem + ".md", "text/markdown; charset=utf-8"
    )


@router.get("/meeting/{meeting_id}", dependencies=[Depends(perms.require("export_workspace"))])
async def export_meeting(
    meeting_id: uuid.UUID,
    format: str = Query("md"),
    org_id: uuid.UUID = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    _check_format(format)
    meeting = (
        await db.execute(
            select(Meeting)
            .where(Meeting.id == meeting_id, Meeting.organization_id == org_id)
            .options(*_meeting_options())
        )
    ).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    when = meeting.started_at or meeting.created_at
    stem = _slug(meeting.title, "meeting")
    if when:
        stem = when.date().isoformat() + "-" + stem

    if format == "json":
        body = json.dumps(meeting_json(meeting), indent=2, ensure_ascii=False).encode("utf-8")
        return _attachment(body, stem + ".json", "application/json")
    return _attachment(
        meeting_markdown(meeting).encode("utf-8"), stem + ".md", "text/markdown; charset=utf-8"
    )


@router.get("/workspace", dependencies=[Depends(perms.require("export_workspace"))])
async def export_workspace(
    format: str = Query("json"),
    org_id: uuid.UUID = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Everything in the workspace: JSON as one file, Markdown as a zip that keeps
    the notebook's folder structure so it opens like a vault.
    """
    _check_format(format)
    folders = await _load_folders(db, org_id)
    notes = list(
        (
            await db.execute(
                select(Note)
                .where(Note.organization_id == org_id)
                .order_by(Note.updated_at.desc())
            )
        ).scalars()
    )
    meetings = list(
        (
            await db.execute(
                select(Meeting)
                .where(Meeting.organization_id == org_id)
                .order_by(Meeting.created_at.desc())
                .options(*_meeting_options())
            )
        ).scalars()
    )

    stamp = datetime.now().date().isoformat()

    if format == "json":
        payload = {
            "exported_at": datetime.now().isoformat(),
            "notes": [note_json(n, _folder_path(n.folder_id, folders)) for n in notes],
            "meetings": [meeting_json(m) for m in meetings],
        }
        body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        return _attachment(body, "meet-companion-export-" + stamp + ".json", "application/json")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        used: set = set()
        for note in notes:
            path = _folder_path(note.folder_id, folders)
            prefix = "notes/" + (path + "/" if path else "")
            name = _unique(prefix + _slug(note.title, "note"), used)
            archive.writestr(name + ".md", note_markdown(note, path))
        for meeting in meetings:
            when = meeting.started_at or meeting.created_at
            stem = _slug(meeting.title, "meeting")
            if when:
                stem = when.date().isoformat() + "-" + stem
            name = _unique("meetings/" + stem, used)
            archive.writestr(name + ".md", meeting_markdown(meeting))
        if not notes and not meetings:
            archive.writestr(
                "README.md",
                "# Meet Companion export\n\nThis workspace has no notes or meetings yet.\n",
            )
    return _attachment(buffer.getvalue(), "meet-companion-export-" + stamp + ".zip", "application/zip")
