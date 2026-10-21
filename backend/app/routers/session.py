"""Session persistence API.

The frontend saves a compact snapshot of the workspace (asset ids + UI state)
after meaningful edits and on page hide; on boot it asks for the last snapshot
and hydrates the UI.  Heavy derived data is re-fetched from the persisted
assets/caches instead of being duplicated here.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models.session import SessionResponse, SessionSaveResult, SessionState
from ..services import session_service

router = APIRouter(tags=["session"])


@router.get("/session", response_model=SessionResponse)
def get_session() -> SessionResponse:
    state, saved_at = session_service.load()
    return SessionResponse(session=state, savedAt=saved_at)


@router.get("/session/previous", response_model=SessionResponse)
def get_previous_session() -> SessionResponse:
    """Last project kept when LIVE/MOCK switching reset the workspace."""
    state, saved_at = session_service.load_previous()
    return SessionResponse(session=state, savedAt=saved_at)


@router.put("/session", response_model=SessionSaveResult)
def put_session(state: SessionState) -> SessionSaveResult:
    try:
        saved_at = session_service.save(state)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"会话保存失败：{exc}") from exc
    return SessionSaveResult(ok=True, savedAt=saved_at)


@router.delete("/session")
def delete_session() -> dict:
    session_service.clear()
    return {"ok": True}
