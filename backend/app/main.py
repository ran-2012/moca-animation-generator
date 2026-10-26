"""MocaDiff Studio backend entry point.

Run:  python -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --reload
(from the moca-diff/backend directory, or use the launcher in README).
"""

from __future__ import annotations

import importlib
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, storage

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mocadiff")

app = FastAPI(title="MocaDiff Studio", version=config.APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers are owned by the domain modules.  Missing ones are tolerated so the
# app still boots while the team is landing features in parallel.
_ROUTER_MODULES = ("psd", "svp", "audio", "projects", "ai", "render", "session")
for module_name in _ROUTER_MODULES:
    try:
        module = importlib.import_module(f".routers.{module_name}", package=__package__)
    except Exception as exc:  # pragma: no cover - visible in the log
        log.warning("router %s not available: %s", module_name, exc)
        continue
    router = getattr(module, "router", None)
    if router is not None:
        app.include_router(router, prefix="/api")


@app.on_event("startup")
def _startup() -> None:
    config.ensure_dirs()
    (config.DATA_DIR / "tmp").mkdir(parents=True, exist_ok=True)
    # A killed export leaves frames.zip.part behind; drop it on boot so the
    # renders directory does not silently grow by hundreds of MB.
    try:
        from .services import render_service

        removed = render_service.cleanup_stale_parts()
        if removed:
            log.info("removed %d stale render part file(s)", removed)
    except Exception as exc:  # pragma: no cover - best effort
        log.warning("could not clean stale render files: %s", exc)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": config.APP_VERSION}


# Runtime files (PSD cache, thumbnails, project assets) are served from /media.
config.ensure_dirs()
app.mount("/media", StaticFiles(directory=str(config.ASSETS_DIR)), name="media")

# A production build of the React app, when present, is served from /.
if config.FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIST), html=True), name="frontend")
