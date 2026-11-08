"""Access control: shared password plus an optional network allowlist.

The user's decision was "simple password / IP allowlist, no user system". Both
are optional and independent:

* `XIST_KB_API_KEY` unset -> no password required
* `XIST_KB_ALLOWED_NETS` unset -> any address allowed
* `XIST_KB_TRUST_PROXY=1` -> read the client address from `X-Forwarded-For`

The last one is off by default because trusting the header without a proxy in
front lets any client claim any address. The lab deployment sets it when the
service sits behind the university gateway.
"""

from __future__ import annotations

import ipaddress
import os
import secrets

from fastapi import HTTPException, Request, status

_PUBLIC_PATHS = frozenset({"/api/health", "/docs", "/openapi.json", "/redoc"})


def _allowed_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    raw = os.environ.get("XIST_KB_ALLOWED_NETS", "").strip()
    if not raw:
        return []
    nets = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            nets.append(ipaddress.ip_network(chunk, strict=False))
        except ValueError:
            # A malformed entry must not silently open the service; skipping it
            # would, so refuse to start the request path instead.
            raise RuntimeError(f"XIST_KB_ALLOWED_NETS has an invalid network: {chunk!r}") from None
    return nets


def client_host(request: Request) -> str:
    if os.environ.get("XIST_KB_TRUST_PROXY") == "1":
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


async def guard(request: Request) -> None:
    """FastAPI dependency applied to every /api route."""
    if request.url.path in _PUBLIC_PATHS:
        return

    nets = _allowed_networks()
    if nets:
        host = client_host(request)
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "client address is not an IP"
            ) from None
        if not any(address in net for net in nets):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "address not allowed")

    expected = os.environ.get("XIST_KB_API_KEY", "").strip()
    if expected:
        supplied = request.headers.get("x-api-key") or request.query_params.get("key")
        if not supplied or not secrets.compare_digest(supplied, expected):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "missing or wrong API key",
                headers={"WWW-Authenticate": "X-API-Key"},
            )
