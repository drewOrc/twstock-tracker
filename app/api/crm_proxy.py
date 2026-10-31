"""Reverse proxy to the Stock CRM backend.

The unified frontend talks to one origin (this engine); every request under /api/crm/* is
forwarded verbatim to the CRM's /api/* (default http://127.0.0.1:8765). The CRM stays a
separate process with its own database and repository.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from ..config import settings

router = APIRouter(prefix="/api/crm", tags=["crm-proxy"])

_client = httpx.AsyncClient(base_url=settings.crm_base_url, timeout=settings.crm_timeout)

_HOP_BY_HOP = {"host", "content-length", "connection", "transfer-encoding", "keep-alive", "accept-encoding"}
_PASS_RESPONSE = {"content-type", "cache-control"}


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request) -> Response:
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
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
