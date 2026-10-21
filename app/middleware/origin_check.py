"""
Refuse state-changing requests that a browser sent from another site.

SameSite=Lax on the session cookie is the main defence: the browser does not
send it with a POST another site starts. This covers what Lax does not: a UI
on another origin (CORS_ORIGINS, where the cookie is SameSite=None) and
sibling subdomains, which count as the same site.

Browsers say where a request came from in Sec-Fetch-Site, and a page cannot
set or change it. Proxies leave it alone, unlike Host, which nginx rewrites by
default. A POST, PUT, PATCH or DELETE marked cross-site or same-site is
refused unless its Origin is in CORS_ORIGINS. No header means no browser page
started it (curl, MCP clients, MeetStream's webhooks, older browsers), and it
passes.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: The page's own origin, or the person typed the address / used a bookmark.
TRUSTED_FETCH_SITES = frozenset({"same-origin", "none"})


def _configured_origins() -> set[str]:
    from app.config import settings

    return {o.strip().rstrip("/").lower() for o in settings.CORS_ORIGINS or [] if o and o.strip()}


def serves_cross_origin_ui() -> bool:
    """Whether CORS_ORIGINS names a UI that calls this server from elsewhere."""
    return bool(_configured_origins())


def request_allowed(request: Request) -> bool:
    if request.method not in STATE_CHANGING:
        return True
    site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    if not site or site in TRUSTED_FETCH_SITES:
        return True
    origin = (request.headers.get("origin") or "").strip().rstrip("/").lower()
    return bool(origin) and origin in _configured_origins()


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not request_allowed(request):
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-site request refused. Add the site to CORS_ORIGINS if it is your UI."},
            )
        return await call_next(request)
