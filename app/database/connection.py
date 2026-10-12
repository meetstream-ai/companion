"""
Database connection and session management.

Engine construction is dialect-aware: SQLite and Postgres need different
pooling and connection arguments, and SQLite additionally needs foreign key
enforcement turned on explicitly.
"""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Dict

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.runtime_config import is_env_managed, load_config

SQLITE = "sqlite"
POSTGRESQL = "postgresql"


def normalize_database_url(url: str) -> str:
    """
    Ensure the URL names an async driver.

    Users naturally write `sqlite:///app.db` or `postgresql://...` from other
    tooling; both are silently upgraded rather than failing with an opaque
    "does not support async" error.
    """
    if url.startswith("sqlite+"):
        return url
    if url.startswith("sqlite:"):
        return url.replace("sqlite:", "sqlite+aiosqlite:", 1)
    if url.startswith("postgresql+"):
        return _asyncpg_query(url)
    if url.startswith(("postgresql:", "postgres:")):
        scheme, _, rest = url.partition(":")
        return _asyncpg_query(f"postgresql+asyncpg:{rest}")
    return url


#: libpq parameters asyncpg has no equivalent for. Neon's dashboard string
#: carries `channel_binding=require`; SQLAlchemy hands every query parameter
#: to asyncpg.connect() as a keyword, which then fails with "unexpected
#: keyword argument". SSL is already required on those hosts, so dropping
#: these loses nothing.
_LIBPQ_ONLY_PARAMS = frozenset({"channel_binding", "gssencmode", "sslcompression", "sslsni", "krbsrvname"})


def _asyncpg_query(url: str) -> str:
    """Rewrite a Postgres URL's query string into what asyncpg accepts."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    if not parts.query:
        return url
    params = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "sslmode":
            # asyncpg reads `ssl`, and understands libpq's mode names.
            key = "ssl"
        if key in _LIBPQ_ONLY_PARAMS:
            continue
        params.append((key, value))
    return urlunsplit(parts._replace(query=urlencode(params)))


def dialect_of(url: str) -> str:
    if url.startswith(SQLITE):
        return SQLITE
    if url.startswith(("postgresql", "postgres")):
        return POSTGRESQL
    return url.split(":", 1)[0]


def _sqlite_file_path(url: str) -> str:
    path = url.split(":///", 1)[-1].split("?", 1)[0]
    return path


def _engine_options(url: str) -> Dict[str, Any]:
    options: Dict[str, Any] = {
        "echo": settings.LOG_LEVEL.upper() == "DEBUG",
        "future": True,
    }

    if dialect_of(url) == SQLITE:
        # SQLite has no server to pool against, and the default pool arguments
        # below are rejected outright by its dialect.
        file_path = _sqlite_file_path(url)
        if file_path and file_path != ":memory:":
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        return options

    options.update(pool_pre_ping=True, pool_size=10, max_overflow=20)
    return options


def resolve_database_url() -> str:
    """
    Process environment first, then the URL saved from the UI, then the
    .env file / SQLite default - the same precedence as every other setting.
    """
    if is_env_managed("DATABASE_URL"):
        return normalize_database_url(settings.DATABASE_URL)
    stored = load_config().database.url
    if stored:
        return normalize_database_url(stored)
    return normalize_database_url(settings.DATABASE_URL)


class DatabaseRuntime:
    """One engine plus its session factory; replaced wholesale on switch."""

    def __init__(self, url: str):
        self.url = url
        self.dialect = dialect_of(url)
        self.engine = create_async_engine(url, **_engine_options(url))
        if self.dialect == SQLITE:
            event.listens_for(self.engine.sync_engine, "connect")(_enable_sqlite_foreign_keys)
        self.sessionmaker = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    # SQLite ignores foreign keys unless asked, which would let the
    # ON DELETE CASCADE rules the schema relies on silently do nothing.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


_runtime = DatabaseRuntime(resolve_database_url())

# Kept for callers that only need to know what was configured at import
# time (scripts, tests). Live code should use the accessors below.
DATABASE_URL = _runtime.url
DIALECT = _runtime.dialect


def current_engine():
    return _runtime.engine


def current_url() -> str:
    return _runtime.url


def current_dialect() -> str:
    return _runtime.dialect


def AsyncSessionLocal() -> AsyncSession:  # noqa: N802 - long-standing name
    """A session on whichever database is active right now."""
    return _runtime.sessionmaker()


async def switch_database(url: str) -> str:
    """
    Point the running application at a different database, without restart.

    The new engine is built and bootstrapped (schema, default workspace)
    before anything is swapped, so a URL that turns out to be unreachable or
    unwritable leaves the current database untouched. Requests already
    holding a session finish on the old engine; it is disposed afterwards.
    """
    from app.database.bootstrap import bootstrap

    global _runtime
    url = normalize_database_url(url)
    if url == _runtime.url:
        return url

    candidate = DatabaseRuntime(url)
    try:
        await bootstrap(candidate.engine)
    except Exception:
        await candidate.engine.dispose()
        raise

    previous, _runtime = _runtime, candidate
    await previous.engine.dispose()
    return url


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI endpoints to acquire a database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for background workers to acquire a database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_connection() -> bool:
    try:
        async with current_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
