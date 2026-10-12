"""
Knowledge Graph Endpoint.
Derives a nodes/edges graph from data already stored - meetings, participants,
memories, and action items - without any new extraction pipeline. See
frontend/src/Graph.jsx for the force-directed rendering.
"""
import uuid
from typing import Any, Dict, List
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.database.connection import get_db
from app.api.deps import get_current_org_id
from app.models.database import Meeting
from app.models.schemas import utc_iso

router = APIRouter(prefix="/api/graph", tags=["graph"])


def _person_id(name: str) -> str:
    return f"person:{name.strip().lower()}"


@router.get("")
async def get_knowledge_graph(org_id: uuid.UUID = Depends(get_current_org_id), db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Meeting)
        .where(Meeting.organization_id == org_id)
        .options(
            selectinload(Meeting.participants),
            selectinload(Meeting.memories),
            selectinload(Meeting.action_items),
        )
    )
    result = await db.execute(stmt)
    meetings = result.scalars().all()

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, str]] = []

    def add_node(node_id: str, **attrs):
        if node_id not in nodes:
            nodes[node_id] = {"id": node_id, **attrs}
        return node_id

    def add_person(name: str) -> str:
        pid = _person_id(name)
        add_node(pid, label=name.strip(), type="person")
        return pid

    for m in meetings:
        # No transcript/memories/participants at all means nothing to
        # connect - skip rather than adding an isolated, contentless node
        # that just clutters the graph.
        if not m.participants and not m.memories and not m.action_items:
            continue

        mid = f"meeting:{m.id}"
        add_node(
            mid,
            label=m.title or "Untitled meeting",
            type="meeting",
            date=utc_iso(m.started_at),
            platform=m.platform,
            status=m.status,
            summary=m.summary,
            meeting_id=str(m.id),
        )

        if m.customer_name:
            cid = add_node(f"customer:{m.customer_name.lower()}", label=m.customer_name, type="customer")
            edges.append({"source": mid, "target": cid, "type": "for_customer"})
        if m.project_name:
            pjid = add_node(f"project:{m.project_name.lower()}", label=m.project_name, type="project")
            edges.append({"source": mid, "target": pjid, "type": "for_project"})

        for p in m.participants:
            if not p.name:
                continue
            pid = add_person(p.name)
            edges.append({"source": pid, "target": mid, "type": "participated_in"})

        for mem in m.memories:
            memid = f"memory:{mem.id}"
            add_node(
                memid,
                label=(mem.content or "")[:80],
                content=mem.content,
                type="memory",
                memory_type=mem.type.value if mem.type else None,
                speaker=mem.speaker,
                meeting_id=str(m.id),
                meeting_title=m.title,
            )
            edges.append({"source": mid, "target": memid, "type": "produced"})
            if mem.speaker:
                pid = add_person(mem.speaker)
                edges.append({"source": pid, "target": memid, "type": "said"})

        for a in m.action_items:
            aid = f"action:{a.id}"
            add_node(
                aid,
                label=a.task[:80],
                task=a.task,
                type="action_item",
                status=a.status,
                owner=a.owner,
                due_date=a.due_date.isoformat() if a.due_date else None,
                priority=a.priority,
                meeting_id=str(m.id),
                meeting_title=m.title,
            )
            edges.append({"source": mid, "target": aid, "type": "produced"})
            if a.owner:
                pid = add_person(a.owner)
                edges.append({"source": pid, "target": aid, "type": "owns"})

    return {"nodes": list(nodes.values()), "edges": edges}
