"""Render/export API: submit a job, poll it, download the artifact.

Owner: backend-render (task-9).  The router is intentionally thin; see
``app/services/render_service.py`` for composition and encoding.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..models.render import RenderJobInfo, RenderRequest
from ..services import render_service

log = logging.getLogger("mocadiff.render")

router = APIRouter(tags=["render"])


def _error(exc: render_service.RenderError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/render", response_model=RenderJobInfo)
def create_render(req: RenderRequest) -> RenderJobInfo:
    try:
        return render_service.submit(req)
    except render_service.RenderError as exc:
        raise _error(exc) from exc
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to the UI
        log.exception("could not create render job")
        raise HTTPException(status_code=500, detail=f"创建渲染任务失败：{exc}") from exc


@router.get("/render/{job_id}", response_model=RenderJobInfo)
def get_render(job_id: str) -> RenderJobInfo:
    job = render_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="渲染任务不存在。")
    return job


@router.get("/render/{job_id}/download")
def download_render(job_id: str) -> FileResponse:
    job = render_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="渲染任务不存在。")
    if job.status != "done":
        raise HTTPException(status_code=409, detail=f"任务尚未完成（{job.status}）。")
    path = render_service.output_path(job_id)
    if path is None:
        raise HTTPException(status_code=404, detail="渲染文件不存在或已被清理。")
    media_type = render_service.MEDIA_TYPES.get(path.suffix.lower(),
                                                "application/octet-stream")
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        headers={"Cache-Control": "no-store"},
    )
