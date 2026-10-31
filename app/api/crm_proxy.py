"""Reverse proxy to the Stock CRM backend (personal layer served by the CRM process).

Every request under /api/crm/* requires a login and is forwarded to the CRM's /api/* with the
caller's identity (X-User-Id / X-User-Name) and a shared secret (X-Facade-Token) so the CRM can
trust those headers. The CRM itself stays bound to 127.0.0.1.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from ..config import settings
from ..models import User
from .deps import current_user

router = APIRouter(prefix="/api/crm", tags=["crm-proxy"], dependencies=[Depends(current_user)])

_client = httpx.AsyncClient(base_url=settings.crm_base_url, timeout=settings.crm_timeout)

_HOP_BY_HOP = {"host", "content-length", "connection", "transfer-encoding", "keep-alive", "accept-encoding", "cookie"}
_PASS_RESPONSE = {"content-type", "cache-control"}


def identity_headers(user: User) -> dict[str, str]:
    h = {"X-User-Id": str(user.id), "X-User-Name": user.username, "X-User-Role": user.role}
    if settings.crm_facade_token:
        h["X-Facade-Token"] = settings.crm_facade_token
    return h


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request, user: User = Depends(current_user)) -> Response:
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP and not k.lower().startswith("x-user")}
    headers.update(identity_headers(user))
    body = await request.body()
    try:
        upstream = await _client.request(
            request.method,
            f"/api/{path}",
            params=list(request.query_params.multi_items()),
            content=body,
            headers=headers,
        )
    except httpx.HTTPError as exc:
        return JSONResponse(
            {"detail": f"stockcrm unreachable at {settings.crm_base_url}: {type(exc).__name__}"},
            status_code=502,
        )
    resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() in _PASS_RESPONSE}
    return Response(content=upstream.content, status_code=upstream.status_code, headers=resp_headers)


async def crm_health() -> dict:
    """Quick reachability probe used by /api/health."""
    try:
        r = await _client.get("/api/enums", timeout=2.0)
        return {"url": settings.crm_base_url, "reachable": r.status_code == 200}
    except httpx.HTTPError as exc:
        return {"url": settings.crm_base_url, "reachable": False, "error": type(exc).__name__}
