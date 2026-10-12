"""
Health check endpoints for service and dependency monitoring.
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.database.connection import POSTGRESQL, get_db
from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """Basic liveness check."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "env": settings.APP_ENV,
    }


@router.get("/health/ready", status_code=status.HTTP_200_OK)
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """
    Readiness check verifying the database is reachable and similarity search
    is usable.

    Readiness is judged against whichever backend is actually configured: on
    SQLite similarity runs in Python and needs no extension, so a missing
    pgvector is only a problem when running on Postgres.
    """
    dialect = db.bind.dialect.name
    details = {}
    db_healthy = False
    vector_search = "unavailable"

    try:
        result = await db.execute(text("SELECT 1"))
        db_healthy = result.scalar() == 1

        if dialect == POSTGRESQL:
            extension = await db.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            )
            vector_search = "pgvector" if extension.scalar() == "vector" else "unavailable"
        else:
            vector_search = "in-process"
    except Exception as exc:
        details["error"] = str(exc)

    ready = db_healthy and vector_search != "unavailable"
    if dialect == POSTGRESQL and vector_search == "unavailable":
        details["hint"] = "Run: CREATE EXTENSION vector;"

    return {
        "status": "ready" if ready else "degraded",
        "database": "connected" if db_healthy else "disconnected",
        "dialect": dialect,
        "vector_search": vector_search,
        "details": details,
    }
