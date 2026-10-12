# Security and privacy

## Privacy and data

Everything is stored in the database you choose (SQLite file by default):
account emails and password hashes, meeting metadata, full transcripts with
speaker names, extracted memories and action items, notes, and uploaded
documents. Embeddings are computed locally and never leave the machine.

What leaves the machine, and only when you enable it:

- **Your LLM provider** receives the full transcript of each processed meeting
  and excerpts of your notes when you use Ask AI. With Ollama, nothing leaves.
- **MeetStream** hosts the bot, the audio and the transcription, and stores the
  agent configuration including this server's MCP token.
- **Hugging Face** serves a one-time download of the embedding model.

API keys are stored in plaintext: server-wide ones in `data/config.json`,
per-member MeetStream keys in the `users.settings` column of the database. Protect the `data` directory the way you
would protect a `.env` file. There is no telemetry.

## Security model

- Every meeting, note and action item belongs to a **workspace**; members of a
  workspace share all of it and never see other workspaces.
- The person who creates a workspace is its **owner**. Owners can change the
  server-wide settings (AI provider, database, MeetStream, agent template),
  reset teammates' passwords, promote other owners and remove members. Members
  can use everything else.
- **Sign-up is open** to anyone who can reach the server (new workspace or
  join by code). Put the server behind your own auth proxy if that is not
  what you want.
- The in-call agent's MCP tools are authenticated with a per-workspace bearer
  token generated on creation. Its write tools (notes, action items) act on
  what people say in the meeting; owners can switch them off to keep the
  agent read-only.

Details and a hardening checklist: [SECURITY.md](../SECURITY.md).

## Signing in

The desktop app signs you in automatically. On first run the server writes a
`device.key` into its data directory; the app reads it and presents it, which
is proof the request comes from this machine rather than from someone who
found your tunnel. Reaching the same server from a phone or over a tunnel
still asks for the password, so exposing the server never exposes your
meetings.

Auto sign-in deliberately applies only when the install has exactly one owner.
On a shared workspace "the local user" is ambiguous, and quietly picking one
person would hand over someone else's role.

Locked out of the only owner account? Nobody can reset it from inside the app,
so run this where the server lives:

```bash
python scripts/reset_password.py --list          # see the accounts
python scripts/reset_password.py you@example.com # set a new password
```
