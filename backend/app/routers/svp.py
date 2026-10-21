"""SVP endpoints (CONTRACT.md §5.3). Owner: backend-svp."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from .. import config
from ..models.svp import SvpUploadResponse, TimelineRequest, TimelineResponse
from ..services import svp_service

log = logging.getLogger("mocadiff.svp")

router = APIRouter(tags=["svp"])


@router.post("/svp/upload", response_model=SvpUploadResponse)
async def upload_svp(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 200MB 上限")
    try:
        return svp_service.save_upload(file.filename or "source.svp", data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("SVP upload failed")
        raise HTTPException(status_code=500, detail=f"SVP 解析失败: {exc}") from exc


@router.post("/svp/{asset_id}/timeline", response_model=TimelineResponse)
async def svp_timeline(asset_id: str, body: TimelineRequest) -> dict:
    try:
        return svp_service.generate_timeline(
            asset_id,
            body.track_index,
            body.fps,
            psd_asset_id=body.psd_asset_id,
            mapping_set_id=body.mapping_set_id,
            animation_mode_id=body.animation_mode_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, IndexError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("SVP timeline failed for %s", asset_id)
        raise HTTPException(status_code=500, detail=f"时间轴生成失败: {exc}") from exc


@router.get("/svp/{asset_id}", response_model=SvpUploadResponse)
async def svp_info(asset_id: str) -> dict:
    """Re-read a previously uploaded project (used when a page reloads)."""
    try:
        return svp_service.list_tracks(asset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
