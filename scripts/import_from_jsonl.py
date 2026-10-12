"""
Load a workspace exported as JSONL into the local database.

Companion to scripts/export_via_railway.sh, for the case where the source
database has no route this machine can reach and the rows had to come out
through a tunnel as JSON.

    python -m scripts.import_from_jsonl --source exports/

Values are coerced back from JSON using each column's declared type, so there
is no per-table mapping to maintain: uuids, timestamps, enums and pgvector
columns are all recognised from the model definition. Re-running is safe -
rows already present by primary key are skipped.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import Date, DateTime, Enum as SQLEnum, inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.connection import normalize_database_url
from app.models.database import (
    ActionItem,
    Base,
    CompanyKnowledgeEmbedding,
    Meeting,
    MeetingMemoryEmbedding,
    Memory,
    Organization,
    Participant,
    ProcessingJob,
    TranscriptSegment,
    User,
)
from app.models.types import GUID, Embedding, GUIDArray

#: Ordered so foreign keys always resolve.
TABLES = [
    ("organizations", Organization),
    ("users", User),
    ("meetings", Meeting),
    ("participants", Participant),
    ("transcript_segments", TranscriptSegment),
    ("memories", Memory),
    ("action_items", ActionItem),
    ("meeting_memory_embeddings", MeetingMemoryEmbedding),
    ("company_knowledge_embeddings", CompanyKnowledgeEmbedding),
    ("processing_jobs", ProcessingJob),
]


def parse_vector(value: Any) -> Optional[List[float]]:
    """pgvector renders as a bracketed string once it passes through row_to_json."""
    if value is None:
        return None
    if isinstance(value, list):
        return [float(v) for v in value]
    text = str(value).strip().strip("[]")
    return [float(part) for part in text.split(",")] if text else []


def parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def coerce_row(model, raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Rebuild a model's keyword arguments from one exported JSON object.

    Keys are matched on database column name rather than attribute name,
    because that is what the export contains - Memory.metadata_ arrives as
    "metadata", for instance.
    """
    values: Dict[str, Any] = {}

    for attr in sa_inspect(model).mapper.column_attrs:
        column = attr.columns[0]
        if column.name not in raw:
            continue

        value = raw[column.name]
        if value is None:
            values[attr.key] = None
            continue

        column_type = column.type
        if isinstance(column_type, GUID):
            value = uuid.UUID(str(value))
        elif isinstance(column_type, GUIDArray):
            value = [uuid.UUID(str(item)) for item in value]
        elif isinstance(column_type, Embedding):
            value = parse_vector(value)
        elif isinstance(column_type, DateTime):
            value = parse_timestamp(value)
        elif isinstance(column_type, Date):
            value = date.fromisoformat(str(value)) if not isinstance(value, date) else value
        elif isinstance(column_type, SQLEnum) and column_type.enum_class is not None:
            value = column_type.enum_class(value)

        values[attr.key] = value

    return values


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path.name} line {number} is not valid JSON: {exc}")
    return rows


def ensure_sqlite_directory(url: str) -> None:
    """A SQLite file cannot be created inside a directory that does not exist."""
    if not url.startswith("sqlite"):
        return
    path = url.split(":///", 1)[-1].split("?", 1)[0]
    if path and path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)


async def run(source_dir: Path, target_url: str, dry_run: bool) -> None:
    target_url = normalize_database_url(target_url)
    ensure_sqlite_directory(target_url)
    engine = create_async_engine(target_url)
    Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    try:
        payload = [(name, model, read_jsonl(source_dir / f"{name}.jsonl")) for name, model in TABLES]

        print(f"Source: {source_dir}")
        for name, _model, rows in payload:
            if rows:
                print(f"  {name:<32} {len(rows):>6}")

        # Checked before touching the database at all: a dry run that creates
        # a schema on the target is not a dry run.
        if dry_run:
            print(f"\nTarget would be: {target_url}")
            print("Dry run - nothing written.")
            return

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        print()
        async with Session() as session:
            for name, model, rows in payload:
                if not rows:
                    continue
                present = set((await session.execute(select(model.id))).scalars().all())

                added = 0
                for raw in rows:
                    data = coerce_row(model, raw)
                    if data.get("id") in present:
                        continue
                    session.add(model(**data))
                    added += 1

                # Flushed per table so a failure names where it happened.
                await session.flush()
                skipped = len(rows) - added
                note = f"  ({skipped} already present)" if skipped else ""
                print(f"  {name:<32} {added:>6} imported{note}")

            await session.commit()

        print(f"\nTarget: {target_url}")
    finally:
        await engine.dispose()


def main() -> None:
    from app.config import settings

    parser = argparse.ArgumentParser(description="Load a JSONL workspace export into the local database.")
    parser.add_argument("--source", required=True, type=Path, help="Directory containing <table>.jsonl files.")
    parser.add_argument("--target", default=settings.DATABASE_URL, help="Destination URL (defaults to DATABASE_URL).")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be imported without writing.")
    args = parser.parse_args()

    if not args.source.is_dir():
        raise SystemExit(f"{args.source} is not a directory.")

    asyncio.run(run(args.source, args.target, args.dry_run))


if __name__ == "__main__":
    main()
