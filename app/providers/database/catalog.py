"""
The database providers a user can pick from, and how their form fields
become a SQLAlchemy URL.

Everything hosted here is PostgreSQL underneath (Supabase, Neon, Railway and
friends all hand you a Postgres connection string), so the catalog is mostly
about meeting people where they are: a local file, a server they run
themselves, or a string they copied from a dashboard. Engines the app has
not been verified against are listed as coming soon rather than hidden, so
the roadmap is visible without promising something that does not work.
"""
from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import quote

from app.database.connection import normalize_database_url

DEFAULT_SQLITE_PATH = "data/meet-companion.db"

_URL_FIELD = {
    "key": "url",
    "label": "Connection string",
    "type": "password",
    "required": True,
    "placeholder": "postgresql://user:password@host:5432/database",
    "help": "Stored in your local configuration and never sent anywhere else.",
}

_SERVER_FIELDS = [
    {"key": "host", "label": "Host", "type": "text", "required": True, "placeholder": "localhost"},
    {"key": "port", "label": "Port", "type": "text", "required": False, "default": "5432"},
    {"key": "database", "label": "Database", "type": "text", "required": True, "placeholder": "meet_companion"},
    {"key": "user", "label": "User", "type": "text", "required": True},
    {"key": "password", "label": "Password", "type": "password", "required": False},
    {
        "key": "sslmode",
        "label": "SSL",
        "type": "select",
        "required": False,
        "default": "prefer",
        "options": ["disable", "prefer", "require"],
    },
]

CATALOG: List[Dict[str, Any]] = [
    {
        "name": "sqlite",
        "label": "Local SQLite",
        "badge": "DB",
        "summary": "Everything in one file on this machine. No server, nothing to install.",
        "dialect": "sqlite",
        "recommended": True,
        "available": True,
        "fields": [
            {
                "key": "path",
                "label": "Database file",
                "type": "text",
                "required": False,
                "default": DEFAULT_SQLITE_PATH,
                "help": "Relative paths are resolved against the project directory.",
            }
        ],
    },
    {
        "name": "postgresql",
        "label": "PostgreSQL",
        "badge": "PG",
        "summary": "A server you run yourself. pgvector is enabled automatically if permitted.",
        "dialect": "postgresql",
        "recommended": False,
        "available": True,
        "fields": _SERVER_FIELDS,
    },
    {
        "name": "supabase",
        "label": "Supabase",
        "badge": "SB",
        "summary": "Hosted Postgres with pgvector built in. Paste the connection string from Project settings.",
        "dialect": "postgresql",
        "recommended": False,
        "available": True,
        "fields": [{**_URL_FIELD, "placeholder": "postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:5432/postgres"}],
    },
    {
        "name": "neon",
        "label": "Neon",
        "badge": "NE",
        "summary": "Serverless Postgres. Paste the connection string from the Neon dashboard.",
        "dialect": "postgresql",
        "recommended": False,
        "available": True,
        "fields": [{**_URL_FIELD, "placeholder": "postgresql://user:password@ep-....neon.tech/neondb?sslmode=require"}],
    },
    {
        "name": "railway",
        "label": "Railway Postgres",
        "badge": "RW",
        "summary": "Paste the public DATABASE_URL from your Railway Postgres service.",
        "dialect": "postgresql",
        "recommended": False,
        "available": True,
        "fields": [{**_URL_FIELD, "placeholder": "postgresql://postgres:password@host.proxy.rlwy.net:12345/railway"}],
    },
    {
        "name": "postgres-url",
        "label": "Other PostgreSQL",
        "badge": "URL",
        "summary": "Any other Postgres host - RDS, Cloud SQL, Azure, DigitalOcean - via its connection string.",
        "dialect": "postgresql",
        "recommended": False,
        "available": True,
        "fields": [_URL_FIELD],
    },
    {
        "name": "mysql",
        "label": "MySQL / MariaDB",
        "badge": "MY",
        "summary": "Not verified yet.",
        "dialect": "mysql",
        "recommended": False,
        "available": False,
    },
    {
        "name": "mongodb",
        "label": "MongoDB",
        "badge": "MG",
        "summary": "Not verified yet.",
        "dialect": "mongodb",
        "recommended": False,
        "available": False,
    },
]

_BY_NAME = {entry["name"]: entry for entry in CATALOG}


def describe_databases() -> List[Dict[str, Any]]:
    """Serializable catalog for the onboarding and settings forms."""
    return CATALOG


def build_database_url(provider: str, values: Dict[str, Any] | None) -> str:
    """
    Turn a provider choice plus its form values into a normalized URL.

    Raises ValueError with a message fit to show the user.
    """
    values = {k: (str(v).strip() if v is not None else "") for k, v in (values or {}).items()}
    entry = _BY_NAME.get(provider)
    if entry is None:
        raise ValueError(f"Unknown database provider '{provider}'.")
    if not entry["available"]:
        raise ValueError(f"{entry['label']} is not supported yet.")

    if provider == "sqlite":
        path = values.get("path") or DEFAULT_SQLITE_PATH
        return f"sqlite+aiosqlite:///{path}"

    if provider == "postgresql":
        missing = [f["label"] for f in _SERVER_FIELDS if f["required"] and not values.get(f["key"])]
        if missing:
            raise ValueError(f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} required.")
        port = values.get("port") or "5432"
        if not port.isdigit():
            raise ValueError("Port must be a number.")
        auth = quote(values["user"], safe="")
        if values.get("password"):
            auth += ":" + quote(values["password"], safe="")
        url = f"postgresql+asyncpg://{auth}@{values['host']}:{port}/{quote(values['database'], safe='')}"
        sslmode = values.get("sslmode") or "prefer"
        # asyncpg reads `ssl`, not libpq's `sslmode`.
        if sslmode == "require":
            url += "?ssl=require"
        elif sslmode == "disable":
            url += "?ssl=disable"
        return url

    url = values.get("url")
    if not url:
        raise ValueError("A connection string is required.")
    if not url.startswith(("postgres://", "postgresql://", "postgresql+")):
        raise ValueError("Expected a PostgreSQL connection string starting with postgresql://.")
    return normalize_database_url(url)


def provider_for_url(url: str | None) -> str:
    """Best guess at which catalog entry a stored URL came from."""
    if not url or url.startswith("sqlite"):
        return "sqlite"
    if "supabase.co" in url or "supabase.com" in url:
        return "supabase"
    if "neon.tech" in url:
        return "neon"
    if "rlwy.net" in url or "railway" in url:
        return "railway"
    return "postgres-url"
