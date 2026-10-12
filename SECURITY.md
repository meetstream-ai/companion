# Security policy

## Reporting a vulnerability

Please do **not** open a public issue for security problems.

Email **thalhaahamedt@gmail.com** with a description, steps to reproduce, and
the version or commit you tested. You will get an acknowledgement within a few
days. Fixes are released as soon as they are ready and credited in the release
notes unless you prefer otherwise.

## What is in scope

- The API server (`app/`), the web UI (`frontend/`), the desktop shell
  (`desktop/`), the MCP tool server (`/mcp`) and the webhook receiver.
- The default configuration produced by first-run onboarding.

## Deployment model and trust boundaries

Meet Companion is designed to be self-hosted by one team. Understand these
boundaries before exposing an instance beyond localhost:

- **Workspace owners are trusted with the whole server.** The AI provider,
  database, MeetStream credentials and the agent template are server-wide
  settings; changing them requires the `owner` role. The person who creates a
  workspace is its owner and can promote others.
- **Members of a workspace see all of that workspace's meetings, notes and
  action items.** There is no per-note sharing.
- **Anyone who can reach the server can create a new workspace** (sign-up is
  open) unless you put it behind your own authentication proxy. A new workspace
  never sees another workspace's data.
- **The in-call voice agent has write tools** (add notes, create and update
  action items) scoped to its workspace, driven by what is said in the meeting.
  Treat what participants say as untrusted input to those tools - or switch
  them off (Settings → Meetings → *In-call agent permissions*, owners only)
  to keep the agent read-only.
- **Transcripts are sent to the LLM provider you choose.** With a hosted
  provider that means the vendor receives the full text of your meetings.

## Hardening checklist

- Run behind HTTPS; the session cookie is marked `Secure`.
- Set `CORS_ORIGINS` to the exact origin of your UI (or leave it empty when the
  server serves the UI itself).
- Set `MEETSTREAM_WEBHOOK_SECRET` (Settings → Meetings, or the environment) so
  webhook deliveries are signature-checked.
- Keep the generated `data/session.key` private; rotating it signs everyone out.
- Bind to `127.0.0.1` (the default) unless the server is meant to be reachable.
- Behind a reverse proxy, set `TRUST_PROXY=true` so rate limiting sees real
  client addresses; never set it when clients connect directly.
- Leave `API_DOCS` off in production (the default outside development).
