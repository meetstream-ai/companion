# For developers

Requires **Python 3.12** (3.13+ is not yet supported by every dependency) and **Node 22**.

```bash
git clone https://github.com/ThalhaAhamed/MeetCompanion.git
cd MeetCompanion

py -3.12 -m venv .venv        # Windows  (python3.12 -m venv .venv on macOS / Linux)
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -r requirements.txt
npm --prefix frontend install
```

> Use the 3.12 launcher explicitly: a bare `python -m venv` picks whatever
> `python` is on your PATH, and on a machine where that is 3.13 or 3.14 the
> venv is silently wrong.

Run both with one command:

```bash
.venv/Scripts/python scripts/dev.py       # API on :8000 (auto-reload) + UI on :3000
```

Or separately, in two terminals:

```bash
.venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload
```

```bash
npm --prefix frontend run dev
```

Open <http://localhost:3000>. No `.env` is required — first run walks you
through setup.

> The API serves the built UI from `frontend/dist` only if it exists when the
> server starts. In development you use Vite on :3000 (above) and don't need
> it; for a single-process deployment, run `npm --prefix frontend run build`
> **before** starting the server.

**Fully offline:** install [Ollama](https://ollama.com), `ollama pull llama3.1`,
and pick *Ollama (local)* during setup.

**PostgreSQL:** `docker compose --profile postgres up -d postgres`, then pick it
in Settings (or set `DATABASE_URL`). Schema, indexes and the pgvector extension
are created automatically.

**Tests and lint:**

```bash
.venv/Scripts/python -m pytest          # hermetic: throwaway SQLite, no network
npm --prefix frontend run lint
npm --prefix frontend test
```

### Building the desktop app

```bash
npm --prefix frontend run build                                        # UI  -> frontend/dist
pip install pyinstaller
pyinstaller desktop/server.spec --noconfirm --distpath desktop/build --workpath desktop/work
npm --prefix desktop install
npm --prefix desktop run dist                                          # -> desktop/release/
```

`npm --prefix desktop start` runs the shell against the frozen server without
packaging. Set `MEET_COMPANION_DATA_DIR` to point it at an existing workspace.
Releases for all three platforms are built by
[`.github/workflows/release.yml`](../.github/workflows/release.yml) on a `v*` tag.

## Tech stack

| Layer | What | Why |
|---|---|---|
| **Backend** | Python 3.12 · [FastAPI](https://fastapi.tiangolo.com) · Uvicorn · Pydantic v2 | Async end to end; the request schemas double as the API contract. |
| **Data** | SQLAlchemy 2 (async) · Alembic migrations · SQLite via `aiosqlite` · PostgreSQL via `asyncpg` + [pgvector](https://github.com/pgvector/pgvector) | One ORM model runs on a local file or a hosted Postgres; migrations run themselves at startup. |
| **Embeddings** | [fastembed](https://github.com/qdrant/fastembed) running `all-MiniLM-L6-v2` on ONNX Runtime | Same vectors as the PyTorch model without a multi-gigabyte torch dependency; computed locally, never sent anywhere. |
| **LLMs** | Adapters over `httpx` for OpenAI, Anthropic, Gemini, Groq, xAI, Ollama and any OpenAI-compatible endpoint | No vendor SDKs — one small file per provider, so adding one is an afternoon. |
| **Meeting capture** | [MeetStream](https://meetstream.ai) bots, webhooks (HMAC-signed) and a built-in [MCP](https://modelcontextprotocol.io) server | The in-call agent's memory lookups are ordinary MCP tool calls against this app. |
| **Documents** | `pypdf`, `.docx` read as XML, `langchain-text-splitters` for chunking | Reference material for Ask AI without a heavyweight document pipeline. |
| **Frontend** | [React 19](https://react.dev) · [Vite 8](https://vite.dev) · [Tailwind CSS 4](https://tailwindcss.com) · React Router 7 · `marked` for Markdown | Small, fast, no component framework; the knowledge graph is a hand-written force simulation on SVG. |
| **Desktop** | [Electron 33](https://www.electronjs.org) shell around a [PyInstaller](https://pyinstaller.org)-frozen server | Windows, macOS and Linux installers from one codebase; the shell signs itself in with a per-machine device key. |
| **Security** | `bcrypt` passwords · HMAC-signed session cookies · per-workspace MCP bearer tokens · rate-limited sign-in | Nothing custom where a standard primitive exists. |
| **Tooling** | pytest (SQLite *and* Postgres in CI) · vitest · oxlint · pip-audit · GitHub Actions for CI and multi-platform releases | 230+ tests; the Docker image is built and booted on every push. |

**The desktop app is the web app.** An Electron shell starts the bundled server
on a free localhost port and opens it in a window. Embeddings run through ONNX
(`all-MiniLM-L6-v2`), which is what keeps the download at a sane size.

The full write-up is in [docs/architecture.md](architecture.md).
