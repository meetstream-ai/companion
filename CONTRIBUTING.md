# Contributing

Thanks for your interest. Issues, questions, and pull requests are all welcome.

## Database migrations

Schema is managed with [Alembic](https://alembic.sqlalchemy.org). You normally
do nothing: the app runs `alembic upgrade head` at startup against whatever
database it is configured for (SQLite or Postgres), a fresh database is built
from the baseline, and an older one created before Alembic is adopted and
stamped automatically.

When you change a model in `app/models/database.py`, add a revision:

```bash
alembic revision --autogenerate -m "what changed"
```

Review the generated file in `app/migrations/versions/` (autogenerate is a
draft, not gospel - check it, especially for renames and server defaults), then
`alembic upgrade head` to apply it locally. `tests/test_migrations.py` fails if
the models drift from the migrations, so CI catches a forgotten revision.

## Getting set up

Requirements: **Python 3.12**, **Node 22**, and optionally Docker (for Postgres).

```bash
git clone https://github.com/ThalhaAhamed/MeetCompanion.git
cd MeetCompanion
python -m venv .venv
.venv/Scripts/activate            # macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt
npm --prefix frontend install
```

Run both servers with one command (or the two underneath in separate terminals):

```bash
python scripts/dev.py              # API on :8000 with reload, UI on :3000
```

```bash
python -m uvicorn app.main:app --port 8000 --reload
npm --prefix frontend run dev      # http://localhost:3000, proxies /api to :8000
```

No `.env` is needed - first run walks you through configuration. Use Ollama or
any provider key you have; SQLite is the default database.

## Where things live

| Area | Path |
| --- | --- |
| HTTP endpoints | `app/api/` (one router per UI page) |
| Business logic | `app/services/` (processing pipeline, notes, extraction) |
| LLM adapters | `app/providers/llm/` - one file per vendor plus a registry entry |
| Search backends | `app/providers/database/` - pgvector vs. portable numpy |
| ORM models and schema patches | `app/models/database.py`, `app/database/bootstrap.py` |
| MCP tools for the voice agent | `app/mcp/tools.py` |
| Web UI | `frontend/src/pages/` and `frontend/src/components/` |
| Desktop shell | `desktop/` |

`docs/architecture.md` explains the layering and the reasons behind it.

## Before opening a pull request

```bash
python -m pytest              # runs on a throwaway SQLite file, no network
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
```

CI runs the same suite against SQLite and Postgres (pgvector), builds the
Docker image, and lints and builds the UI.

- Keep pull requests focused. One behaviour change per PR is ideal.
- Add or update tests for behaviour you change. Tests use the `authed_client`
  fixture for signed-in requests; see `tests/conftest.py`.
- Schema changes go in `app/models/database.py` **and** an Alembic revision
  (see *Database migrations* above). Never as a patch in `bootstrap.py`.
- Every route that changes data takes a permission dependency -
  `dependencies=[Depends(perms.require("edit_content"))]` etc. - see
  `app/permissions.py` for the six keys. Owners always pass.
- Never log or return a secret in full. `app/runtime_config.py` masks them.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `ci:` ...).

## Adding an LLM provider

1. Copy `app/providers/llm/ollama.py` (the smallest adapter).
2. Implement `_complete()` and `health_check()`.
3. Register it in `app/providers/llm/__init__.py` with the fields the setup
   form should show.
4. Add a case to `tests/test_llm_providers.py`.

## Reporting security issues

See [SECURITY.md](SECURITY.md). Please don't file public issues for those.
