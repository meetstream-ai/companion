"""
Refuse state-changing requests that a browser sent from another site.

The session cookie goes with any request the browser makes to this server,
including one a page on another site fires with fetch(..., {mode:
"no-cors"}). JSON routes are safe from that (it cannot send a JSON content
type), but a POST with no body is not: /api/setup/reset, a new join code,
stopping a bot. Browsers name the page that started a request in Origin, so
a POST, PUT, PATCH or DELETE whose Origin is neither this server nor a
configured CORS origin is refused.

No Origin means no browser page started it - curl, MCP clients, MeetStream's
webhooks - and those carry no ambient cookie to abuse, so they pass.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_DEFAULT_PORTS = {"http": "80", "https": "443"}


def _host_of_origin(origin: str) -> str | None:
    """'https://Example.com:443' -> 'example.com'; None for 'null' or junk."""
    try:
        parts = urlsplit(origin.strip())
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in _DEFAULT_PORTS or not host:
        return None
    if ":" in host:
        host = f"[{host}]"
    if port is not None and str(port) != _DEFAULT_PORTS[parts.scheme]:
        return f"{host}:{port}"
    return host


def own_host(request: Request) -> str:
    """
    The host the browser used to reach this server. Behind a trusted proxy
    that is X-Forwarded-Host when the proxy sets it; the scheme is left out
    on purpose, since a TLS-terminating proxy makes every request look like
    plain http unless TRUST_PROXY is on.
    """
    from app.config import settings

    host = ""
    if settings.TRUST_PROXY:
        host = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    host = (host or request.headers.get("host") or "").lower()
    for default in (":80", ":443"):
        if host.endswith(default):
            host = host[: -len(default)]
    return host


def _configured_origins() -> set[str]:
    from app.config import settings

    return {o.strip().rstrip("/").lower() for o in settings.CORS_ORIGINS or [] if o and o.strip()}


def is_own_origin(request: Request, origin: str) -> bool:
    host = _host_of_origin(origin)
    return host is not None and host == own_host(request)


def origin_allowed(request: Request, origin: str) -> bool:
    return is_own_origin(request, origin) or origin.strip().rstrip("/").lower() in _configured_origins()


def serves_cross_origin_ui(request: Request) -> bool:
    """Whether CORS_ORIGINS names a UI on another origin than this server."""
    return any(not is_own_origin(request, origin) for origin in _configured_origins())


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in STATE_CHANGING:
            origin = request.headers.get("origin")
            if origin is not None and not origin_allowed(request, origin):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-site request refused. Add the site to CORS_ORIGINS if it is your UI."},
                )
        return await call_next(request)
