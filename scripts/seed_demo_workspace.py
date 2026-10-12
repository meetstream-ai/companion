"""
Seed a workspace full of realistic data, for testing.

Creates an owner account and a workspace on whatever database the app is
configured for (or DATABASE_URL, if set), then fills it with a year of
activity: meetings with transcripts, the memories and action items that
would have been extracted from them, and a folder tree of notes. Prints
the login and the join code at the end, so another person can ask to join.

    python scripts/seed_demo_workspace.py                       # defaults below
    python scripts/seed_demo_workspace.py --meetings 120 --notes 300
    python scripts/seed_demo_workspace.py --email me@x.test --password ... --workspace "Acme"

Deterministic: the same arguments produce the same data (seeded RNG), so a
test can be repeated. Never touches an existing account: refuses if the
email is taken.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402

from app.database.bootstrap import bootstrap  # noqa: E402
from app.database.connection import AsyncSessionLocal, current_engine, current_url  # noqa: E402
from app.models.database import (  # noqa: E402
    ActionItem,
    Meeting,
    Membership,
    Memory,
    MemoryType,
    Note,
    NotebookFolder,
    Organization,
    Participant,
    TranscriptSegment,
    User,
)
from app.security import hash_password  # noqa: E402

CUSTOMERS = ["Northwind", "Globex", "Initech", "Umbrella Health", "Vandelay Imports", "Hooli", "Stark Industries", "Wayne Logistics"]
PROJECTS = ["Onboarding revamp", "Billing migration", "Mobile app v2", "Data warehouse", "SSO rollout", "Support portal", "Pricing experiment", "Analytics dashboard"]
PEOPLE = ["Ada Lovelace", "Grace Hopper", "Linus Torvalds", "Margaret Hamilton", "Ken Thompson", "Barbara Liskov", "Dennis Ritchie", "Frances Allen", "Guido van Rossum", "Radia Perlman"]
PLATFORMS = ["google_meet", "zoom", "teams"]
MEETING_KINDS = ["Weekly sync", "Kickoff", "Design review", "Retro", "Planning", "Customer check-in", "Incident review", "Roadmap", "1:1", "Demo"]

DECISIONS = [
    "We will ship {p} behind a feature flag and turn it on for 10% of {c} first.",
    "{c} agreed to move the go-live for {p} to the end of next month.",
    "Postgres stays; the {p} team will not migrate to a document store this year.",
    "Support tickets about {p} get triaged daily at 9am instead of weekly.",
    "The {p} API will be versioned from v2 onward; v1 is frozen.",
]
COMMITMENTS = [
    "{who} will send {c} the revised {p} timeline by Friday.",
    "{who} owns the runbook for {p} and will have a draft this sprint.",
    "{who} will set up the staging environment for {p} before the next demo.",
]
CONCERNS = [
    "{c} is worried that {p} will slip if the vendor contract is not signed this week.",
    "Load on the {p} search endpoint doubled last month; nobody owns capacity planning.",
    "Two engineers on {p} are on leave in the same fortnight.",
]
FACTS = [
    "{c} has 1,400 seats on the current plan and expects 2,000 by Q4.",
    "{p} currently handles about 30k requests a day at peak.",
    "{c}'s security review requires SOC 2 evidence before {p} can go live.",
]
QUESTIONS = [
    "Who signs off on the {p} data retention policy for {c}?",
    "Does {c} need SAML or is OIDC enough for the SSO piece of {p}?",
]
TASKS = [
    "Draft the {p} rollout plan for {c}",
    "Fix the pagination bug in the {p} list view",
    "Book a follow-up with {c} about {p} pricing",
    "Write the {p} incident postmortem",
    "Update the {p} architecture diagram",
    "Get legal to review the {c} data-processing addendum",
    "Add monitoring for the {p} export job",
    "Prepare the {p} demo script for {c}",
]
LINES = [
    "Thanks everyone for joining. Let's start with where we are on {p}.",
    "Quick update from my side: the {p} build is green again after yesterday's fix.",
    "{c} asked whether we can bring the timeline forward. I said we'd look at it.",
    "I think the risk here is the vendor piece, not our own work.",
    "Can we make a decision on the flag rollout today? We've discussed it three times.",
    "Agreed. Let's go with the staged rollout and revisit in two weeks.",
    "One more thing - {c} wants a written summary after each of these calls.",
    "I'll take the action to send that. Anything else before we wrap?",
    "The numbers from last week look good, about a 12% lift on the pilot cohort.",
    "We still need someone to own the runbook. Volunteers?",
    "I can take that, but I'll need the staging environment first.",
    "Fine, let's pair on it Thursday.",
]
NOTE_BODIES = [
    "## Context\n\n{c} is mid-way through {p}. This note tracks the open threads.\n\n- Timeline slipped once already\n- Vendor contract pending\n- Pilot cohort at 12% lift\n\n## Next\n\n1. Confirm go-live date\n2. Publish runbook\n3. Schedule the demo",
    "# {p} - design notes\n\nThe current approach keeps everything in Postgres and adds a read replica for the {c} reporting load. Alternatives considered:\n\n| Option | Pros | Cons |\n|---|---|---|\n| Replica | cheap, known | lag |\n| Warehouse | fast | new system |\n\nDecision: replica for now.",
    "Ideas for {p}:\n\n- Batch the nightly export instead of per-row\n- Ask {c} for a sample of real data\n- Pre-compute the dashboard tiles\n- Cache the search facets for an hour\n\nParking lot: rename the project, nobody likes the name.",
    "# Research: how {c} uses {p} today\n\nInterviewed three people on their team. Common thread: they export to a spreadsheet every Monday because the in-app view lacks a date filter. Quick win identified.",
    "Meeting prep for {c}\n\n- Recap last decision (staged rollout)\n- Show the pilot numbers\n- Ask about SOC 2 timing\n- Confirm who signs the DPA",
]
FOLDERS = {
    "Customers": CUSTOMERS[:5],
    "Projects": PROJECTS[:5],
    "Personal": ["Ideas", "Reading", "1:1 prep"],
}


def fill(s: str, c: str, p: str, who: str = "") -> str:
    return s.format(c=c, p=p, who=who)


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--name", default="Demo Owner")
    ap.add_argument("--email", default="demo-owner@example.com")
    ap.add_argument("--password", default="demo-password-123")
    ap.add_argument("--workspace", default="Demo Co")
    ap.add_argument("--meetings", type=int, default=80)
    ap.add_argument("--notes", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    email = args.email.strip().lower()

    print(f"database: {current_url().split('@')[-1] if '@' in current_url() else current_url()}")
    await bootstrap(current_engine())

    async with AsyncSessionLocal() as db:
        if (await db.execute(select(User.id).where(User.email == email))).scalar_one_or_none():
            print(f"[ERROR] {email} already exists; pick another --email.")
            sys.exit(1)

        slug_base = args.workspace.strip().lower().replace(" ", "-")[:80] or "workspace"
        slug, n = slug_base, 1
        while (await db.execute(select(Organization.id).where(Organization.slug == slug))).scalar_one_or_none():
            n += 1
            slug = f"{slug_base}-{n}"
        org = Organization(name=args.workspace.strip(), slug=slug, mcp_token=secrets.token_urlsafe(32), join_code=secrets.token_hex(4))
        db.add(org)
        await db.flush()
        owner = User(organization_id=org.id, email=email, name=args.name, password_hash=hash_password(args.password), role="owner", is_active=True)
        db.add(owner)
        await db.flush()
        db.add(Membership(user_id=owner.id, organization_id=org.id, role="owner", status="active"))

        # Folder tree.
        folder_ids: list[uuid.UUID] = []
        for top, subs in FOLDERS.items():
            parent = NotebookFolder(organization_id=org.id, name=top)
            db.add(parent)
            await db.flush()
            folder_ids.append(parent.id)
            for sub in subs:
                child = NotebookFolder(organization_id=org.id, parent_id=parent.id, name=sub)
                db.add(child)
                await db.flush()
                folder_ids.append(child.id)

        now = datetime.now(timezone.utc)
        counts = {"meetings": 0, "segments": 0, "memories": 0, "action_items": 0, "notes": 0, "folders": len(folder_ids)}

        for i in range(args.meetings):
            c, p = rng.choice(CUSTOMERS), rng.choice(PROJECTS)
            started = now - timedelta(days=rng.randint(1, 365), hours=rng.randint(0, 9))
            attendees = rng.sample(PEOPLE, k=rng.randint(2, 5))
            memories_for = [
                (MemoryType.DECISION, fill(rng.choice(DECISIONS), c, p)),
                (MemoryType.COMMITMENT, fill(rng.choice(COMMITMENTS), c, p, attendees[0])),
                (MemoryType.CONCERN, fill(rng.choice(CONCERNS), c, p)),
                (MemoryType.FACT, fill(rng.choice(FACTS), c, p)),
            ]
            if rng.random() < 0.5:
                memories_for.append((MemoryType.UNRESOLVED_QUESTION, fill(rng.choice(QUESTIONS), c, p)))
            summary = (
                f"{rng.choice(MEETING_KINDS)} with {c} on {p}. "
                f"Decided: {memories_for[0][1]} Open concern: {memories_for[2][1]}"
            )
            meeting = Meeting(
                organization_id=org.id,
                created_by_user_id=owner.id,
                title=f"{rng.choice(MEETING_KINDS)}: {p} ({c})",
                meeting_url=f"https://meet.example.com/{secrets.token_hex(4)}",
                platform=rng.choice(PLATFORMS),
                customer_name=c,
                project_name=p,
                started_at=started,
                ended_at=started + timedelta(minutes=rng.choice([25, 30, 45, 60])),
                status="completed",
                processing_status="completed",
                summary=summary,
            )
            db.add(meeting)
            await db.flush()
            counts["meetings"] += 1

            for who in attendees:
                db.add(Participant(meeting_id=meeting.id, name=who, email=who.lower().replace(" ", ".") + "@example.com", role="attendee"))

            t = 0.0
            for k in range(rng.randint(12, 30)):
                text = fill(rng.choice(LINES), c, p)
                dur = 4 + len(text) / 12
                db.add(TranscriptSegment(meeting_id=meeting.id, speaker=rng.choice(attendees), text=text, start_time=t, end_time=t + dur, confidence=0.9, segment_index=k))
                t += dur + 0.5
                counts["segments"] += 1

            for mtype, content in memories_for:
                db.add(Memory(organization_id=org.id, meeting_id=meeting.id, type=mtype, content=content, importance=rng.randint(3, 9), speaker=rng.choice(attendees), customer_name=c, project_name=p, created_at=started))
                counts["memories"] += 1

            for _ in range(rng.randint(1, 3)):
                status = rng.choices(["open", "in_progress", "completed"], weights=[5, 2, 4])[0]
                db.add(ActionItem(
                    organization_id=org.id, meeting_id=meeting.id, owner=rng.choice(attendees),
                    task=fill(rng.choice(TASKS), c, p), status=status,
                    priority=rng.choice(["low", "medium", "high", "critical"]),
                    due_date=started + timedelta(days=rng.randint(3, 30)),
                    completed_at=(started + timedelta(days=rng.randint(1, 20))) if status == "completed" else None,
                    created_at=started,
                ))
                counts["action_items"] += 1

            # The note the pipeline files for a processed meeting.
            db.add(Note(
                organization_id=org.id, meeting_id=meeting.id, created_by_user_id=owner.id,
                title=meeting.title, note_type="meeting", tags=[c.lower().split()[0], p.lower().split()[0]],
                content=f"# {meeting.title}\n\n{summary}\n\n## Action items\n\n- " + "\n- ".join(fill(rng.choice(TASKS), c, p) for _ in range(2)),
                created_at=started,
            ))
            counts["notes"] += 1

        for i in range(args.notes):
            c, p = rng.choice(CUSTOMERS), rng.choice(PROJECTS)
            when = now - timedelta(days=rng.randint(0, 365))
            db.add(Note(
                organization_id=org.id, folder_id=rng.choice(folder_ids), created_by_user_id=owner.id,
                title=f"{p} - {rng.choice(['notes', 'plan', 'ideas', 'research', 'prep'])} ({c})",
                content=fill(rng.choice(NOTE_BODIES), c, p),
                note_type=rng.choice(["note", "idea", "research"]),
                tags=[c.lower().split()[0], p.lower().split()[0]],
                is_favorite=rng.random() < 0.1,
                created_at=when, updated_at=when,
            ))
            counts["notes"] += 1

        await db.commit()

    print("\nSeeded workspace")
    print(f"  workspace : {args.workspace}")
    print(f"  join code : {org.join_code}")
    print(f"  login     : {email} / {args.password}")
    print("  data      : " + ", ".join(f"{v} {k}" for k, v in counts.items()))


if __name__ == "__main__":
    asyncio.run(main())
