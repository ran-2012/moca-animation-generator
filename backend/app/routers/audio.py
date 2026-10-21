"""Audio endpoints (CONTRACT.md §5.3). Owner: backend-svp."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from .. import config
from ..models.audio import (
    AudioSummary,
    BpmUpdate,
    OkResponse,
    PeaksResponse,
)
from ..services import audio_service

log = logging.getLogger("mocadiff.audio")

router = APIRouter(tags=["audio"])


@router.post("/audio/upload", response_model=AudioSummary)
async def upload_audio(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 200MB 上限")
    try:
        return audio_service.save_upload(file.filename or "audio", data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("audio upload failed")
        raise HTTPException(status_code=500, detail=f"音频处理失败: {exc}") from exc


@router.get("/audio/{asset_id}/peaks", response_model=PeaksResponse)
async def audio_peaks(
    asset_id: str,
    points: int = Query(default=audio_service.DEFAULT_POINTS,
                        ge=audio_service.MIN_POINTS,
                        le=audio_service.MAX_POINTS),
) -> dict:
    try:
        return audio_service.get_peaks(asset_id, points)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/audio/{asset_id}/bpm", response_model=OkResponse)
async def audio_bpm(asset_id: str, body: BpmUpdate) -> dict:
    try:
        return audio_service.set_bpm(asset_id, body.bpm, body.offset_sec)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/audio/{asset_id}/file")
async def audio_file(asset_id: str) -> FileResponse:
    try:
        path, media_type = audio_service.get_source_file(asset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # Starlette's FileResponse implements Range / 206 responses for <audio>.
    return FileResponse(path, media_type=media_type,
                        headers={"Cache-Control": "no-store"})
