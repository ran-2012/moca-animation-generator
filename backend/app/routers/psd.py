"""PSD router (CONTRACT.md §5.2).  Thin transport layer over psd_service."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from .. import config
from ..models.psd import BakeRequest, MappingProfile
from ..services import psd_service

router = APIRouter(prefix="/psd", tags=["psd"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, psd_service.PsdError):
        return HTTPException(status_code=exc.status_code, detail=exc.detail)
    return HTTPException(status_code=500, detail=f"PSD 处理失败：{exc}")


async def _call(func: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a blocking service call in the threadpool and normalise errors."""
    try:
        return await run_in_threadpool(func, *args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - mapped to an HTTP error
        raise _http_error(exc) from exc


@router.post("/upload")
async def upload_psd(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"PSD 超过大小限制（{config.MAX_UPLOAD_BYTES // (1024 * 1024)}MB）",
        )
    return await _call(psd_service.upload_psd, file.filename or "upload.psd", data)


@router.get("/{asset_id}/tree")
async def get_tree(asset_id: str) -> dict[str, Any]:
    return await _call(psd_service.layer_tree, asset_id)


@router.get("/{asset_id}/thumb/{layer_id}")
async def get_thumbnail(asset_id: str, layer_id: str, size: int = Query(160, ge=8, le=1024)) -> Response:
    payload = await _call(psd_service.thumbnail_png, asset_id, layer_id, size)
    return Response(
        content=payload,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{asset_id}/automap")
async def automap(asset_id: str) -> dict[str, Any]:
    return await _call(psd_service.automap, asset_id)


@router.put("/{asset_id}/profile")
async def save_profile(asset_id: str, payload: MappingProfile | None = Body(default=None)) -> dict[str, bool]:
    if payload is None:
        raise HTTPException(status_code=400, detail="缺少 profile 请求体")
    await _call(psd_service.save_profile, asset_id, payload.model_dump(exclude_none=True))
    return {"ok": True}


@router.post("/{asset_id}/bake")
async def bake(asset_id: str, payload: BakeRequest | None = Body(default=None)) -> dict[str, Any]:
    profile = payload.profile.model_dump(exclude_none=True) if payload is not None and payload.profile is not None else None
    return await _call(psd_service.bake, asset_id, profile)


@router.get("/{asset_id}/manifest")
async def get_manifest(asset_id: str) -> dict[str, Any]:
    manifest = await _call(psd_service.get_manifest, asset_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="尚未烘焙，manifest 不存在")
    return manifest


@router.get("/{asset_id}/preview")
async def get_preview(asset_id: str, width: int = Query(900, ge=64, le=4096)) -> Response:
    payload = await _call(psd_service.preview_png, asset_id, width)
    return Response(
        content=payload,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )
