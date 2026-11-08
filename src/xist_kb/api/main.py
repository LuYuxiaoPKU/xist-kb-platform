"""FastAPI application.

Serves the JSON API under `/api`; the built React frontend is mounted at `/`
when `web/dist` exists. Static serving is built into FastAPI on purpose: the
lab server has no nginx and `systemctl --user` is unavailable, so one uvicorn
process serves both halves.

Auth is applied to the API only -- the frontend shell has to load before a
browser can send a key, and it contains no data.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from xist_kb import __version__
from xist_kb.api.auth import guard
from xist_kb.api.routes import claims, papers

log = logging.getLogger(__name__)

WEB_DIST = Path(__file__).resolve().parent.parent.parent.parent / "web" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(
        title="XIST Knowledge Base",
        version=__version__,
        description=(
            "Claims extracted from the XIST/XCI literature, each with the paper's own "
            "words where they could be located and an honest label where they could not."
        ),
        dependencies=[Depends(guard)],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    app.include_router(claims.router)
    app.include_router(papers.router)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    if WEB_DIST.is_dir():
        # html=True makes StaticFiles serve index.html for "/" and for any path
        # that is not a file, which is what a single-page app needs for routing.
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    else:
        log.info("no frontend build at %s; serving the API only", WEB_DIST)

    return app


app = create_app()
