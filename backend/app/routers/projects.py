"""Projects router (CONTRACT.md §5.4).  Thin transport layer over project_service."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from starlette.concurrency import run_in_threadpool

from ..models.project import ProjectCreate, ProjectPatch
from ..services import project_service

router = APIRouter(prefix="/projects", tags=["projects"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, project_service.ProjectError):
        return HTTPException(status_code=exc.status_code, detail=exc.detail)
    return HTTPException(status_code=500, detail=f"项目操作失败：{exc}")


async def _call(func: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return await run_in_threadpool(func, *args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc


@router.post("")
async def create_project(payload: ProjectCreate | None = Body(default=None)) -> dict[str, Any]:
    body = payload.model_dump(exclude_none=True) if payload is not None else {}
    return await _call(project_service.create_project, body)


@router.get("")
async def list_projects() -> list[dict[str, Any]]:
    return await _call(project_service.list_projects)


@router.get("/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    return await _call(project_service.get_project, project_id)


@router.put("/{project_id}")
async def update_project(project_id: str, payload: ProjectPatch | None = Body(default=None)) -> dict[str, Any]:
    if payload is None:
        raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象")
    return await _call(project_service.update_project, project_id, payload.model_dump(exclude_unset=True))


@router.delete("/{project_id}")
async def delete_project(project_id: str) -> dict[str, bool]:
    return await _call(project_service.delete_project, project_id)
