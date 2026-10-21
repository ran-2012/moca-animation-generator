"""Project storage service (CONTRACT.md §4.5, §5.4).

Projects are plain JSON files under ``data/projects/<id>/project.json``.  The
service validates identifiers before touching the filesystem so no request can
escape the projects root.
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import config, storage


class ProjectError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = int(status_code)
        self.detail = str(detail)


_PROJECT_ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
_MAX_NAME = 120


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_id(project_id: str) -> str:
    if not isinstance(project_id, str) or not _PROJECT_ID_RE.match(project_id):
        raise ProjectError(400, f"非法项目 ID: {project_id}")
    if project_id in (".", ".."):
        raise ProjectError(400, f"非法项目 ID: {project_id}")
    return project_id


def _project_dir(project_id: str) -> Path:
    _validate_id(project_id)
    root = config.PROJECTS_DIR.resolve()
    directory = (config.PROJECTS_DIR / project_id).resolve()
    if directory.parent != root:
        raise ProjectError(400, f"非法项目 ID: {project_id}")
    return directory


def _project_file(project_id: str) -> Path:
    return _project_dir(project_id) / "project.json"


def _ensure_root() -> Path:
    config.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    return config.PROJECTS_DIR


def _as_int(value: Any, field: str, minimum: int = 1, maximum: int = 100000) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ProjectError(400, f"{field} 必须是整数") from exc
    if number < minimum or number > maximum:
        raise ProjectError(400, f"{field} 超出范围（{minimum}-{maximum}）")
    return number


def _clean_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name:
        name = "未命名项目"
    return name[:_MAX_NAME]


def default_project(project_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    now = _iso_now()
    project: dict[str, Any] = {
        "id": project_id,
        "name": _clean_name(payload.get("name")),
        "fps": _as_int(payload.get("fps", 24), "fps", 1, 240),
        "width": _as_int(payload.get("width", 1080), "width", 16, 16384),
        "height": _as_int(payload.get("height", 1524), "height", 16, 16384),
        "createdAt": now,
        "updatedAt": now,
        "audio": payload.get("audio") if isinstance(payload.get("audio"), dict) else None,
        "characters": payload.get("characters") if isinstance(payload.get("characters"), list) else [],
        "timeline": payload.get("timeline") if isinstance(payload.get("timeline"), dict) else {},
    }
    for key, value in payload.items():
        if key not in project and key not in ("id", "createdAt", "updatedAt"):
            project[key] = value
    return project


def create_project(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _ensure_root()
    project_id = "p_" + storage.new_id()
    project = default_project(project_id, payload)
    storage.write_json(_project_file(project_id), project)
    return project


def list_projects() -> list[dict[str, Any]]:
    _ensure_root()
    items: list[dict[str, Any]] = []
    for directory in config.PROJECTS_DIR.iterdir():
        if not directory.is_dir() or not _PROJECT_ID_RE.match(directory.name):
            continue
        project = storage.read_json(directory / "project.json")
        if not isinstance(project, dict):
            continue
        items.append(
            {
                "id": str(project.get("id") or directory.name),
                "name": _clean_name(project.get("name")),
                "updatedAt": str(project.get("updatedAt") or project.get("createdAt") or ""),
            }
        )
    items.sort(key=lambda item: item["updatedAt"], reverse=True)
    return items


def get_project(project_id: str) -> dict[str, Any]:
    path = _project_file(project_id)
    project = storage.read_json(path)
    if not isinstance(project, dict):
        raise ProjectError(404, f"项目不存在: {project_id}")
    project.setdefault("id", project_id)
    project.setdefault("name", "未命名项目")
    project.setdefault("createdAt", "")
    project.setdefault("updatedAt", project.get("createdAt") or "")
    project.setdefault("characters", [])
    project.setdefault("timeline", {})
    return project


def update_project(project_id: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ProjectError(400, "请求体必须是 JSON 对象")
    existing = get_project(project_id)
    merged = dict(existing)
    for key, value in payload.items():
        if key in ("id", "createdAt"):
            continue
        merged[key] = value
    merged["id"] = project_id
    merged["name"] = _clean_name(merged.get("name"))
    merged["fps"] = _as_int(merged.get("fps", 24), "fps", 1, 240)
    merged["width"] = _as_int(merged.get("width", 1080), "width", 16, 16384)
    merged["height"] = _as_int(merged.get("height", 1524), "height", 16, 16384)
    if not isinstance(merged.get("characters"), list):
        merged["characters"] = []
    if not isinstance(merged.get("timeline"), dict):
        merged["timeline"] = {}
    if not isinstance(merged.get("audio"), dict):
        merged["audio"] = None
    merged["updatedAt"] = _iso_now()
    storage.write_json(_project_file(project_id), merged)
    return merged


def delete_project(project_id: str) -> dict[str, bool]:
    directory = _project_dir(project_id)
    if not directory.is_dir():
        raise ProjectError(404, f"项目不存在: {project_id}")
    shutil.rmtree(directory)
    return {"ok": True}
