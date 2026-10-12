# Meet Companion web UI

React 19 + Vite + Tailwind v4. Talks to the FastAPI server through `/api`,
which the Vite dev server proxies to `http://localhost:8000`.

```bash
npm install
npm run dev      # http://localhost:3000
npm run lint     # oxlint
npm test         # vitest + testing-library
npm run build    # -> dist/, which the API server serves when present
```

- `src/pages/` - one component per screen, each fetching its own data.
- `src/components/` - shared UI (`ui.jsx`), Markdown rendering, the provider
  and database forms.
- `src/api.js` - every server call in one place.
- `src/user.js` - the signed-in member; used only to hide controls the server
  would refuse anyway.

See the repository README for the full picture.
